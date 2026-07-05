r"""
Convenience launcher for the Streamlit UI.

    .\.venv\Scripts\python.exe scripts\run_app.py

(Equivalent to `python -m streamlit run app/main.py`, just shorter to type.)
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    app = ROOT / "app" / "main.py"
    # Re-use the same interpreter that's running this script (the venv python).
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)])


if __name__ == "__main__":
    raise SystemExit(main())
