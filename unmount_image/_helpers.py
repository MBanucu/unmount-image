"""Internal subprocess helpers."""

import subprocess


def loop_delete(loop_dev: str):
    return subprocess.run(
        ['udisksctl', 'loop-delete', '-b', loop_dev, '--no-user-interaction'],
        capture_output=True)


def power_off(device: str):
    return subprocess.run(
        ['udisksctl', 'power-off', '-b', device, '--no-user-interaction'],
        capture_output=True)
