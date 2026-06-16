"""Edge case tests for concurrent events from multiple loop devices.

When 3+ devices are set up, mounted, unmounted, and detached concurrently,
events interleave across devices. This tests the parser's ability to
correctly attribute property changes to the right device when lines
from different devices arrive in rapid succession.

Based on real udisksctl monitor output captured from concurrent operations.
"""

import unittest

from unmount_image._monitor import _MonitorParser, _UdisksMonitor


# Real interleaved output from 3 concurrent loop setups (captured manually)
INTERLEAVED_SETUP_OUTPUT = """\
/org/freedesktop/UDisks2/block_devices/loop2: org.freedesktop.UDisks2.Block: Properties Changed
  IdUUID:               1648-D8F4
  IdType:               vfat
  Size:                 1048576
/org/freedesktop/UDisks2/block_devices/loop2: Added interface org.freedesktop.UDisks2.Filesystem
/org/freedesktop/UDisks2/block_devices/loop2: org.freedesktop.UDisks2.Loop: Properties Changed
  SetupByUID:           1000
  BackingFile:          /tmp/concur_a.img
/org/freedesktop/UDisks2/block_devices/loop3: org.freedesktop.UDisks2.Block: Properties Changed
  IdUUID:               1649-241D
  IdType:               vfat
  Size:                 1048576
/org/freedesktop/UDisks2/block_devices/loop3: Added interface org.freedesktop.UDisks2.Filesystem
/org/freedesktop/UDisks2/block_devices/loop3: org.freedesktop.UDisks2.Loop: Properties Changed
  SetupByUID:           1000
  BackingFile:          /tmp/concur_b.img
/org/freedesktop/UDisks2/block_devices/loop4: org.freedesktop.UDisks2.Block: Properties Changed
  IdUUID:               1649-61C3
  IdType:               vfat
  Size:                 1048576
/org/freedesktop/UDisks2/block_devices/loop4: Added interface org.freedesktop.UDisks2.Filesystem
/org/freedesktop/UDisks2/block_devices/loop4: org.freedesktop.UDisks2.Loop: Properties Changed
  SetupByUID:           1000
  BackingFile:          /tmp/concur_c.img
"""

INTERLEAVED_DETACH_OUTPUT = """\
/org/freedesktop/UDisks2/block_devices/loop3: org.freedesktop.UDisks2.Loop: Properties Changed
  SetupByUID:           0
  Autoclear:            false
  BackingFile:          
/org/freedesktop/UDisks2/block_devices/loop4: org.freedesktop.UDisks2.Filesystem: Properties Changed
  MountPoints:          
/org/freedesktop/UDisks2/block_devices/loop4: org.freedesktop.UDisks2.Loop: Properties Changed
  SetupByUID:           0
  Autoclear:            false
  BackingFile:          
/org/freedesktop/UDisks2/block_devices/loop2: org.freedesktop.UDisks2.Loop: Properties Changed
  SetupByUID:           0
  Autoclear:            false
  BackingFile:          
/org/freedesktop/UDisks2/block_devices/loop4: org.freedesktop.UDisks2.Block: Properties Changed
  IdUUID:               
  IdType:               
  Size:                 0
/org/freedesktop/UDisks2/block_devices/loop4: Removed interface org.freedesktop.UDisks2.Filesystem
/org/freedesktop/UDisks2/block_devices/loop3: org.freedesktop.UDisks2.Block: Properties Changed
  IdUUID:               
  IdType:               
  Size:                 0
/org/freedesktop/UDisks2/block_devices/loop3: Removed interface org.freedesktop.UDisks2.Filesystem
/org/freedesktop/UDisks2/block_devices/loop2: org.freedesktop.UDisks2.Block: Properties Changed
  IdUUID:               
  IdType:               
  Size:                 0
/org/freedesktop/UDisks2/block_devices/loop2: Removed interface org.freedesktop.UDisks2.Filesystem
"""


