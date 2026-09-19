import sys
from pathlib import Path

# Tests import `app.*` directly; the backend package root is this file's parent.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
