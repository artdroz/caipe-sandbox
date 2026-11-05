"""Wait for CLI login, then run the Omnigent host under the workspace supervisor."""

import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit


def main():
    server = os.environ.get("OMNIGENT_SERVER_URL", "").rstrip("/")
    parsed = urlsplit(server)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("Set OMNIGENT_SERVER_URL before enabling the Omnigent service")
    auth = Path.home() / ".omnigent/auth_tokens.json"
    print("Waiting for Omnigent login; use the Sign in to Omnigent helper.", flush=True)
    while True:
        try:
            configured = bool(json.loads(auth.read_text()).get(server))
        except (OSError, ValueError, AttributeError):
            configured = False
        if configured:
            os.execvp("omnigent", ["omnigent", "host", "--server", server])
        time.sleep(2)


if __name__ == "__main__":
    main()
