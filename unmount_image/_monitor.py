"""udisksctl monitor integration — monitor thread, detach thread."""
from __future__ import annotations

import os
import threading
import time

from udisks_monitor import DevicePropertyChanged, UdisksMonitor

from unmount_image._helpers import loop_delete
from unmount_image._strategy import _unmount_normal

_pending_detaches: set[_DetachThread] = set()


class _DetachThread(threading.Thread):
    """Daemon thread: runs the detach state machine.

    Issues ``loop-delete``, then waits for ``udisksctl monitor``
    feedback.  If the auto-mounter re-mounts, unmounts and retries.
    Exits once the device is confirmed fully detached.

    Each instance is tracked in ``_pending_detaches`` so callers can
    optionally wait for completion via :func:`join_pending_detaches`.
    """

    def __init__(self, device: str):
        super().__init__(daemon=True)
        self._device = device
        self._name = device.split('/')[-1]

    def run(self):
        _pending_detaches.add(self)
        try:
            self._run_detach()
        finally:
            _pending_detaches.discard(self)

    def _run_detach(self):
        mon = UdisksMonitor()
        backing_cleared = threading.Event()
        mount_detected = threading.Event()

        @mon.on(DevicePropertyChanged, device=self._name,
                property_='BackingFile')
        def _on_backing(evt):
            if not evt.value:
                backing_cleared.set()

        @mon.on(event_type='filesystem-mount')
        def _on_mount(evt):
            if self._name in evt.objects:
                mount_detected.set()

        mon.start()
        if not mon.ready.wait(timeout=10):
            print(f"device {self._device}: monitor failed to start, "
                  f"giving up")
            return
        try:
            while True:
                backing_cleared.clear()
                mount_detected.clear()
                _unmount_normal(self._device, None)
                time.sleep(0.15)
                loop_delete(self._device)
                print(f"device {self._device}: loop-delete issued, "
                      f"waiting for monitor...")

                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline:
                    if mount_detected.is_set():
                        print(f"device {self._device}: auto-mounter "
                              f"re-mounted, retrying...")
                        break

                    if backing_cleared.is_set():
                        time.sleep(0.3)
                        if mount_detected.is_set():
                            break
                        print(f"device {self._device} detached")
                        return
                    time.sleep(0.1)
                else:
                    _fallback_detach(self._name, self._device)
                    return
        finally:
            mon.stop()
            mon.join(timeout=3)


def _fallback_detach(name: str, device: str):
    """Fallback: aggressive unmount-delete-poll retry loop.

    Used when the udisksctl monitor does not confirm detachment
    before the timeout.
    """
    sys_path = f'/sys/block/{name}/loop/backing_file'
    for _ in range(30):
        _unmount_normal(device, None)
        time.sleep(0.1)
        loop_delete(device)
        time.sleep(0.1)
        if not os.path.exists(sys_path):
            print(f"device {device} detached (fallback)")
            return
        time.sleep(0.3)
    print(f"device {device}: fallback detach exhausted, giving up")


def detach_loop(device: str):
    """Detach *device* in a background thread (non-blocking).

    Spawns a daemon thread that issues ``loop-delete`` and watches
    ``udisksctl monitor`` for the device to confirm full detachment.
    If the desktop auto-mounter (gvfs) re-attaches and re-mounts the
    device between delete attempts, the thread unmounts and retries.

    Call :func:`join_pending_detaches` to block until all outstanding
    detach threads have completed.
    """
    print("")
    _DetachThread(device).start()


def join_pending_detaches(timeout: float | None = None):
    """Block until all outstanding detach threads have completed."""
    for t in list(_pending_detaches):
        t.join(timeout=timeout)
        if t.is_alive():
            print(f"warning: detach thread for {t._device} "
                  f"still alive after {timeout}s")
