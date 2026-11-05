"""Outcomes that runtime adapters can confirm independently of transport errors."""

from fastapi import HTTPException


class CreationRejected(HTTPException):
    """The runtime rejected creation and will perform no further create effects."""
