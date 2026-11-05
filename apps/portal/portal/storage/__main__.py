"""Schema setup and read-only checks for portal init containers and operators."""

import argparse
import os
import sys

from . import StorageError, open_store
from .database import DatabaseSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["migrate", "check"])
    args = parser.parse_args()
    store = None
    try:
        store = open_store(
            DatabaseSettings(
                url=os.environ.get(
                    "PORTAL_DATABASE_URL", "sqlite:////var/lib/portal/metadata.db"
                ),
                expected_backend=os.environ.get("PORTAL_DATABASE_BACKEND", ""),
            )
        )
        if args.action == "migrate":
            store.migrate()
        store.check_schema()
        print("Metadata schema is current")
        return 0
    except StorageError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError:
        print(
            "Invalid metadata database configuration; check the database URL and connection settings",
            file=sys.stderr,
        )
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
