"""Edge case tests for ANSI escape sequence handling in udisksctl monitor
output parsing.

Covers every SGR code emitted by udisksctl, malformed sequences,
nested/adjacent escapes, and the interaction between ANSI stripping
and property value extraction.
"""

import unittest

from unmount_image._monitor import _ANSI_RE, _MonitorParser


class TestAnsiStrippingRegex(unittest.TestCase):
    """Exhaustive test of the ANSI stripping regex against all SGR codes
    emitted by udisksctl monitor."""

    def test_all_ansi_sgr_codes(self):
        """udisksctl uses codes 0,1,31,32,33,34,35,37 with and without
        bold."""
        test_cases = [
            # (raw, expected_clean)
            ('\x1b[0m', ''),
            ('\x1b[1m', ''),
            ('\x1b[31m', ''),
            ('\x1b[32m', ''),
            ('\x1b[33m', ''),
            ('\x1b[34m', ''),
            ('\x1b[35m', ''),
            ('\x1b[37m', ''),
            ('\x1b[1;33m', ''),
            ('\x1b[1;34m', ''),
            ('\x1b[1;35m', ''),
            ('\x1b[1;37m', ''),
            ('\x1b[1;32m', ''),
            ('\x1b[1;31m', ''),
        ]
        for raw, expected in test_cases:
            with self.subTest(raw=repr(raw)):
                self.assertEqual(_ANSI_RE.sub('', raw), expected)

    def test_multiple_adjacent_escapes(self):
        raw = '\x1b[1m\x1b[33m12:03:36.774:\x1b[0m'
        clean = _ANSI_RE.sub('', raw)
        self.assertEqual(clean, '12:03:36.774:')
        self.assertNotIn('\x1b', clean)

    def test_nested_escapes(self):
        raw = '\x1b[1m\x1b[34m/org/.../loop3:\x1b[0m'
        clean = _ANSI_RE.sub('', raw)
        self.assertEqual(clean, '/org/.../loop3:')

    def test_escapeless_text_unchanged(self):
        text = '  BackingFile:          /tmp/img'
        self.assertEqual(_ANSI_RE.sub('', text), text)

    def test_empty_string(self):
        self.assertEqual(_ANSI_RE.sub('', ''), '')

    def test_only_ansi(self):
        self.assertEqual(
            _ANSI_RE.sub('', '\x1b[1m\x1b[31m\x1b[0m'), '')

    def test_ansi_mid_text(self):
        raw = '  \x1b[37mBackingFile:\x1b[0m          \x1b[37m/tmp/img\x1b[0m'
        clean = _ANSI_RE.sub('', raw)
        self.assertEqual(clean, '  BackingFile:          /tmp/img')

    def test_ansi_in_property_name_and_value(self):
        """Real udisksctl output: both key and value can be coloured."""
        raw = (
            '  \x1b[37mBackingFile:\x1b[0m          '
            '\x1b[37m/tmp/test_monitor.img\x1b[0m')
        clean = _ANSI_RE.sub('', raw)
        self.assertIn('BackingFile:', clean)
        self.assertIn('/tmp/test_monitor.img', clean)

    def test_malformed_ansi_sequence(self):
        """Incomplete escape without trailing 'm' is not a valid SGR sequence
        and is left unchanged by the regex."""
        raw = '\x1b[31hello\x1b[0m'
        clean = _ANSI_RE.sub('', raw)
        # \x1b[0m is stripped, but \x1b[31 (no 'm') is NOT valid SGR
        self.assertEqual(clean, '\x1b[31hello')

    def test_non_sgr_escape_sequences(self):
        """Other CSI sequences (non-SGR) should not match."""
        # Cursor up: \x1b[A — not matched by [0-9;]*m
        raw = '\x1b[Ahello\x1b[B'
        clean = _ANSI_RE.sub('', raw)
        self.assertEqual(clean, '\x1b[Ahello\x1b[B')

    def test_ansi_in_preamble_line(self):
        raw = ('\x1b[1m\x1b[33m12:03:29.940:\x1b[0m '
               'The udisks-daemon is running (name-owner :1.72).')
        clean = _ANSI_RE.sub('', raw)
        self.assertEqual(
            clean, '12:03:29.940: The udisks-daemon is running '
                    '(name-owner :1.72).')

    def test_ansi_in_job_added(self):
        raw = ('\x1b[1m\x1b[33m12:03:37.002:\x1b[0m '
               '\x1b[1m\x1b[32mAdded '
               '/org/freedesktop/UDisks2/jobs/10842\x1b[0m')
        clean = _ANSI_RE.sub('', raw)
        self.assertIn('Added /org/freedesktop/UDisks2/jobs/10842', clean)

    def test_ansi_in_job_removed(self):
        raw = ('\x1b[1m\x1b[33m12:03:37.002:\x1b[0m '
               '\x1b[1m\x1b[31mRemoved '
               '/org/freedesktop/UDisks2/jobs/10842\x1b[0m')
        clean = _ANSI_RE.sub('', raw)
        self.assertIn('Removed /org/freedesktop/UDisks2/jobs/10842', clean)