class TestConcurrentDeviceSetup(unittest.TestCase):
    """Parser correctly attributes events when 3 devices set up
    concurrently."""

    def test_three_devices_property_attribution(self):
        """Each device's BackingFile should be attributed to the correct
        device, even when events interleave."""
        p = _MonitorParser()
        events = []
        for line in INTERLEAVED_SETUP_OUTPUT.split('\n'):
            if not line.strip():
                continue
            r = p.feed(line)
            if r:
                events.append(r)

        backing_events = [e for e in events
                          if e[0] == 'loop_prop'
                          and e[1]['prop'] == 'BackingFile']
        self.assertEqual(len(backing_events), 3)

        by_device = {}
        for e in backing_events:
            by_device[e[1]['device']] = e[1]['value']

        self.assertEqual(by_device.get('loop2'), '/tmp/concur_a.img')
        self.assertEqual(by_device.get('loop3'), '/tmp/concur_b.img')
        self.assertEqual(by_device.get('loop4'), '/tmp/concur_c.img')

    def test_interleaved_device_context_switching(self):
        """Device context switches correctly when lines from different
        devices arrive consecutively."""
        p = _MonitorParser()

        p.feed('/org/.../block_devices/loop2: '
               'org.freedesktop.UDisks2.Block: Properties Changed')
        self.assertEqual(p._current_device, 'loop2')

        # loop3 line arrives before loop2 line is resolved
        p.feed('/org/.../block_devices/loop3: '
               'org.freedesktop.UDisks2.Block: Properties Changed')
        self.assertEqual(p._current_device, 'loop3')

        # BackingFile belongs to loop3, not loop2
        r = p.feed('  BackingFile:          /tmp/concur_b.img')
        self.assertEqual(r[1]['device'], 'loop3')

    def test_device_switch_mid_property_block(self):
        """A device switch while reading properties of the current device
        should correctly attribute to the new device."""
        p = _MonitorParser()

        p.feed('/org/.../block_devices/loop2: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        self.assertEqual(p._current_device, 'loop2')

        # Start reading loop2's properties
        self.assertIsNone(p.feed('  SetupByUID:           1000'))

        # Mid-property: loop3's header arrives!
        p.feed('/org/.../block_devices/loop3: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        self.assertEqual(p._current_device, 'loop3')

        # BackingFile now belongs to loop3
        r = p.feed('  BackingFile:          /tmp/concur_b.img')
        self.assertEqual(r[1]['device'], 'loop3')


class TestConcurrentDeviceDetach(unittest.TestCase):
    """Parser correctly handles interleaved detach events from concurrent
    loop-delete operations."""

    def test_multiple_backing_files_cleared(self):
        """All three devices' BackingFile should be detected as cleared
        in the correct order."""
        p = _MonitorParser()
        events = []
        for line in INTERLEAVED_DETACH_OUTPUT.split('\n'):
            if not line.strip():
                continue
            r = p.feed(line)
            if r:
                events.append(r)

        cleared = [e for e in events
                   if e[0] == 'loop_prop'
                   and e[1]['prop'] == 'BackingFile'
                   and not e[1]['value']]
        self.assertEqual(len(cleared), 3)
        devices_cleared = {e[1]['device'] for e in cleared}
        self.assertEqual(devices_cleared, {'loop2', 'loop3', 'loop4'})

    def test_interleaved_filesystem_removal(self):
        """Filesystem interface removal events interleave with
        BackingFile clears."""
        p = _MonitorParser()
        events = []
        for line in INTERLEAVED_DETACH_OUTPUT.split('\n'):
            if not line.strip():
                continue
            r = p.feed(line)
            if r:
                events.append(r)

        # loop4 has MountPoints cleared (line 61) between loop3 and
        # loop4 Loop property clears
        loop_props = [e for e in events if e[0] == 'loop_prop']
        # All loop_prop events are BackingFile (the only property matched)
        self.assertTrue(all(e[1]['prop'] == 'BackingFile'
                            for e in loop_props))


class TestConcurrentMonitorSignals(unittest.TestCase):
    """_UdisksMonitor signal handling with concurrent events."""

    def test_mount_detected_on_target_among_many(self):
        """Among many jobs for different devices, only the one targeting
        our device should signal mount_detected."""
        m = _UdisksMonitor('loop2')

        # Unrelated job
        m._handle_event(
            ('job', {'op': 'filesystem-mount',
                     'objects': '/org/.../block_devices/loop3'}))
        self.assertFalse(m.mount_detected.is_set())

        # Target job
        m._handle_event(
            ('job', {'op': 'filesystem-mount',
                     'objects': '/org/.../block_devices/loop2'}))
        self.assertTrue(m.mount_detected.is_set())

    def test_backing_cleared_on_target_among_many(self):
        """Among many property changes, only our target device's
        BackingFile clear should signal."""
        m = _UdisksMonitor('loop2')

        # Unrelated device clears BackingFile
        m._handle_event(
            ('loop_prop', {'device': 'loop3', 'prop': 'BackingFile',
                           'value': ''}))
        self.assertFalse(m.backing_cleared.is_set())

        # Target device clears BackingFile
        m._handle_event(
            ('loop_prop', {'device': 'loop2', 'prop': 'BackingFile',
                           'value': ''}))
        self.assertTrue(m.backing_cleared.is_set())
