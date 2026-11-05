"""Pod-local shutdown signal shared by the portal and its exec preStop hook."""

import math
import os
import tempfile
import time
from pathlib import Path

from fastapi import HTTPException


def duration_label(seconds):
    if seconds and seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute" + ("s" if minutes != 1 else "")
    return f"{seconds} second" + ("s" if seconds != 1 else "")


class Drain:
    def __init__(self, path):
        self.path = Path(path)

    def reset(self):
        self.path.unlink(missing_ok=True)

    def remaining(self):
        try:
            deadline = float(self.path.read_text())
            if not math.isfinite(deadline):
                return 0
            return max(0, deadline - time.monotonic())
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            return 0

    def require_accepting(self):
        if self.remaining() is not None:
            raise HTTPException(
                503,
                "Portal is restarting; retry when it is ready",
                headers={"Retry-After": "2"},
            )

    def begin(self, seconds):
        if not 0 <= seconds <= 660:
            raise ValueError("Drain duration must be between 0 and 660 seconds")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=self.path.parent, delete=False
        ) as temporary:
            temporary.write(str(time.monotonic() + seconds))
        try:
            try:
                os.link(temporary.name, self.path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary.name)


def main():
    drain = Drain(os.environ.get("PORTAL_DRAIN_FILE", "/tmp/portal-drain"))
    propagation = int(os.environ.get("PORTAL_DRAIN_PROPAGATION_SECONDS", "10"))
    sessions = int(os.environ.get("PORTAL_DRAIN_SECONDS", "180"))
    if not 0 <= propagation <= 60 or not 0 <= sessions <= 600:
        raise ValueError("Invalid portal drain budget")
    drain.begin(propagation + sessions)
    while (remaining := drain.remaining()) > 0:
        time.sleep(min(remaining, 0.25))


if __name__ == "__main__":
    main()
