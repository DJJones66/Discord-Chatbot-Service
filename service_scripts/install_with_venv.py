import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
venv_python = root / ".venv" / "bin" / "python"
requirements = root / "requirements.txt"

subprocess.run([str(venv_python), "-m", "pip", "install", "-U", "pip"], check=True)
subprocess.run([str(venv_python), "-m", "pip", "install", "-r", str(requirements)], check=True)

print("dependencies installed")
