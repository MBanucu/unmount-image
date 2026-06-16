"""Edge case tests for loop device number recycling.

When a loop device is detached and a new image is set up immediately, the
kernel can recycle the same device number (e.g., loop1). The monitor sees:
  1. BackingFile cleared (empty)
  2. 50-150ms later: new Block properties appear on the same device name
  3. Filesystem interface Added
  4. BackingFile set to the new image path

This is a critical edge case for detach confirmation: observing BackingFile
become empty on loopX is NOT sufficient proof that loopX stayed detached
— it may have been immediately reused by another process.
"""

import threading
import unittest

from unmount_image._monitor import _MonitorParser, _UdisksMonitor


class TestLoopDeviceRecycling(unittest.TestCase):
    """Tests parser and monitor behaviour when loop device numbers are
    recycled (reused after detach)."""

    def test_backing_file_cleared_then_reset_same_device(self):
        """Simulate: detach clears BackingFile, then a new loop-setup
        immediately reuses the same device number and sets BackingFile
        to a different path."""
        p = _MonitorParser()

        # Original loop setup on loop1
        p.feed('/org/freedesktop/UDisks2/block_devices/loop1: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        r1 = p.feed('  BackingFile:          /tmp/edge_test_1.img')
        self.assertEqual(r1[1]['device'], 'loop1')
        self.assertEqual(r1[1]['value'], '/tmp/edge_test_1.img')

        # Detach: BackingFile cleared (line 237 from real output)
        r2 = p.feed('  BackingFile:          ')
        self.assertEqual(r2[1]['device'], 'loop1')
        self.assertEqual(r2[1]['value'], '')
        self.assertTrue(not r2[1]['value'])

        # Recycling: same loop1 gets new BackingFile (line 232-236 real
        # output: block zeroed, Filesystem removed, then...)
        p.feed('/org/freedesktop/UDisks2/block_devices/loop1: '
               'org.freedesktop.UDisks2.Block: Properties Changed')
        self.assertIsNone(p.feed('  IdUUID:               12D4-9566'))
        self.assertIsNone(p.feed('  Size:                 1048576'))

        p.feed('/org/freedesktop/UDisks2/block_devices/loop1: '
               'Added interface org.freedesktop.UDisks2.Filesystem')

        p.feed('/org/freedesktop/UDisks2/block_devices/loop1: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        r3 = p.feed('  BackingFile:          /tmp/edge_test_2.img')
        self.assertEqual(r3[1]['device'], 'loop1')
        self.assertEqual(r3[1]['value'], '/tmp/edge_test_2.img')

    def test_monitor_signal_on_recycled_device(self):
        """_UdisksMonitor must check both device name AND BackingFile
        value before signalling backing_cleared. A re-setup after clearing
        should trigger a new BackingFile event with a non-empty value."""
        m = _UdisksMonitor('loop1')

        # Simulate monitoring: BackingFile becomes non-empty first
        m._handle_event(
            ('loop_prop', {'device': 'loop1', 'prop': 'BackingFile',
                           'value': '/tmp/a.img'}))
        self.assertFalse(m.backing_cleared.is_set())

        # BackingFile cleared — signal
        m._handle_event(
            ('loop_prop', {'device': 'loop1', 'prop': 'BackingFile',
                           'value': ''}))
        self.assertTrue(m.backing_cleared.is_set())

        # Recycling: loop1 gets new BackingFile
        # The monitor would see this but backing_cleared is already set.
        # The _DetachThread checks mount_detected after backing_cleared
        # and the 0.3s grace period handles this.
        m.reset_events()
        m._handle_event(
            ('loop_prop', {'device': 'loop1', 'prop': 'BackingFile',
                           'value': '/tmp/b.img'}))
        self.assertFalse(m.backing_cleared.is_set())

    def test_recycling_race_condition(self):
        """Real observed sequence: BackingFile cleared on loop1 at
        the same timestamp as new block properties appear on the
        recycled loop1 (within same millisecond)."""
        p = _MonitorParser()

        # Detach sequence (from real output)
        lines = [
            '/org/.../block_devices/loop1: '
            'org.freedesktop.UDisks2.Loop: Properties Changed',
            '  SetupByUID:           0',
            '  Autoclear:            false',
            '  BackingFile:          ',  # ← cleared
            # Simultaneously, recycled device appears:
            '/org/.../block_devices/loop1: '
            'org.freedesktop.UDisks2.Block: Properties Changed',
            '  IdUUID:               12D4-9566',
            '  IdVersion:            FAT12',
            '  IdType:               vfat',
            '  BackingFile:          /tmp/edge_test_2.img',  # ← re-set!
        ]

        events = []
        for line in lines:
            r = p.feed(line)
            if r:
                events.append(r)

        backing_events = [e for e in events
                          if e[0] == 'loop_prop'
                          and e[1]['prop'] == 'BackingFile']
        self.assertEqual(len(backing_events), 2)
        self.assertEqual(backing_events[0][1]['value'], '')
        self.assertEqual(backing_events[1][1]['value'],
                         '/tmp/edge_test_2.img')

    def test_three_device_recycling_sequence(self):
        """Three loop devices detach concurrently, and their numbers
        can get recycled during the event burst."""
        p = _MonitorParser()
        events = []

        # Three devices set up
        for dev in ['loop2', 'loop3', 'loop4']:
            p.feed(f'/org/.../block_devices/{dev}: '
                   'org.freedesktop.UDisks2.Loop: Properties Changed')
            r = p.feed(f'  BackingFile:          /tmp/concur_{dev[-1]}.img')
            events.append(r)

        # All three BackingFiles cleared (detach)
        for dev in ['loop2', 'loop3', 'loop4']:
            p.feed(f'/org/.../block_devices/{dev}: '
                   'org.freedesktop.UDisks2.Loop: Properties Changed')
            r = p.feed('  BackingFile:          ')
            events.append(r)

        backing_clears = [e for e in events
                          if e[0] == 'loop_prop'
                          and not e[1]['value']]
        self.assertEqual(len(backing_clears), 3)

    def test_monitor_backing_cleared_reset_properly_after_recycling(self):
        """Test that after a recycled device sets BackingFile again,
        the monitor's backing_cleared event resets correctly."""
        m = _UdisksMonitor('loop1')

        # Initial setup — don't set backing_cleared
        m._handle_event(
            ('loop_prop', {'device': 'loop1', 'prop': 'BackingFile',
                           'value': '/tmp/a.img'}))
        self.assertFalse(m.backing_cleared.is_set())

        # Detach — signal
        m._handle_event(
            ('loop_prop', {'device': 'loop1', 'prop': 'BackingFile',
                           'value': ''}))
        self.assertTrue(m.backing_cleared.is_set())

        # reset_events should clear it for the next detach cycle
        m.reset_events()
        self.assertFalse(m.backing_cleared.is_set())

        # Recycling: new path set — should not trigger backing_cleared
        m._handle_event(
            ('loop_prop', {'device': 'loop1', 'prop': 'BackingFile',
                           'value': '/tmp/b.img'}))
        self.assertFalse(m.backing_cleared.is_set())
