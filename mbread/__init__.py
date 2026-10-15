"""记忆面包 mbread."""
import sys as _sys

if _sys.version_info < (3, 10):
    _sys.stderr.write(
        f"错误：mbread 需要 Python 3.10+，当前是 {_sys.version.split()[0]}（{_sys.executable}）。\n"
        "macOS 可运行：brew install python@3.12 && python3.12 -m venv .venv && "
        "source .venv/bin/activate && pip install -r requirements.txt\n")
    raise SystemExit(1)
