"""Edge case tests for _MonitorParser state machine: state transitions,
corruption recovery, and boundary conditions in the parser's internal slots.

Covers: rapid state flips, missing Removed, device context attacks,
object path collisions, and the interaction between job tracking and
device name tracking.
"""

import unittest

from unmount_image._monitor import _MonitorParser


class TestParserStateTransitions(unittest.TestCase):
    """Tests state transitions under unexpected input sequences."""

    def test_job_added_while_already_in_job(self):
        """A new Added resets state even if no Removed for previous job."""
        p = _MonitorParser()
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          filesystem-mount')
        p.feed('    Objects:            /org/.../block_devices/loop0')
        self.assertTrue(p._emitted)

        # Second Added before Removed — resets state
        p.feed('Added /org/freedesktop/UDisks2/jobs/2')
        self.assertFalse(p._emitted)
        self.assertEqual(p._job_op, '')
        self.assertEqual(p._job_objects, '')

    def test_removed_without_added(self):
        """Removed is a no-op when not in a job."""
        p = _MonitorParser()
        p.feed('Removed /org/freedesktop/UDisks2/jobs/1')
        self.assertFalse(p._in_job)

    def test_property_feeding_without_device_context(self):
        """BackingFile without any device context should be ignored."""
        p = _MonitorParser()
        r = p.feed('  BackingFile:          /tmp/img')
        self.assertIsNone(r)

    def test_device_context_persists_across_unrelated_lines(self):
        """Device name should not be cleared by unrelated lines."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        self.assertEqual(p._current_device, 'loop0')

        # Empty line does not clear context
        p.feed('')
        self.assertEqual(p._current_device, 'loop0')

        # Preamble does not clear context
        p.feed('Monitoring the udisks daemon. Press Ctrl+C to exit.')
        self.assertEqual(p._current_device, 'loop0')

    def test_device_context_overwritten_by_new_device(self):
        """A new device path overwrites the old context."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        self.assertEqual(p._current_device, 'loop0')
        p.feed('/org/.../block_devices/loop1: '
               'org.freedesktop.UDisks2.Block: Properties Changed')
        self.assertEqual(p._current_device, 'loop1')

    def test_device_context_not_set_by_job_path(self):
        """Job paths should not change _current_device."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Block: Properties Changed')
        self.assertEqual(p._current_device, 'loop0')
        p.feed('/org/freedesktop/UDisks2/jobs/1: '
               'org.freedesktop.UDisks2.Job::Completed (true, \'\')')
        self.assertEqual(p._current_device, 'loop0')

    def test_device_context_not_set_by_drive_path(self):
        """Drive paths should not set device context."""
        p = _MonitorParser()
        p.feed('/org/freedesktop/UDisks2/drives/ST1000DM010: '
               'org.freedesktop.UDisks2.Drive: Properties Changed')
        self.assertEqual(p._current_device, '')

    def test_backing_file_after_device_switch(self):
        """After switching devices, BackingFile applies to the new device."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        self.assertEqual(p._current_device, 'loop0')

        p.feed('/org/.../block_devices/loop1: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        self.assertEqual(p._current_device, 'loop1')

        r = p.feed('  BackingFile:          /tmp/b.img')
        self.assertEqual(r[1]['device'], 'loop1')
        self.assertEqual(r[1]['value'], '/tmp/b.img')

    def test_emitted_flag_prevents_re_emit(self):
        """Once a job is emitted, further property lines don't re-emit."""
        p = _MonitorParser()
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          filesystem-mount')
        p.feed('    Objects:            /org/.../block_devices/loop0')
        self.assertTrue(p._emitted)
        # Progress update — should not emit another job event
        r = p.feed('    Progress:           0.5')
        self.assertIsNone(r)

    def test_emitted_reset_on_new_job(self):
        """New Added clears _emitted flag."""
        p = _MonitorParser()
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          filesystem-mount')
        p.feed('    Objects:            /org/.../block_devices/loop0')
        self.assertTrue(p._emitted)
        p.feed('Added /org/freedesktop/UDisks2/jobs/2')
        self.assertFalse(p._emitted)


class TestParserBoundaryInput(unittest.TestCase):
    """Tests parser behaviour with unusual/malformed input."""

    def test_line_with_only_ansi(self):
        p = _MonitorParser()
        r = p.feed('\x1b[1m\x1b[33m\x1b[0m')
        self.assertIsNone(r)

    def test_line_longer_than_typical(self):
        """Very long property values shouldn't crash parsing."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        long_path = '/tmp/' + 'x' * 2000 + '.img'
        r = p.feed(f'  BackingFile:          {long_path}')
        self.assertIsNotNone(r)
        self.assertEqual(r[1]['value'], long_path)

    def test_line_with_only_whitespace(self):
        p = _MonitorParser()
        r = p.feed('          ')
        self.assertIsNone(r)

    def test_line_with_tab_characters(self):
        """Tabs in lines should not break parsing."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        r = p.feed('  \tBackingFile:          /tmp/img')
        self.assertIsNotNone(r)
        self.assertEqual(r[1]['value'], '/tmp/img')

    def test_multiple_colons_in_line(self):
        """Device name extraction should handle multiple colons."""
        p = _MonitorParser()
        r = p.feed('/org/.../block_devices/loop0: '
                   'org.freedesktop.UDisks2.Block: Properties Changed '
                   ': extra')
        self.assertIsNone(r)
        self.assertEqual(p._current_device, 'loop0')

    def test_backing_file_value_with_colon(self):
        """BackingFile value containing a colon (unlikely but possible)."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        r = p.feed('  BackingFile:          /tmp/img:backup')
        self.assertEqual(r[1]['value'], '/tmp/img:backup')

    def test_job_completed_failure_message(self):
        """Job::Completed with a failure message. The parser doesn't parse
        Completed lines, but they shouldn't break state."""
        p = _MonitorParser()
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          filesystem-mount')
        p.feed('    Objects:            /org/.../block_devices/loop0')
        # Completed with failure
        r = p.feed('/org/.../jobs/1: '
                   'org.freedesktop.UDisks2.Job::Completed '
                   '(false, \'Not authorized\')')
        self.assertIsNone(r)
        # State should be unaffected
        self.assertTrue(p._in_job)

    def test_job_number_boundary(self):
        """Job numbers are monotonic integers; test large values."""
        p = _MonitorParser()
        p.feed('Added /org/freedesktop/UDisks2/jobs/999999999')
        p.feed('    Operation:          filesystem-mount')
        r = p.feed('    Objects:            /org/.../block_devices/loop0')
        self.assertIsNotNone(r)

    def test_device_name_numeric(self):
        """Device names like 'loop0', 'sda1', 'nvme0n1p2' should all work."""
        p = _MonitorParser()
        for name in ['loop0', 'loop99', 'sda', 'sda1', 'sdb15',
                      'nvme0n1', 'nvme0n1p1', 'dm-0', 'md0']:
            with self.subTest(name=name):
                p = _MonitorParser()
                p.feed(f'/org/.../block_devices/{name}: '
                       'org.freedesktop.UDisks2.Block: Properties Changed')
                self.assertEqual(p._current_device, name)
