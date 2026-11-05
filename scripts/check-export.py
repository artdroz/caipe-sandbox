"""Reject internal deployment configuration and private build dependencies."""

import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
paths = (
    subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
    )
    .decode()
    .split("\0")
)
patterns = [
    r"cisco-eti/",
    r"\d{12}\.dkr\.ecr\.",
    r"agents-dev-use2-1",
    r"sandbox\.outshift\.io",
    r"VAULT_APPROLE",
    r"DEFAULT_ARC_RUNNERS",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
]
failures = []
for name in sorted(set(paths) - {"", "scripts/check-export.py"}):
    path = root / name
    if not path.is_file():
        continue
    try:
        content = path.read_text()
    except UnicodeError:
        continue
    for pattern in patterns:
        if re.search(pattern, content):
            failures.append(
                f"{name}: internal configuration or private credential marker ({pattern})"
            )
if failures:
    raise SystemExit("\n".join(failures))
print("Portable export checks passed")
