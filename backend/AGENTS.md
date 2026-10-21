## Engineering guidelines

- Follow the repository's root AGENTS.md instructions.
- Do not use deprecated APIs.

## Server management

- The backend must use port 3001. The frontend uses port 3000.
- The user manages the servers. Do not start, restart, or stop any server unless the user explicitly requests it.
- Do not start a server for testing or verification. Use checks that do not launch servers.
- When the user runs the backend from this directory, use `.venv/bin/python app.py` or `.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 3001`.
