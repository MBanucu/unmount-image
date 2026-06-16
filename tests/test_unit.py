"""Unit tests for unmount_image — mocked subprocess calls."""

import unittest
from unittest.mock import patch, MagicMock


class TestUdisksUnmount(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from unmount_image._monitor import join_pending_detaches
        join_pending_detaches(timeout=60)

    # ── umount_image tests ─────────────────────────────────────

    @patch('unmount_image._monitor._DetachThread')
    @patch('subprocess.run')
    def test_umount_image(self, mock_run, mock_thread):
        mock_run.return_value = MagicMock(returncode=0, stderr='')
        from unmount_image import umount_image
        umount_image('/dev/loop0')
        self.assertEqual(mock_run.call_count, 1)
        mock_run.assert_any_call(
            ['udisksctl', 'unmount', '-b', '/dev/loop0',
             '--no-user-interaction'], capture_output=True, text=True)
        mock_thread.assert_called_once_with('/dev/loop0')
        mock_thread.return_value.start.assert_called_once()

    @patch('unmount_image._monitor._DetachThread')
    @patch('subprocess.run')
    def test_umount_image_force_fallback(self, mock_run, mock_thread):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr='error'),
            MagicMock(returncode=0, stderr=''),
        ]
        from unmount_image import umount_image, UNMOUNT_FORCE
        umount_image('/dev/loop0', strategy=UNMOUNT_FORCE)
        mock_run.assert_any_call(
            ['udisksctl', 'unmount', '-b', '/dev/loop0',
             '--force', '--no-user-interaction'],
            capture_output=True, text=True)
        mock_thread.assert_called_once_with('/dev/loop0')

    @patch('unmount_image._monitor._DetachThread')
    @patch('subprocess.run')
    def test_umount_image_lazy_fallback(self, mock_run, mock_thread):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr='error'),
            MagicMock(returncode=0),
        ]
        from unmount_image import umount_image, UNMOUNT_LAZY
        umount_image('/dev/loop0', mount_point='/mnt/img',
                     strategy=UNMOUNT_LAZY)
        mock_run.assert_any_call(
            ['umount', '-l', '/mnt/img'], capture_output=True)
        mock_thread.assert_called_once_with('/dev/loop0')

    @patch('subprocess.run')
    def test_umount_image_no_mount_point_exhausted(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr='error'),
            MagicMock(returncode=1, stderr='error'),
        ]
        from unmount_image import umount_image, UNMOUNT_FORCE
        with self.assertRaises(RuntimeError) as ctx:
            umount_image('/dev/loop0', strategy=UNMOUNT_FORCE)
        self.assertIn('unmount failed', str(ctx.exception))

    @patch('subprocess.run')
    def test_umount_image_strategy_fail_fast(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stderr='error')
        from unmount_image import umount_image, UNMOUNT_FAIL_FAST
        with self.assertRaises(RuntimeError) as ctx:
            umount_image('/dev/loop0', strategy=UNMOUNT_FAIL_FAST)
        self.assertIn('unmount failed', str(ctx.exception))
        self.assertEqual(mock_run.call_count, 1)

    @patch('unmount_image._monitor._DetachThread')
    @patch('subprocess.run')
    def test_umount_image_custom_strategy(self, mock_run, mock_thread):
        mock_run.side_effect = [
            MagicMock(returncode=0, stderr=''),
            MagicMock(returncode=0),
        ]
        from unmount_image import umount_image, compose, retry,\
            _unmount_normal
        strategy = compose(retry(_unmount_normal, attempts=2, delay=0))
        umount_image('/dev/loop0', strategy=strategy)
        self.assertEqual(mock_run.call_count, 1)

    @patch('unmount_image._monitor._DetachThread')
    @patch('subprocess.run')
    def test_umount_image_retry_success_after_fail(self, mock_run,
                                                    mock_thread):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr='error'),
            MagicMock(returncode=0, stderr=''),
        ]
        from unmount_image import umount_image, compose, retry,\
            _unmount_normal
        strategy = compose(retry(_unmount_normal, attempts=2, delay=0))
        umount_image('/dev/loop0', strategy=strategy)
        self.assertEqual(mock_run.call_count, 2)

    @patch('subprocess.run')
    def test_umount_image_retry_exhausted(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stderr='error')
        from unmount_image import umount_image, compose, retry,\
            _unmount_normal
        strategy = compose(retry(_unmount_normal, attempts=2, delay=0))
        with self.assertRaises(RuntimeError) as ctx:
            umount_image('/dev/loop0', strategy=strategy)
        self.assertIn('unmount failed', str(ctx.exception))

    @patch('unmount_image._monitor._DetachThread')
    @patch('subprocess.run')
    def test_umount_image_strategy_force(self, mock_run, mock_thread):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr='error'),
            MagicMock(returncode=0, stderr=''),
        ]
        from unmount_image import umount_image, UNMOUNT_FORCE
        umount_image('/dev/loop0', strategy=UNMOUNT_FORCE)

    @patch('unmount_image._monitor._DetachThread')
    @patch('subprocess.run')
    def test_umount_image_default_retries_then_lazy(self, mock_run,
                                                     mock_thread):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr='error'),
            MagicMock(returncode=1, stderr='error'),
            MagicMock(returncode=1, stderr='error'),
            MagicMock(returncode=0),
        ]
        from unmount_image import umount_image
        umount_image('/dev/loop0', mount_point='/mnt/img')
        mock_run.assert_any_call(
            ['umount', '-l', '/mnt/img'], capture_output=True)

    @patch('subprocess.run')
    def test_umount_image_default_retries_exhausted_no_mount_point(self,
                                                                    mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stderr='error')
        from unmount_image import umount_image
        with self.assertRaises(RuntimeError) as ctx:
            umount_image('/dev/loop0')
        self.assertIn('unmount failed', str(ctx.exception))

    # ── detach_image tests ─────────────────────────────────────

    @patch('unmount_image._monitor._DetachThread')
    def test_detach_image(self, mock_thread):
        from unmount_image import detach_image
        detach_image('/dev/loop0')
        mock_thread.assert_called_once_with('/dev/loop0')
        mock_thread.return_value.start.assert_called_once()

    @patch('unmount_image._monitor._DetachThread')
    def test_detach_inner(self, mock_thread):
        from unmount_image import detach_inner
        detach_inner('/dev/loop0')
        mock_thread.assert_called_once_with('/dev/loop0')
        mock_thread.return_value.start.assert_called_once()

    # ── umount_inner tests ─────────────────────────────────────

    @patch('subprocess.run')
    def test_umount_inner_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr='')
        from unmount_image import umount_inner
        umount_inner('/dev/loop0')
        mock_run.assert_called_once_with(
            ['udisksctl', 'unmount', '-b', '/dev/loop0',
             '--no-user-interaction'], capture_output=True, text=True)

    @patch('subprocess.run')
    def test_umount_inner_fails(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stderr='unmount error')
        from unmount_image import umount_inner
        with self.assertRaises(RuntimeError) as ctx:
            umount_inner('/dev/loop0')
        self.assertIn('unmount failed', str(ctx.exception))
