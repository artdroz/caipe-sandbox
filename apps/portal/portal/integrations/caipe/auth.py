"""Verify CAIPE's hosted-app JWT contract; Sandbox retains authorization."""

import math
import re
import time

from fastapi import HTTPException
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from pydantic import BaseModel, ConfigDict, Field


class CaipePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str = Field(default="caipe-agentic-apps", min_length=1)
    app_id: str = Field(
        default="sandbox", pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
    )
    default_role: str = Field(default="user", pattern=r"^(user|viewer)$")
    session_seconds: int = Field(default=3600, ge=60, le=86400, strict=True)


class CaipeAuthentication:
    signin_message = (
        "Your CAIPE session may have expired. Reopen Sandbox from CAIPE to continue."
    )

    def __init__(self, settings):
        self.policy = CaipePolicy.model_validate_json(settings.caipe_policy)
        # CAIPE normalizes Secret values before signing.
        key = settings.caipe_verification_key.strip()
        if len(key.encode()) < 32:
            raise ValueError("CAIPE requires a verification key of at least 32 bytes")
        self.key = OctKey.import_key(key.encode())

    def identity(self, connection):
        authorization = connection.headers.get("authorization", "").split()
        if len(authorization) != 2 or authorization[0].lower() != "bearer":
            raise HTTPException(401, "Open Sandbox from CAIPE to sign in")
        try:
            if len(authorization[1]) > 16384:
                raise ValueError("Oversized token")
            claims = jwt.decode(authorization[1], self.key, algorithms=["HS256"]).claims
            jwt.JWTClaimsRegistry(
                iss={"essential": True, "value": self.policy.issuer},
                aud={"essential": True, "value": "agentic-app:" + self.policy.app_id},
                exp={"essential": True},
                iat={"essential": True},
            ).validate(claims)
            email, subject = claims.get("email"), claims.get("sub")
            if (
                claims.get("app_id") != self.policy.app_id
                or not isinstance(email, str)
                or len(email) > 254
                or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
                or not isinstance(subject, str)
                or not subject.strip()
                or len(subject) > 512
                or any(
                    type(claims[field]) not in {int, float}
                    or not math.isfinite(claims[field])
                    for field in ("exp", "iat")
                )
                or claims["iat"] > time.time() + 30
            ):
                raise ValueError("Invalid identity")
        except (JoseError, ValueError, TypeError, KeyError):
            raise HTTPException(
                401, "CAIPE sign-in is missing, invalid or expired"
            ) from None
        return {
            "owner": email.lower(),
            "subject": subject,
            "expires": time.time() + self.policy.session_seconds,
        }
