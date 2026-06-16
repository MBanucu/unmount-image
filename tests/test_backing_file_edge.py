"""Edge case tests for BackingFile property handling in udisksctl monitor.

Covers: the complete BackingFile lifecycle across setup/mount/unmount/detach,
thresholds between empty and non-empty, the interaction with Autoclear,
and the key signal used by unmount-image's detach confirmation.
"""

import unittest

from unmount_image._monitor import _MonitorParser, _UdisksMonitor


class TestBackingFileLifecycle(unittest.TestCase):
    """Complete BackingFile lifecycle through the parser."""

    def test_full_lifecycle_setup_to_detach(self):
        """BackingFile: (not present) -> path -> path -> empty."""
        p = _MonitorParser()
        events = []

        # 1. Loop setup: BackingFile appears with path
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        r = p.feed('  BackingFile:          /tmp/img')
        events.append(r)
        self.assertEqual(r[1]['value'], '/tmp/img')

        # 2. Mount: BackingFile stays the same (no change event)
        # 3. Unmount: BackingFile stays the same (no change event)

        # 4. Detach: BackingFile becomes empty
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        r = p.feed('  BackingFile:          ')
        events.append(r)
        self.assertEqual(r[1]['value'], '')

    def test_backing_file_change_without_header(self):
        """BackingFile property line appears without a preceding header.
        Should use the last-known device."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        p.feed('  SetupByUID:           1000')
        p.feed('  BackingFile:          /tmp/a.img')
        # Now a BackingFile change without header — should still use
        # _current_device (loop0) unless overwritten
        r = p.feed('  BackingFile:          ')
        self.assertEqual(r[1]['device'], 'loop0')
        self.assertEqual(r[1]['value'], '')

    def test_autoclear_and_backing_file_together(self):
        """Autoclear and BackingFile change in the same Properties
        Changed event."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')

        # Both properties change simultaneously (common during detach)
        self.assertIsNone(p.feed('  Autoclear:            false'))
        r = p.feed('  BackingFile:          ')
        self.assertEqual(r[1]['value'], '')

    def test_backing_file_with_autoclear_cycle(self):
        """Autoclear true -> false + BackingFile cleared =
        definitive detach signal."""
        p = _MonitorParser()

        # Setup
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        p.feed('  SetupByUID:           1000')
        p.feed('  BackingFile:          /tmp/img')

        # After mount, Autoclear becomes true
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        self.assertIsNone(p.feed('  Autoclear:            true'))

        # Detach: Autoclear becomes false, BackingFile cleared
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        self.assertIsNone(p.feed('  Autoclear:            false'))
        r = p.feed('  BackingFile:          ')
        self.assertEqual(r[1]['value'], '')


class TestBackingFileMonitorSignals(unittest.TestCase):
    """_UdisksMonitor signal behaviour for BackingFile events."""

    def test_empty_backing_file_triggers_signal(self):
        m = _UdisksMonitor('loop0')
        m._handle_event(
            ('loop_prop', {'device': 'loop0', 'prop': 'BackingFile',
                           'value': ''}))
        self.assertTrue(m.backing_cleared.is_set())

    def test_non_empty_backing_file_does_not_trigger(self):
        m = _UdisksMonitor('loop0')
        m._handle_event(
            ('loop_prop', {'device': 'loop0', 'prop': 'BackingFile',
                           'value': '/tmp/img'}))
        self.assertFalse(m.backing_cleared.is_set())

    def test_empty_backing_file_wrong_device_ignored(self):
        m = _UdisksMonitor('loop0')
        m._handle_event(
            ('loop_prop', {'device': 'loop9', 'prop': 'BackingFile',
                           'value': ''}))
        self.assertFalse(m.backing_cleared.is_set())

    def test_non_backing_prop_empty_value_ignored(self):
        """A non-BackingFile property with empty value should not trigger."""
        # The parser only emits 'loop_prop' for BackingFile, so this
        # shouldn't reach _handle_event. But test defensively.
        m = _UdisksMonitor('loop0')
        m._handle_event(
            ('loop_prop', {'device': 'loop0', 'prop': 'MountPoints',
                           'value': ''}))
        # prop is 'MountPoints', not 'BackingFile' — should not trigger
        self.assertFalse(m.backing_cleared.is_set())

    def test_rapid_set_clear_sequence(self):
        """BackingFile: set -> cleared -> set all within the same
        Properties Changed event block (extreme edge case)."""
        m = _UdisksMonitor('loop0')
        m.reset_events()
        self.assertFalse(m.backing_cleared.is_set())

        # Rapid toggling
        m._handle_event(
            ('loop_prop', {'device': 'loop0', 'prop': 'BackingFile',
                           'value': '/tmp/a.img'}))
        self.assertFalse(m.backing_cleared.is_set())

        m._handle_event(
            ('loop_prop', {'device': 'loop0', 'prop': 'BackingFile',
                           'value': ''}))
        self.assertTrue(m.backing_cleared.is_set())

        m._handle_event(
            ('loop_prop', {'device': 'loop0', 'prop': 'BackingFile',
                           'value': '/tmp/b.img'}))
        # backing_cleared stays set until reset_events
        self.assertTrue(m.backing_cleared.is_set())

    def test_with_spaces_in_backing_file_path(self):
        """Monitor test: BackingFile with spaces in path should not
        break signal detection."""
        m = _UdisksMonitor('loop0')

        # Set with path containing spaces
        m._handle_event(
            ('loop_prop', {'device': 'loop0', 'prop': 'BackingFile',
                           'value': '/home/user/my disk.img'}))
        self.assertFalse(m.backing_cleared.is_set())

        # Clear
        m._handle_event(
            ('loop_prop', {'device': 'loop0', 'prop': 'BackingFile',
                           'value': ''}))
        self.assertTrue(m.backing_cleared.is_set())

    def test_setupbyuid_zero_with_backing_clear(self):
        """SetupByUID becomes 0 simultaneously with BackingFile clear.
        Both changes arrive in the same Properties Changed event."""
        m = _UdisksMonitor('loop0')
        # SetupByUID:0 — parser ignores it
        # BackingFile:'' — triggers signal
        m._handle_event(
            ('loop_prop', {'device': 'loop0', 'prop': 'BackingFile',
                           'value': ''}))
        self.assertTrue(m.backing_cleared.is_set())
