"""Public API for unmount-image."""

import subprocess

from unmount_image._helpers import loop_delete
from unmount_image._monitor import detach_loop
from unmount_image._strategy import StepFn, UNMOUNT_RETRY_THEN_LAZY


def umount_image(device: str, mount_point: str | None = None,
                 strategy: StepFn = UNMOUNT_RETRY_THEN_LAZY):
    """Unmount and detach a disk image.

    *strategy* is a callable ``(device, mount_point) -> (ok, err)``.
    Use :func:`compose` and :func:`retry` to build custom strategies,
    or pick from the pre-built ones:

    - ``UNMOUNT_FAIL_FAST`` — normal unmount, raise on failure
    - ``UNMOUNT_RETRY`` — normal unmount, retry 3x with 0.5 s delay
    - ``UNMOUNT_FORCE`` — normal, then ``--force``
    - ``UNMOUNT_LAZY`` — normal, then ``umount -l`` (needs *mount_point*)
    - ``UNMOUNT_FORCE_THEN_LAZY`` — normal -> force -> lazy
    - ``UNMOUNT_RETRY_THEN_LAZY`` (**default**) — retry normal 3x -> lazy

    A custom strategy::

        strategy = compose(retry(_unmount_normal, attempts=5),
                           _unmount_force,
                           _unmount_lazy)
    """
    ok, err = strategy(device, mount_point)
    if not ok:
        raise RuntimeError(f"udisksctl unmount failed: {err.strip()}")

    detach_loop(device)


def detach_image(device: str):
    """Detach a block device."""
    detach_loop(device)


def umount_inner(device: str):
    """Unmount without detach. Used by the mount-image orchestrator."""
    r = subprocess.run(
        ['udisksctl', 'unmount', '-b', device, '--no-user-interaction'],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"udisksctl unmount failed: {r.stderr.strip()}")


def detach_inner(device: str):
    """Detach without unmount. Used by the mount-image orchestrator."""
    detach_loop(device)
