"""Edge case tests for property value parsing from udisksctl monitor output.

Covers: empty values, whitespace-only values, multi-line property values,
Unicode in paths, special characters in values, and property name collisions.
"""

import unittest

from unmount_image._monitor import _BACKING_RE, _OBJ_RE, _OP_RE, _MonitorParser


class TestBackingFileRegex(unittest.TestCase):
    """_BACKING_RE edge cases."""

    def test_normal_path(self):
        m = _BACKING_RE.search('  BackingFile:          /tmp/img')
        self.assertEqual(m.group(1).strip(), '/tmp/img')

    def test_empty_value_no_spaces(self):
        # _BACKING_RE requires \s+ after colon; real output always has spaces
        m = _BACKING_RE.search('  BackingFile:')
        self.assertIsNone(m)

    def test_empty_value_with_spaces(self):
        m = _BACKING_RE.search('  BackingFile:          ')
        self.assertEqual(m.group(1).strip(), '')

    def test_empty_value_with_only_whitespace(self):
        m = _BACKING_RE.search('  BackingFile:          \t  ')
        self.assertEqual(m.group(1).strip(), '')

    def test_path_with_spaces(self):
        m = _BACKING_RE.search(
            '  BackingFile:          /home/user/my disk image.img')
        self.assertEqual(
            m.group(1).strip(), '/home/user/my disk image.img')

    def test_path_with_special_chars(self):
        m = _BACKING_RE.search(
            '  BackingFile:          /tmp/img!@#$%^&*()_+.img')
        self.assertEqual(
            m.group(1).strip(), '/tmp/img!@#$%^&*()_+.img')

    def test_path_with_unicode(self):
        m = _BACKING_RE.search(
            '  BackingFile:          /tmp/\u00fcber-\u00df\u00e4ge.img')
        self.assertEqual(
            m.group(1).strip(), '/tmp/\u00fcber-\u00df\u00e4ge.img')

    def test_path_with_trailing_spaces(self):
        m = _BACKING_RE.search(
            '  BackingFile:          /tmp/img   ')
        self.assertEqual(m.group(1).strip(), '/tmp/img')

    def test_path_with_leading_spaces_in_value(self):
        # Leading spaces in the value are preserved by regex, then stripped
        m = _BACKING_RE.search('  BackingFile:             /tmp/img')
        self.assertEqual(m.group(1).strip(), '/tmp/img')

    def test_backing_re_no_match_on_other_property(self):
        m = _BACKING_RE.search('  SetupByUID:           1000')
        self.assertIsNone(m)

    def test_backing_re_no_match_on_autoclear(self):
        m = _BACKING_RE.search('  Autoclear:            true')
        self.assertIsNone(m)

    def test_backing_re_no_match_partial_name(self):
        """Property names containing 'BackingFile' as substring."""
        m = _BACKING_RE.search('  BackingFilePath:      /tmp/img')
        self.assertIsNone(m)


class TestOperationRegex(unittest.TestCase):
    """_OP_RE edge cases."""

    def test_all_known_operations(self):
        ops = [
            'filesystem-mount', 'filesystem-unmount', 'filesystem-check',
            'loop-setup', 'loop-delete', 'cleanup', 'power-off',
            'ata-smart-selftest', 'ata-smart-simulate',
            'luks-close', 'luks-open',
        ]
        for op in ops:
            with self.subTest(op=op):
                m = _OP_RE.search(f'    Operation:          {op}')
                self.assertEqual(m.group(1), op)

    def test_no_match_on_non_operation_line(self):
        m = _OP_RE.search('    Objects:            /org/.../loop0')
        self.assertIsNone(m)

    def test_no_match_on_bytes_line(self):
        m = _OP_RE.search('    Bytes:              0')
        self.assertIsNone(m)


class TestObjectsRegex(unittest.TestCase):
    """_OBJ_RE edge cases."""

    def test_single_object(self):
        m = _OBJ_RE.search(
            '    Objects:            '
            '/org/freedesktop/UDisks2/block_devices/loop0')
        self.assertEqual(
            m.group(1), '/org/freedesktop/UDisks2/block_devices/loop0')

    def test_empty_objects(self):
        # _OBJ_RE requires \s+ then \S+; "Objects:" alone doesn't match
        m = _OBJ_RE.search('    Objects:')
        self.assertIsNone(m)

    def test_empty_objects_with_spaces(self):
        # _OBJ_RE requires \S+ after whitespace; spaces-only doesn't match
        m = _OBJ_RE.search('    Objects:            ')
        self.assertIsNone(m)

    def test_multiple_objects(self):
        """Objects can contain multiple paths separated by spaces.
        _OBJ_RE uses \\S+ which stops at the first space."""
        m = _OBJ_RE.search(
            '    Objects:            '
            '/org/.../loop0 /org/.../loop1')
        self.assertEqual(m.group(1), '/org/.../loop0')


class TestPropertyValueInParser(unittest.TestCase):
    """How the parser handles unusual property values."""

    def test_backing_file_empty_string(self):
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        # _BACKING_RE needs \s+ after colon; real output has spaces
        r = p.feed('  BackingFile:          ')
        self.assertEqual(r[1]['value'], '')

    def test_backing_file_only_whitespace(self):
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        r = p.feed('  BackingFile:          ')
        self.assertEqual(r[1]['value'], '')

    def test_backing_file_with_unicode(self):
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        r = p.feed('  BackingFile:          /tmp/caf\u00e9.img')
        self.assertEqual(r[1]['value'], '/tmp/caf\u00e9.img')

    def test_backing_file_empty_to_nonempty(self):
        """Simulate BackingFile transitioning empty -> path (loop setup)."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')

        # First, BackingFile empty (pre-setup residual)
        r1 = p.feed('  BackingFile:          ')
        self.assertEqual(r1[1]['value'], '')

        # Then, BackingFile gets set (new loop setup)
        r2 = p.feed('  BackingFile:          /tmp/new.img')
        self.assertEqual(r2[1]['value'], '/tmp/new.img')

    def test_backing_file_nonempty_to_empty(self):
        """Simulate BackingFile transitioning path -> empty (detach)."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')

        # First, BackingFile is set
        r1 = p.feed('  BackingFile:          /tmp/img')
        self.assertEqual(r1[1]['value'], '/tmp/img')

        # Then, BackingFile cleared (detach) — real output has spaces
        r2 = p.feed('  BackingFile:          ')
        self.assertEqual(r2[1]['value'], '')

    def test_property_order_in_properties_changed(self):
        """Multiple property changes in one event; only BackingFile is
        captured."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Loop: Properties Changed')
        r1 = p.feed('  SetupByUID:           1000')
        self.assertIsNone(r1)
        r2 = p.feed('  BackingFile:          /tmp/img')
        self.assertEqual(r2[1]['value'], '/tmp/img')
        r3 = p.feed('  Autoclear:            true')
        self.assertIsNone(r3)

    def test_symlinks_multiline(self):
        """Symlinks spans multiple lines; parser should not crash."""
        p = _MonitorParser()
        p.feed('/org/.../block_devices/loop0: '
               'org.freedesktop.UDisks2.Block: Properties Changed')
        self.assertIsNone(
            p.feed('  Symlinks:             /dev/disk/by-diskseq/10'))
        self.assertIsNone(
            p.feed('                        /dev/disk/by-uuid/ABCD'))
        self.assertIsNone(
            p.feed('                        /dev/disk/by-loop-inode/1:2'))
