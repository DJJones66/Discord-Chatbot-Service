from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from db import init_db

db_path = init_db()
print(f"Discord service DB initialized at {db_path}")
