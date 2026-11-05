"""Renewable database claims; native operations keep their existing retry keys."""

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

from .storage import Conflict, Lease, MetadataStore, StorageError


@dataclass
class Claim:
    metadata: MetadataStore
    lease: Lease
    seconds: int
    lost: threading.Event = field(default_factory=threading.Event)

    def check(self):
        if self.lost.is_set():
            raise Conflict(
                "Operation ownership was lost; refresh and confirm its outcome"
            )
        try:
            if self.metadata.renew_lease(self.lease, seconds=self.seconds):
                return
        except StorageError:
            self.lost.set()
            raise
        self.lost.set()
        raise Conflict("Operation ownership expired; refresh and confirm its outcome")


@contextmanager
def claim(metadata, name, *, seconds=120, required=True):
    lease = metadata.acquire_lease(name, seconds=seconds)
    if lease is None:
        if required:
            raise Conflict(
                "This operation is already being processed; refresh before retrying"
            )
        yield None
        return
    owner = Claim(metadata, lease, seconds)
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(seconds / 3):
            try:
                owner.check()
            except StorageError:
                return

    worker = threading.Thread(target=heartbeat, daemon=True, name="portal-lease")
    worker.start()
    try:
        yield owner
    finally:
        stop.set()
        worker.join(timeout=1)
        try:
            metadata.release_lease(lease)
        except StorageError:
            logging.getLogger(__name__).warning("lease_release_unavailable")
