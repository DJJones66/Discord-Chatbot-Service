import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
venv_python = root / ".venv" / "bin" / "python"
requirements = root / "requirements.txt"

subprocess.run([str(venv_python), "-m", "pip", "install", "-U", "pip"], check=True)
subprocess.run([str(venv_python), "-m", "pip", "install", "-r", str(requirements)], check=True)

init_db_script = root / "service_scripts" / "init_db.py"
if init_db_script.exists():
    subprocess.run([str(venv_python), str(init_db_script)], check=True)

print("dependencies installed")
