r"""
Convenience launcher for the FastAPI backend.

    .\.venv\Scripts\python.exe scripts\run_api.py
    .\.venv\Scripts\python.exe scripts\run_api.py --port 8123   # force a port

Picks a port that Windows will actually let us bind to. On Windows, Hyper-V/WSL/
Docker reserve large ranges of ports, and binding a reserved one fails with
"WinError 10013 — access forbidden" (NOT 'in use'). So by default we probe a few
known-friendly ports and use the first that binds. Docs at http://localhost:<port>/docs
"""

import argparse
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

# 8000 is a common casualty of Windows reserved ranges; these tend to be free.
CANDIDATE_PORTS = [8040, 8050, 8123, 8200, 8500, 8765, 9001]


def _can_bind(port: int) -> bool:
    """True if we can actually bind this port (catches reserved ports too)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Polymarket MM API.")
    parser.add_argument("--port", type=int, default=None, help="force a specific port")
    args = parser.parse_args()

    if args.port is not None:
        port = args.port
        if not _can_bind(port):
            print(f"Port {port} can't be bound (in use or reserved by Windows). "
                  f"Try another, e.g. --port 8123.")
            return 1
    else:
        port = next((p for p in CANDIDATE_PORTS if _can_bind(p)), None)
        if port is None:
            print("None of the candidate ports were bindable. Pass --port <n> with a free port.")
            return 1

    # flush so these lines appear before uvicorn's own logging in the console.
    print(f"\n  API:  http://localhost:{port}", flush=True)
    print(f"  Docs: http://localhost:{port}/docs   (try the endpoints here)\n", flush=True)
    uvicorn.run("api.main:app", host="127.0.0.1", port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
