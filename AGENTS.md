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
  test_unit.py                  — unit tests (API, strategies)
  test_monitor.py               — _UdisksMonitor signals, _fallback_detach
  test_parser.py                — _MonitorParser basic parsing
  test_int.py                   — integration tests (real udisksctl)
  test_ansi_edge.py             — ANSI escape handling edge cases
  test_job_interleaving_edge.py — concurrent job interleaving
  test_parser_state_edge.py     — parser state machine boundary conditions
  test_device_name_edge.py      — device name extraction edge cases
  test_property_value_edge.py   — property value parsing edge cases
  test_loop_recycling_edge.py   — loop device number recycling
  test_concurrent_events_edge.py — interleaved events from multiple devices
  test_backing_file_edge.py     — BackingFile lifecycle edge cases
tools/
  capture_monitor.py   — capture live monitor output with labels
  analyze_monitor.py   — parse and summarize captured output
  inspect_regex.py     — test regexes against captured/live output
  stress_monitor.py    — concurrent stress test with real devices
docs/
  index.md             — documentation index
  01-...10-*.md        — udisksctl monitor reference docs
  11-manual-testing.md — manual test procedures
  12-agent-tools.md    — LLM agent workflows and tools
