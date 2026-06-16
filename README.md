# unmount-image

Disk image unmount and detach via udisksctl (Linux).

[![PyPI version](https://img.shields.io/pypi/v/unmount-image)](https://pypi.org/project/unmount-image/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://www.python.org/)
[![License](https://img.shields.io/github/license/MBanucu/unmount-image)](LICENSE)
[![OS](https://img.shields.io/badge/OS-Linux-blue)](https://github.com/MBanucu/unmount-image)

[![CI](https://img.shields.io/github/actions/workflow/status/MBanucu/unmount-image/test.yml?branch=main)](https://github.com/MBanucu/unmount-image/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/MBanucu/unmount-image/branch/main/graph/badge.svg)](https://codecov.io/gh/MBanucu/unmount-image)

## Quick start

```python
from unmount_image import umount_image

umount_image('/dev/loop0', mount_point='/run/media/user/IMG')
```

## API

- `umount_image(device, mount_point=None, strategy=UNMOUNT_RETRY_THEN_LAZY)` — unmount + detach
- `detach_image(device)` — detach only (non-blocking)
- `umount_inner(device)` — unmount only, used by the [mount-image](https://github.com/MBanucu/mount-image) orchestrator
- `detach_inner(device)` — detach only, used by the [mount-image](https://github.com/MBanucu/mount-image) orchestrator

### Unmount strategies

| Strategy | Pipeline |
|---|---|
| `UNMOUNT_FAIL_FAST` | normal unmount |
| `UNMOUNT_RETRY` | normal unmount, retry 3x |
| `UNMOUNT_FORCE` | normal → `--force` |
| `UNMOUNT_LAZY` | normal → `umount -l` |
| `UNMOUNT_FORCE_THEN_LAZY` | normal → force → lazy |
| `UNMOUNT_RETRY_THEN_LAZY` **(default)** | retry 3x → lazy |

### Custom strategies

```python
from unmount_image import umount_image, compose, retry, _unmount_normal, _unmount_force

strategy = compose(retry(_unmount_normal, attempts=5), _unmount_force)
umount_image('/dev/loop0', strategy=strategy)
```

## License

GPL-3.0-only
