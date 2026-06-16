"""Tests for _fallback_detach logic."""

import unittest
from unittest.mock import patch


class TestFallbackDetach(unittest.TestCase):
    """_fallback_detach — aggressive unmount-delete-poll retry loop."""

    @patch('unmount_image._monitor.time.sleep')
    @patch('unmount_image._monitor._unmount_normal')
    @patch('unmount_image._monitor.loop_delete')
    @patch('unmount_image._monitor.os.path.exists')
    def test_detaches_when_device_disappears(self, mock_exists, mock_delete,
                                              mock_unmount, mock_sleep):
        from unmount_image._monitor import _fallback_detach
        mock_unmount.return_value = (True, '')
        mock_exists.side_effect = [True, True, False]
        _fallback_detach('loop0', '/dev/loop0')
        self.assertGreaterEqual(mock_unmount.call_count, 1)
        self.assertGreaterEqual(mock_delete.call_count, 1)

    @patch('unmount_image._monitor.time.sleep')
    @patch('unmount_image._monitor._unmount_normal')
    @patch('unmount_image._monitor.loop_delete')
    @patch('unmount_image._monitor.os.path.exists')
    def test_retries_until_device_gone(self, mock_exists, mock_delete,
                                        mock_unmount, mock_sleep):
        from unmount_image._monitor import _fallback_detach
        mock_unmount.return_value = (True, '')
        mock_exists.side_effect = [True, True, False]
        _fallback_detach('loop0', '/dev/loop0')
        self.assertEqual(mock_delete.call_count, 3)
        self.assertEqual(mock_unmount.call_count, 3)

    @patch('unmount_image._monitor.time.sleep')
    @patch('unmount_image._monitor._unmount_normal')
    @patch('unmount_image._monitor.loop_delete')
    @patch('unmount_image._monitor.os.path.exists')
    def test_exhausted_after_30_iterations(self, mock_exists, mock_delete,
                                            mock_unmount, mock_sleep):
        from unmount_image._monitor import _fallback_detach
        mock_unmount.return_value = (True, '')
        mock_exists.return_value = True
        _fallback_detach('loop0', '/dev/loop0')
        self.assertEqual(mock_unmount.call_count, 30)
        self.assertEqual(mock_delete.call_count, 30)

    @patch('unmount_image._monitor.time.sleep')
    @patch('unmount_image._monitor._unmount_normal')
    @patch('unmount_image._monitor.loop_delete')
    @patch('unmount_image._monitor.os.path.exists')
    def test_immediate_detach_when_already_gone(self, mock_exists,
                                                 mock_delete, mock_unmount,
                                                 mock_sleep):
        from unmount_image._monitor import _fallback_detach
        mock_unmount.return_value = (True, '')
        mock_exists.return_value = False
        _fallback_detach('loop0', '/dev/loop0')
        mock_unmount.assert_called_once()
        mock_delete.assert_called_once()
