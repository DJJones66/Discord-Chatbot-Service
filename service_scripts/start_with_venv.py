import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
venv_python = root / ".venv" / "bin" / "python"
log_dir = root / "data"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "service.log"

cmd = [str(venv_python), str(root / "service.py")]

with log_file.open("ab") as log_handle:
    proc = subprocess.Popen(
        cmd,
        cwd=str(root),
        stdout=log_handle,
        stderr=log_handle,
        env=os.environ.copy(),
    )

pid_file = log_dir / "service.pid"
pid_file.write_text(str(proc.pid))

print(f"started pid={proc.pid}")
