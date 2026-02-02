import os
import signal
from pathlib import Path

root = Path(__file__).resolve().parents[1]
pid_file = root / "data" / "service.pid"

if not pid_file.exists():
    print("pid file not found")
    raise SystemExit(0)

pid = int(pid_file.read_text().strip())

try:
    os.kill(pid, signal.SIGTERM)
    print(f"stopped pid={pid}")
except ProcessLookupError:
    print("process not found")

try:
    pid_file.unlink()
except OSError:
    pass
