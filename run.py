"""Entry point: `python run.py` or `flask --app run run`."""
import os
import socket
import sys

from app import create_app

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))


def _port_is_free(host: str, port: int) -> bool:
    """True when nothing is listening on the port yet.

    SO_REUSEADDR must NOT be set here: on Windows it allows a second socket to
    bind a port that is already in use, which would let two instances serve on
    the same port and fight over the SQLite file.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _guard_port() -> None:
    """Stop the app when the port is taken by another instance.

    The Werkzeug reloader runs this module twice: the parent process creates
    the listening socket, then restarts the app in a child process that
    inherits that socket. The child must not re-check the port - the parent
    already holds it, so the probe would fail and the app would never start.
    """
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return
    if _port_is_free(HOST, PORT):
        return
    print(
        f"\n[run] Port {PORT} is already in use - another instance of the app is\n"
        f"      probably still running. Stop it first, or use a different port:\n"
        f"          taskkill /PID <pid> /F\n"
        f"          set PORT=5001 && python run.py\n",
        file=sys.stderr,
    )
    raise SystemExit(1)


if __name__ == "__main__":
    # Check the port before the app touches the database, so a refused start
    # leaves no trace (no autobackup, no migration).
    _guard_port()

from app import create_app  # noqa: E402  (import order matters, see above)

app = create_app()


def main() -> None:
    _guard_port()
    print(f"[run] Serving on http://127.0.0.1:{PORT}")
    app.run(debug=True, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
