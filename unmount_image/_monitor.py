"""udisksctl monitor integration — parser, monitor thread, detach thread."""

import os
import re
import subprocess
import threading
import time

from unmount_image._helpers import loop_delete
from unmount_image._strategy import _unmount_normal

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
_BACKING_RE = re.compile(r'BackingFile:\s+(.*)')
_OP_RE = re.compile(r'Operation:\s+(\S+)')
_OBJ_RE = re.compile(r'Objects:\s+(\S+)')


def _device_name_from_path(line: str) -> str | None:
    """Extract ``'loop0'`` from ``/org/.../block_devices/loop0:``."""
    idx = line.find('/block_devices/')
    if idx == -1:
        return None
    rest = line[idx + len('/block_devices/'):]
    colon = rest.find(':')
    if colon != -1:
        rest = rest[:colon]
    return rest.strip()


class _MonitorParser:
    """Stateful line parser for ``udisksctl monitor`` output.

    Feeds one stripped line at a time.  Tracks job context (creation,
    removal, operation, target objects) so that each ``(operation,
    objects)`` pair is emitted exactly once per job, and remembers the
    last-seen block device so that indented property lines are
    attributed correctly.
    """
    __slots__ = ('_in_job', '_job_op', '_job_objects', '_emitted',
                 '_current_device')

    def __init__(self):
        self._in_job = False
        self._job_op = ''
        self._job_objects = ''
        self._emitted = False
        self._current_device = ''

    def feed(self, line: str) -> tuple[str, dict] | None:
        """Parse one line.  Returns ``(event_type, data)`` or ``None``."""
        clean = _ANSI_RE.sub('', line)

        if clean.startswith('Added /org/freedesktop/UDisks2/jobs/'):
            self._in_job = True
            self._job_op = ''
            self._job_objects = ''
            self._emitted = False
            return None

        if clean.startswith('Removed /org/freedesktop/UDisks2/jobs/'):
            self._in_job = False
            return None

        if self._in_job and not self._emitted:
            m = _OP_RE.search(clean)
            if m:
                self._job_op = m.group(1)
            m = _OBJ_RE.search(clean)
            if m:
                self._job_objects = m.group(1)
            if self._job_op and self._job_objects:
                self._emitted = True
                return ('job', {'op': self._job_op,
                                'objects': self._job_objects})
            return None

        device = _device_name_from_path(clean)
        if device:
            self._current_device = device

        if self._current_device:
            m = _BACKING_RE.search(clean)
            if m:
                return ('loop_prop', {
                    'device': self._current_device,
                    'prop': 'BackingFile',
                    'value': m.group(1).strip(),
                })
        return None


class _UdisksMonitor(threading.Thread):
    """Background thread: ``udisksctl monitor`` -> parsed events.

    Sets :attr:`backing_cleared` when *device_name*'s ``BackingFile``
    property becomes empty, and :attr:`mount_detected` when a
    ``filesystem-mount`` job targeting *device_name* appears.
    """

    def __init__(self, device_name: str):
        super().__init__(daemon=True)
        self._name = device_name
        self.backing_cleared = threading.Event()
        self.mount_detected = threading.Event()
        self._stop = threading.Event()
        self._parser = _MonitorParser()
        self.ready = threading.Event()

    def reset_events(self):
        self.backing_cleared.clear()
        self.mount_detected.clear()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            proc = subprocess.Popen(
                ['udisksctl', 'monitor'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception:
            self.ready.set()
            return

        # Wait for the first line to confirm D-Bus connection is up,
        # then signal readiness and feed that line to the parser.
        try:
            first = proc.stdout.readline()
        except Exception:
            proc.terminate()
            proc.wait()
            self.ready.set()
            return
        self.ready.set()
        event = self._parser.feed(first)
        self._handle_event(event)

        try:
            for line in proc.stdout:
                if self._stop.is_set():
                    break
                event = self._parser.feed(line)
                self._handle_event(event)
        finally:
            proc.stdout.close()
            proc.terminate()
            proc.wait()

    def _handle_event(self, event):
        if event is None:
            return
        etype, data = event
        if etype == 'job':
            if (data['op'] == 'filesystem-mount' and
                    self._name in data['objects']):
                self.mount_detected.set()
        elif etype == 'loop_prop':
            if (data['device'] == self._name and
                    data['prop'] == 'BackingFile' and
                    not data['value']):
                self.backing_cleared.set()


_pending_detaches: set['_DetachThread'] = set()


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
        monitor = _UdisksMonitor(self._name)
        monitor.start()
        if not monitor.ready.wait(timeout=10):
            print(f"device {self._device}: monitor failed to start, "
                  f"giving up")
            return
        try:
            while True:
                monitor.reset_events()
                _unmount_normal(self._device, None)
                time.sleep(0.15)
                loop_delete(self._device)
                print(f"device {self._device}: loop-delete issued, "
                      f"waiting for monitor...")

                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline:
                    if monitor.mount_detected.is_set():
                        print(f"device {self._device}: auto-mounter "
                              f"re-mounted, retrying...")
                        break

                    if monitor.backing_cleared.is_set():
                        time.sleep(0.3)
                        if monitor.mount_detected.is_set():
                            break
                        print(f"device {self._device} detached")
                        return
                    time.sleep(0.1)
                else:
                    _fallback_detach(self._name, self._device)
                    return
        finally:
            monitor.stop()
            monitor.join(timeout=3)


def _fallback_detach(name: str, device: str):
    """Fallback: aggressive unmount–delete–poll retry loop.

    Used when the udisksctl monitor does not confirm detachment
    before the timeout.
    """
    sys_path = f'/sys/block/{name}'
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
