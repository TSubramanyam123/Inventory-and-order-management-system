"""Idempotently apply schema version 1 to each owned SQLite database."""
import sys
from pathlib import Path
from dotenv import load_dotenv
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root));load_dotenv(root/'.env')
from common.db import Store,TABLES
for name in TABLES:
    db=Store(name)
    print(f'{name}: schema v1 ready')
