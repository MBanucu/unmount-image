"""Unmount strategy combinators and pre-built strategies."""

import subprocess
import time
from typing import Callable

StepFn = Callable[[str, str | None], tuple[bool, str]]


def _unmount_normal(device: str, _mount_point: str | None) -> tuple[bool, str]:
    r = subprocess.run(
        ['udisksctl', 'unmount', '-b', device, '--no-user-interaction'],
        capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def _unmount_force(device: str, _mount_point: str | None) -> tuple[bool, str]:
    r = subprocess.run(
        ['udisksctl', 'unmount', '-b', device,
         '--force', '--no-user-interaction'],
        capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def _unmount_lazy(_device: str, mount_point: str | None) -> tuple[bool, str]:
    if mount_point:
        subprocess.run(['umount', '-l', mount_point], capture_output=True)
        return True, ''
    return False, 'no mount point for lazy unmount'


def compose(*steps: StepFn) -> StepFn:
    """Chain unmount strategies: each runs only if the previous failed."""
    def _run(device: str, mount_point: str | None = None) -> tuple[bool, str]:
        last_err = ''
        for step in steps:
            ok, err = step(device, mount_point)
            if ok:
                return True, ''
            last_err = err
        return False, last_err
    return _run


def retry(step: StepFn, attempts: int = 3, delay: float = 0.5) -> StepFn:
    """Retry a strategy *attempts* times with *delay* seconds between."""
    def _run(device: str, mount_point: str | None = None) -> tuple[bool, str]:
        last_err = ''
        for _ in range(attempts):
            ok, err = step(device, mount_point)
            if ok:
                return True, ''
            last_err = err
            time.sleep(delay)
        return False, last_err
    return _run


UNMOUNT_FAIL_FAST:          StepFn = compose(_unmount_normal)
UNMOUNT_RETRY:              StepFn = compose(retry(_unmount_normal))
UNMOUNT_FORCE:              StepFn = compose(_unmount_normal, _unmount_force)
UNMOUNT_LAZY:               StepFn = compose(_unmount_normal, _unmount_lazy)
UNMOUNT_FORCE_THEN_LAZY:    StepFn = compose(_unmount_normal, _unmount_force,
                                              _unmount_lazy)
UNMOUNT_RETRY_THEN_LAZY:    StepFn = compose(retry(_unmount_normal),
                                              _unmount_lazy)
