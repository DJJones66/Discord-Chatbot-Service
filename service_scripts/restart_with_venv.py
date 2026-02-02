import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
shutdown = root / "service_scripts" / "shutdown_with_venv.py"
start = root / "service_scripts" / "start_with_venv.py"

subprocess.run(["python3", str(shutdown)], check=False)
subprocess.run(["python3", str(start)], check=True)