class TestAnsiParserInteraction(unittest.TestCase):
    """Tests that the parser correctly handles ANSI-embedded lines."""

    def test_job_added_with_ansi(self):
        p = _MonitorParser()
        # subprocess.PIPE output has no timestamp prefix
        raw = ('\x1b[1m\x1b[32mAdded '
               '/org/freedesktop/UDisks2/jobs/10842\x1b[0m')
        result = p.feed(raw)
        self.assertIsNone(result)  # Job entry doesn't emit
        self.assertTrue(p._in_job)

    def test_job_operation_with_ansi(self):
        p = _MonitorParser()
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        raw = ('    \x1b[37mOperation:\x1b[0m          '
               'filesystem-mount')
        result = p.feed(raw)
        self.assertIsNone(result)
        self.assertEqual(p._job_op, 'filesystem-mount')

    def test_job_objects_with_ansi(self):
        p = _MonitorParser()
        p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        p.feed('    Operation:          filesystem-mount')
        raw = ('    \x1b[37mObjects:\x1b[0m            '
               '/org/freedesktop/UDisks2/block_devices/loop0')
        result = p.feed(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result[1]['objects'],
                         '/org/freedesktop/UDisks2/block_devices/loop0')

    def test_properties_changed_with_ansi(self):
        p = _MonitorParser()
        raw = ('\x1b[1m\x1b[34m/org/freedesktop/UDisks2/block_devices/loop0:'
               '\x1b[0m \x1b[1m\x1b[35morg.freedesktop.UDisks2.Loop:'
               '\x1b[0m \x1b[1m\x1b[33mProperties Changed\x1b[0m')
        result = p.feed(raw)
        self.assertIsNone(result)
        self.assertEqual(p._current_device, 'loop0')

    def test_backing_file_ansi_full(self):
        """Full ANSI line: both property name and value are coloured."""
        p = _MonitorParser()
        p.feed('/org/freedesktop/UDisks2/block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        raw = ('  \x1b[37mBackingFile:\x1b[0m          '
               '\x1b[37m/home/user/my disk image.img\x1b[0m')
        result = p.feed(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result[1]['value'], '/home/user/my disk image.img')

    def test_complete_job_cycle_with_ansi(self):
        """Simulate a full real-world job cycle with ANSI in every line.
        Lines are from subprocess.PIPE output (no timestamp prefix)."""
        p = _MonitorParser()
        lines = [
            '\x1b[1m\x1b[32mAdded '
            '/org/freedesktop/UDisks2/jobs/10842\x1b[0m',
            '  \x1b[1m\x1b[35morg.freedesktop.UDisks2.Job:\x1b[0m',
            '    \x1b[37mBytes:\x1b[0m              0',
            '    \x1b[37mCancelable:\x1b[0m         true',
            '    \x1b[37mObjects:\x1b[0m            '
            '/org/freedesktop/UDisks2/block_devices/loop3',
            '    \x1b[37mOperation:\x1b[0m          filesystem-mount',
            '    \x1b[37mProgress:\x1b[0m           0.0',
            '/org/freedesktop/UDisks2/jobs/10842: '
            'org.freedesktop.UDisks2.Job::Completed (true, \'\')',
            '\x1b[1m\x1b[31mRemoved '
            '/org/freedesktop/UDisks2/jobs/10842\x1b[0m',
        ]
        events = []
        for line in lines:
            result = p.feed(line)
            if result:
                events.append(result)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], 'job')
        self.assertEqual(events[0][1]['op'], 'filesystem-mount')

    def test_interface_added_with_ansi(self):
        p = _MonitorParser()
        raw = ('\x1b[1m\x1b[34m/org/.../block_devices/loop0:\x1b[0m '
               '\x1b[1m\x1b[32mAdded interface '
               'org.freedesktop.UDisks2.Filesystem\x1b[0m')
        result = p.feed(raw)
        self.assertIsNone(result)
        self.assertEqual(p._current_device, 'loop0')

    def test_interface_removed_with_ansi(self):
        p = _MonitorParser()
        raw = ('\x1b[1m\x1b[34m/org/.../block_devices/loop0:\x1b[0m '
               '\x1b[1m\x1b[31mRemoved interface '
               'org.freedesktop.UDisks2.Filesystem\x1b[0m')
        result = p.feed(raw)
        self.assertIsNone(result)
        self.assertEqual(p._current_device, 'loop0')
