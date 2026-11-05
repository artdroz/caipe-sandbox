"""Compare editable files with retained configuration, without running processes."""

import hashlib
import json


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_changes(current, applied, previous, defaults, errors=None):
    errors = errors or {}
    result = []
    for name in sorted(
        set(current) | set(applied) | set(previous) | set(defaults) | set(errors)
    ):
        exists = name in current or name in errors
        sources = [
            source
            for source, values in (
                ("applied", applied),
                ("previous", previous),
                ("default", defaults),
            )
            if name in values
        ]
        if name in errors:
            status = "invalid"
        elif name in current:
            status = (
                "new"
                if name not in applied
                else "applied"
                if current[name] == applied[name]
                else "changed"
            )
        else:
            status = "deleted" if name in applied else "recoverable"
        result.append(
            {
                "name": name,
                "exists": exists,
                "revision": hashlib.sha256(current[name].encode()).hexdigest()
                if name in current
                else None,
                "status": status,
                "recovery_sources": sources,
                **({"error": errors[name]} if name in errors else {}),
            }
        )
    return result
