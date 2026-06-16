"""Disk image unmount and detach via udisksctl (Linux, no sudo needed).

Uses ``udisksctl unmount`` to unmount filesystems and
``udisksctl loop-delete`` to detach loop devices via UDisks2.
PolKit grants active local sessions permission without a password
on most desktop distributions.

Key advantages over manual umount + losetup:
  - No root password required (uses polkit authorisation)
  - Handles auto-mounter re-mount races
  - Retry and fallback strategies
  - Monitor-based detach confirmation
"""

from unmount_image._api import (
    detach_image,
    detach_inner,
    umount_image,
    umount_inner,
)
from unmount_image._strategy import (
    StepFn,
    UNMOUNT_FAIL_FAST,
    UNMOUNT_FORCE,
    UNMOUNT_FORCE_THEN_LAZY,
    UNMOUNT_LAZY,
    UNMOUNT_RETRY,
    UNMOUNT_RETRY_THEN_LAZY,
    _unmount_force,
    _unmount_lazy,
    _unmount_normal,
    compose,
    retry,
)
