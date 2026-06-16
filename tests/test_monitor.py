"""Tests for _UdisksMonitor signaling and _fallback_detach logic."""

import unittest
from unittest.mock import patch


class TestUdisksMonitorSignaling(unittest.TestCase):
    """_UdisksMonitor._handle_event — parser events → Event flags."""

    @staticmethod
    def _make_monitor(device_name='loop0'):
        from unmount_image._monitor import _UdisksMonitor
        return _UdisksMonitor(device_name)

    def test_filesystem_mount_sets_mount_detected(self):
        m = self._make_monitor()
        m._handle_event(
            ('job', {'op': 'filesystem-mount',
                     'objects': '/org/.../block_devices/loop0'}))
        self.assertTrue(m.mount_detected.is_set())
        self.assertFalse(m.backing_cleared.is_set())

    def test_unmount_or_other_job_ignored(self):
        m = self._make_monitor()
        for op in ('filesystem-unmount', 'loop-setup', 'filesystem-check'):
            with self.subTest(op=op):
                m._handle_event(
                    ('job', {'op': op,
                             'objects': '/org/.../block_devices/loop0'}))
        self.assertFalse(m.mount_detected.is_set())

    def test_mount_on_different_device_ignored(self):
        m = self._make_monitor('loop0')
        m._handle_event(
            ('job', {'op': 'filesystem-mount',
                     'objects': '/org/.../block_devices/loop1'}))
        self.assertFalse(m.mount_detected.is_set())

    def test_backing_file_set_does_not_trigger(self):
        m = self._make_monitor()
        m._handle_event(
            ('loop_prop', {'device': 'loop0', 'prop': 'BackingFile',
                           'value': '/tmp/img'}))
        self.assertFalse(m.backing_cleared.is_set())

    def test_backing_file_emptied_sets_cleared(self):
        m = self._make_monitor()
        m._handle_event(
            ('loop_prop', {'device': 'loop0', 'prop': 'BackingFile',
                           'value': ''}))
        self.assertTrue(m.backing_cleared.is_set())

    def test_backing_cleared_on_different_device_ignored(self):
        m = self._make_monitor('loop0')
        m._handle_event(
            ('loop_prop', {'device': 'loop1', 'prop': 'BackingFile',
                           'value': ''}))
        self.assertFalse(m.backing_cleared.is_set())

    def test_reset_events_clears_both(self):
        m = self._make_monitor()
        m.mount_detected.set()
        m.backing_cleared.set()
        m.reset_events()
        self.assertFalse(m.mount_detected.is_set())
        self.assertFalse(m.backing_cleared.is_set())

    def test_both_events_set_scenario(self):
        m = self._make_monitor()
        m._handle_event(
            ('job', {'op': 'filesystem-mount',
                     'objects': '/org/.../block_devices/loop0'}))
        m._handle_event(
            ('loop_prop', {'device': 'loop0', 'prop': 'BackingFile',
                           'value': ''}))
        self.assertTrue(m.mount_detected.is_set())
        self.assertTrue(m.backing_cleared.is_set())


class TestFallbackDetach(unittest.TestCase):
    """_fallback_detach — aggressive unmount→delete→poll retry loop."""

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
        # Iteration: unmount→delete→exists checks; 3rd exists=False
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
