import os
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
venv_dir = root / ".venv"

force = os.getenv("VENV_FORCE_RECREATE", "").strip() == "1"
if force and venv_dir.exists():
    shutil.rmtree(venv_dir)

if not venv_dir.exists():
    subprocess.run(["python3", "-m", "venv", str(venv_dir)], check=True)

print(f"venv ready: {venv_dir}")
