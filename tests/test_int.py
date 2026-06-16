"""Integration tests — unmount real images via udisksctl."""

import gzip
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

_FAT_IMG_SIZE_MB = 1
_EXT4_IMG_SIZE_MB = 1

_FIXTURE_DIR = Path(__file__).parent

_DEV_RE = re.compile(r'as\s+(/[^\s]+?)\.?\s*$', re.MULTILINE)
_MOUNT_RE = re.compile(r'at\s+(/[^\s]+?)\.?\s*$', re.MULTILINE)


def _mkfs_available(tool):
    return subprocess.run(
        ['which', tool],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _create_fat_image(path):
    subprocess.run(
        ['truncate', '-s', f'{_FAT_IMG_SIZE_MB}M', path], check=True)
    subprocess.run(
        ['mkfs.fat', path], check=True, capture_output=True)


def _create_ext4_image(path):
    subprocess.run(
        ['truncate', '-s', f'{_EXT4_IMG_SIZE_MB}M', path], check=True)
    subprocess.run(
        ['mkfs.ext4', '-E', 'root_perms=0777', path],
        check=True, capture_output=True)


def _decompress_image(gz_path, dest_path, full_size_mb):
    CHUNK = 1024 * 1024
    zero = b'\x00' * CHUNK
    full_size = full_size_mb * 1024 * 1024

    fd = os.open(dest_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
    os.ftruncate(fd, full_size)
    os.close(fd)

    offset = 0
    with gzip.open(gz_path, 'rb') as src, open(dest_path, 'rb+') as dst:
        while True:
            chunk = src.read(CHUNK)
            if not chunk:
                break
            if chunk != zero[:len(chunk)]:
                os.lseek(dst.fileno(), offset, os.SEEK_SET)
                dst.write(chunk)
            offset += len(chunk)


def _loop_setup(image_path):
    r = subprocess.run(
        ['udisksctl', 'loop-setup', '-f', image_path,
         '--no-user-interaction'],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"loop-setup failed: {r.stderr.strip()}")
    m = _DEV_RE.search(r.stdout)
    if not m:
        raise RuntimeError(f"could not parse device: {r.stdout.strip()}")
    return m.group(1)


def _mount_device(loop_dev, fstype=None):
    cmd = ['udisksctl', 'mount', '-b', loop_dev, '--no-user-interaction']
    if fstype:
        cmd.extend(['-t', fstype])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"mount failed: {r.stderr.strip()}")
    m = _MOUNT_RE.search(r.stdout)
    if not m:
        raise RuntimeError(f"could not parse mount point: {r.stdout.strip()}")
    return m.group(1)


class TestUnmountIntegration(unittest.TestCase):
    _img: str

    @classmethod
    def setUpClass(cls):
        if _mkfs_available('mkfs.fat'):
            fd, path = tempfile.mkstemp(
                suffix='.img', prefix='unmount_image_test_')
            os.close(fd)
            _create_fat_image(path)
            cls._img = path
        elif (_FIXTURE_DIR / 'fat.img.gz').exists():
            fd, path = tempfile.mkstemp(
                suffix='.img', prefix='unmount_image_test_')
            os.close(fd)
            _decompress_image(
                _FIXTURE_DIR / 'fat.img.gz', path, _FAT_IMG_SIZE_MB)
            cls._img = path
        else:
            raise unittest.SkipTest(
                'mkfs.fat not available and fat.img.gz fixture not found')

    @classmethod
    def tearDownClass(cls):
        from unmount_image._monitor import join_pending_detaches
        join_pending_detaches(timeout=60)
        try:
            os.unlink(cls._img)
        except OSError:
            pass

    def test_umount_image(self):
        from unmount_image import umount_image
        try:
            dev = _loop_setup(self._img)
            mp = _mount_device(dev, fstype='vfat')
        except RuntimeError as e:
            raise unittest.SkipTest(f'udisksctl not functional: {e}')
        self.assertTrue(os.path.exists(dev))
        umount_image(dev, mp)

    def test_umount_with_custom_strategy(self):
        from unmount_image import umount_image, UNMOUNT_FORCE
        try:
            dev = _loop_setup(self._img)
            mp = _mount_device(dev, fstype='vfat')
        except RuntimeError as e:
            raise unittest.SkipTest(f'udisksctl not functional: {e}')
        self.assertTrue(os.path.exists(dev))
        umount_image(dev, mp, strategy=UNMOUNT_FORCE)

    def test_detach_only(self):
        from unmount_image import detach_image
        try:
            dev = _loop_setup(self._img)
        except RuntimeError as e:
            raise unittest.SkipTest(f'udisksctl not functional: {e}')
        self.assertTrue(os.path.exists(dev))
        detach_image(dev)

    def test_umount_write_and_umount(self):
        from unmount_image import umount_image
        try:
            dev = _loop_setup(self._img)
            mp = _mount_device(dev, fstype='vfat')
        except RuntimeError as e:
            raise unittest.SkipTest(f'udisksctl not functional: {e}')

        try:
            test_file = os.path.join(mp, 'test_write.txt')
            content = 'hello from unmount-image'
            with open(test_file, 'w') as f:
                f.write(content)
            with open(test_file) as f:
                self.assertEqual(f.read(), content)
            os.unlink(test_file)
        finally:
            umount_image(dev, mp)
