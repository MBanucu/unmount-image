# unmount-image — AGENTS.md

## Project

Disk image unmount and detach via udisksctl (Linux).

- **Package**: `unmount-image` (PyPI), `unmount_image` (import)
- **Repo**: `https://github.com/MBanucu/unmount-image`
- **Python**: `>=3.10`
- **License**: GPL-3.0-only

## Commands

```bash
# Install editable, run tests
pip install -e .
python -m unittest discover -s tests -v

# Coverage (NixOS)
nix-shell -p "python313.withPackages(ps: [ ps.coverage ])" --run "
PYTHONPATH=. python -m coverage run --source=unmount_image -m unittest discover -s tests -v
python -m coverage report --show-missing
"

# Coverage (pip)
pip install coverage
python -m coverage run -m unittest discover -s tests -v
python -m coverage report --fail-under=70 --skip-covered
```

## Module structure

```
unmount_image/
  __init__.py    — public API
  _api.py        — umount_image, detach_image, umount_inner, detach_inner
  _strategy.py   — unmount strategies and combinators
  _helpers.py    — loop_delete subprocess wrapper
  _monitor.py    — udisksctl monitor integration, detach thread
tests/
  test_unit.py
  test_monitor.py
  test_parser.py
  test_int.py
```
