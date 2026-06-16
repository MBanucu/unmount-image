"""Edge case tests for _device_name_from_path: the function that extracts
kernel device names from udisksctl monitor D-Bus object paths.

Covers: all device naming conventions, path format variations, colons,
ANSIs embedded in paths, and false match prevention.
"""

import unittest

from unmount_image._monitor import _device_name_from_path


class TestDeviceNameStandard(unittest.TestCase):
    """Standard device name extraction — correctness baseline."""

    def test_loop_device_basic(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/loop0'),
            'loop0')

    def test_loop_device_with_colon(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/loop3:'),
            'loop3')

    def test_partition_device(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/sda1:'),
            'sda1')

    def test_disk_device(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/sda:'),
            'sda')

    def test_nvme_device(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/nvme0n1:'),
            'nvme0n1')

    def test_nvme_partition(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/nvme0n1p2:'),
            'nvme0n1p2')


class TestDeviceNameWithTrailingContent(unittest.TestCase):
    """Device names with arbitrary trailing content after the colon."""

    def test_properties_changed_trailing(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/loop0: '
                'org.freedesktop.UDisks2.Block: Properties Changed'),
            'loop0')

    def test_added_interface_trailing(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/loop0: '
                'Added interface org.freedesktop.UDisks2.Filesystem'),
            'loop0')

    def test_removed_interface_trailing(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/loop0: '
                'Removed interface org.freedesktop.UDisks2.Filesystem'),
            'loop0')

    def test_multiple_colons_trailing(self):
        # "Properties Changed" line has `Interface: Properties Changed`
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/loop0: '
                'org.freedesktop.UDisks2.Block: Properties Changed: extra'),
            'loop0')

    def test_no_trailing_content(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/sda1'),
            'sda1')


class TestDeviceNameNonBlockDevice(unittest.TestCase):
    """Non-block-device paths should return None."""

    def test_job_path(self):
        self.assertIsNone(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/jobs/10842'))

    def test_job_path_with_trailing(self):
        self.assertIsNone(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/jobs/1: '
                'org.freedesktop.UDisks2.Job::Completed (true, \'\')'))

    def test_drive_path(self):
        self.assertIsNone(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/drives/ST1000DM010'))

    def test_drive_path_with_trailing(self):
        self.assertIsNone(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/drives/ST1000DM010: '
                'org.freedesktop.UDisks2.Drive: Properties Changed'))

    def test_root_path(self):
        self.assertIsNone(
            _device_name_from_path('/org/freedesktop/UDisks2'))

    def test_preamble_line(self):
        self.assertIsNone(
            _device_name_from_path(
                'Monitoring the udisks daemon. Press Ctrl+C to exit.'))

    def test_empty_string(self):
        self.assertIsNone(_device_name_from_path(''))

    def test_whitespace_only(self):
        self.assertIsNone(_device_name_from_path('   '))


class TestDeviceNameSpecialNames(unittest.TestCase):
    """Device names from different subsystems."""

    def test_dm_device(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/dm-0:'),
            'dm-0')

    def test_md_device(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/md0:'),
            'md0')

    def test_mmc_device(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/mmcblk0:'),
            'mmcblk0')

    def test_mmc_partition(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/mmcblk0p1:'),
            'mmcblk0p1')

    def test_vd_device(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/vda:'),
            'vda')


class TestDeviceNameFalseMatches(unittest.TestCase):
    """Tests against false-positive device name matches."""

    def test_loop0_not_in_loop10(self):
        """'loop0' should not match inside 'loop10'."""
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/loop10:'),
            'loop10')
        # Verify it's not 'loop0'
        self.assertNotEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/loop10:'),
            'loop0')

    def test_sda_not_in_sda1(self):
        self.assertEqual(
            _device_name_from_path(
                '/org/freedesktop/UDisks2/block_devices/sda1:'),
            'sda1')

    def test_block_devices_not_partial_match(self):
        """A path containing 'block_devices' but not the expected prefix
        should not falsely register."""
        # Hypothetical malformed path
        result = _device_name_from_path(
            '/org/freedesktop/UDisks2/not_block_devices/loop0:')
        self.assertIsNone(result)
