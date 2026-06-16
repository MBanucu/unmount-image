"""Tests for _DetachThread._run_detach — the background cleanup state machine."""

import unittest
from unittest.mock import MagicMock, patch


class _FakeEvent:
    """Controllable event-like object — behaves like threading.Event."""

    def __init__(self, value=False):
        self._value = value

    def is_set(self):
        return self._value

    def set(self):
        self._value = True

    def clear(self):
        self._value = False

    def wait(self, timeout=None):
        return self._value


def _make_mock_monitor(device_name='loop0'):
    """Return a MagicMock with _FakeEvent fields and working reset_events."""
    m = MagicMock()
    m.ready = _FakeEvent(False)
    m.backing_cleared = _FakeEvent(False)
    m.mount_detected = _FakeEvent(False)

    def _reset():
        m.backing_cleared.clear()
        m.mount_detected.clear()
    m.reset_events.side_effect = _reset
    return m


def _make_detach_thread(device='/dev/loop0'):
    from unmount_image._monitor import _DetachThread
    return _DetachThread(device)


class TestRunDetach(unittest.TestCase):
    """_DetachThread._run_detach — end-to-end detach state machine."""

    # ── monitor not ready ────────────────────────────────────────

    @patch('unmount_image._monitor._UdisksMonitor')
    @patch('unmount_image._monitor.time.sleep')
    @patch('unmount_image._monitor._unmount_normal')
    @patch('unmount_image._monitor.loop_delete')
    @patch('unmount_image._monitor._fallback_detach')
    def test_monitor_not_ready_gives_up(self, mock_fb, mock_del,
                                         mock_umnt, mock_sleep,
                                         mock_um_cls):
        mock_mon = _make_mock_monitor()
        mock_um_cls.return_value = mock_mon
        dt = _make_detach_thread('/dev/loop0')
        dt._run_detach()
        mock_mon.start.assert_called_once()
        mock_umnt.assert_not_called()
        mock_del.assert_not_called()
        mock_fb.assert_not_called()

    # ── normal success via backing_cleared ───────────────────────

    @patch('unmount_image._monitor._UdisksMonitor')
    @patch('unmount_image._monitor.time.monotonic')
    @patch('unmount_image._monitor.time.sleep')
    @patch('unmount_image._monitor._unmount_normal')
    @patch('unmount_image._monitor.loop_delete')
    @patch('unmount_image._monitor._fallback_detach')
    def test_backing_cleared_detaches_normally(
            self, mock_fb, mock_del, mock_umnt, mock_sleep,
            mock_monotonic, mock_um_cls):
        mock_mon = _make_mock_monitor()
        mock_mon.ready.set()
        mock_um_cls.return_value = mock_mon
        mock_umnt.return_value = (True, '')
        mock_monotonic.side_effect = [0, 1]

        def _sleep(t):
            if t == 0.15:
                mock_mon.backing_cleared.set()
        mock_sleep.side_effect = _sleep

        dt = _make_detach_thread('/dev/loop0')
        dt._run_detach()

        mock_umnt.assert_called_once_with('/dev/loop0', None)
        mock_del.assert_called_once_with('/dev/loop0')
        mock_fb.assert_not_called()
        mock_mon.stop.assert_called_once()
        mock_mon.join.assert_called_once_with(timeout=3)

    # ── auto-mounter re-mount → retry → success ──────────────────

    @patch('unmount_image._monitor._UdisksMonitor')
    @patch('unmount_image._monitor.time.monotonic')
    @patch('unmount_image._monitor.time.sleep')
    @patch('unmount_image._monitor._unmount_normal')
    @patch('unmount_image._monitor.loop_delete')
    @patch('unmount_image._monitor._fallback_detach')
    def test_mount_detected_retries_then_succeeds(
            self, mock_fb, mock_del, mock_umnt, mock_sleep,
            mock_monotonic, mock_um_cls):
        mock_mon = _make_mock_monitor()
        mock_mon.ready.set()
        mock_um_cls.return_value = mock_mon
        mock_umnt.return_value = (True, '')
        mock_monotonic.side_effect = [0, 1, 2, 3]

        sleep_count = [0]

        def _sleep(t):
            sleep_count[0] += 1
            if sleep_count[0] == 1:
                mock_mon.mount_detected.set()
            elif sleep_count[0] == 2:
                mock_mon.backing_cleared.set()
        mock_sleep.side_effect = _sleep

        dt = _make_detach_thread('/dev/loop0')
        dt._run_detach()

        self.assertEqual(mock_umnt.call_count, 2)
        self.assertEqual(mock_del.call_count, 2)
        self.assertEqual(mock_mon.reset_events.call_count, 2)
        mock_fb.assert_not_called()
        mock_mon.stop.assert_called_once()

    # ── deadline expired → fallback ──────────────────────────────

    @patch('unmount_image._monitor._UdisksMonitor')
    @patch('unmount_image._monitor.time.monotonic')
    @patch('unmount_image._monitor.time.sleep')
    @patch('unmount_image._monitor._unmount_normal')
    @patch('unmount_image._monitor.loop_delete')
    @patch('unmount_image._monitor._fallback_detach')
    def test_deadline_expired_falls_back(
            self, mock_fb, mock_del, mock_umnt, mock_sleep,
            mock_monotonic, mock_um_cls):
        mock_mon = _make_mock_monitor()
        mock_mon.ready.set()
        mock_um_cls.return_value = mock_mon
        mock_umnt.return_value = (True, '')
        mock_monotonic.side_effect = [0, 100]

        dt = _make_detach_thread('/dev/loop0')
        dt._run_detach()

        mock_umnt.assert_called_once_with('/dev/loop0', None)
        mock_del.assert_called_once_with('/dev/loop0')
        mock_fb.assert_called_once_with('loop0', '/dev/loop0')
        mock_mon.stop.assert_called_once()

    # ── re-mount during grace period (sleep 0.3) → retry ────────

    @patch('unmount_image._monitor._UdisksMonitor')
    @patch('unmount_image._monitor.time.monotonic')
    @patch('unmount_image._monitor.time.sleep')
    @patch('unmount_image._monitor._unmount_normal')
    @patch('unmount_image._monitor.loop_delete')
    @patch('unmount_image._monitor._fallback_detach')
    def test_remount_during_grace_period_retries(
            self, mock_fb, mock_del, mock_umnt, mock_sleep,
            mock_monotonic, mock_um_cls):
        mock_mon = _make_mock_monitor()
        mock_mon.ready.set()
        mock_um_cls.return_value = mock_mon
        mock_umnt.return_value = (True, '')
        mock_monotonic.side_effect = [0, 1, 2, 3]

        call_count = [0]

        def _sleep(t):
            call_count[0] += 1
            if call_count[0] == 1:
                mock_mon.backing_cleared.set()
            elif call_count[0] == 2:
                mock_mon.mount_detected.set()
            elif call_count[0] == 3:
                mock_mon.backing_cleared.set()
        mock_sleep.side_effect = _sleep

        dt = _make_detach_thread('/dev/loop0')
        dt._run_detach()

        self.assertEqual(mock_umnt.call_count, 2)
        self.assertEqual(mock_del.call_count, 2)
        mock_fb.assert_not_called()
        mock_mon.stop.assert_called_once()

    # ── run() adds/removes from _pending_detaches ────────────────

    @patch('unmount_image._monitor._DetachThread._run_detach')
    def test_run_tracks_pending_detaches(self, mock_run_detach):
        from unmount_image._monitor import _pending_detaches
        dt = _make_detach_thread('/dev/loop0')
        self.assertNotIn(dt, _pending_detaches)
        dt.run()
        self.assertNotIn(dt, _pending_detaches)
        mock_run_detach.assert_called_once()

    # ── finally block always cleans up monitor ───────────────────

    @patch('unmount_image._monitor._UdisksMonitor')
    @patch('unmount_image._monitor.time.sleep')
    @patch('unmount_image._monitor._unmount_normal')
    @patch('unmount_image._monitor.loop_delete')
    @patch('unmount_image._monitor._fallback_detach')
    def test_finally_cleans_up_monitor_on_exception(
            self, mock_fb, mock_del, mock_umnt, mock_sleep,
            mock_um_cls):
        mock_mon = _make_mock_monitor()
        mock_mon.ready.set()
        mock_um_cls.return_value = mock_mon
        mock_umnt.side_effect = RuntimeError('boom')

        dt = _make_detach_thread('/dev/loop0')
        with self.assertRaises(RuntimeError):
            dt._run_detach()

        mock_mon.stop.assert_called_once()
        mock_mon.join.assert_called_once_with(timeout=3)
        mock_fb.assert_not_called()
