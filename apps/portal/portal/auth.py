"""Portal authentication and group policy, independent of Kubernetes credentials."""

import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .terminal_auth import TerminalCredentials

COOKIE = "agent_sandbox_session"


class OIDCPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str = ""
    client_id: str = ""
    scopes: str = "openid email profile groups"
    email_claim: str = "email"
    groups_claim: str = "groups"
    require_verified_email: bool = True
    use_userinfo: bool = False
    allowed_email_domains: list[str] = Field(default_factory=list)
    allowed_groups: list[str] = Field(default_factory=list)
    role_groups: dict[str, list[str]] = Field(default_factory=dict)
    default_role: str = ""
    session_seconds: int = Field(default=3600, ge=60, le=86400, strict=True)

    @model_validator(mode="after")
    def roles(self):
        if set(self.role_groups) - {"viewer", "user"} or self.default_role not in {
            "",
            "viewer",
            "user",
        }:
            raise ValueError("OIDC roles must be viewer or user")
        if "openid" not in self.scopes.split():
            raise ValueError("OIDC scopes must include openid")
        return self

    def role(self, email, groups):
        if self.allowed_email_domains and email.rsplit("@", 1)[-1] not in {
            domain.lower() for domain in self.allowed_email_domains
        }:
            raise HTTPException(403, "Your email domain cannot access this portal")
        if self.allowed_groups and not set(groups).intersection(self.allowed_groups):
            raise HTTPException(403, "Your groups cannot access this portal")
        for role in ("user", "viewer"):
            if set(groups).intersection(self.role_groups.get(role, [])):
                return role
        if self.default_role:
            return self.default_role
        raise HTTPException(403, "No portal role is mapped to your groups")


@dataclass(frozen=True)
class Principal:
    owner: str
    role: str

    def require_user(self):
        if self.role not in {"user", "admin"}:
            raise HTTPException(403, "Your portal role permits viewing only")

    def require_admin(self):
        if self.role != "admin":
            raise HTTPException(403, "Administrator access is required")


class Authentication:
    def __init__(self, settings):
        self.settings = settings
        admins = json.loads(settings.admin_emails)
        if not isinstance(admins, list) or any(
            not isinstance(email, str)
            or len(email) > 254
            or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
            for email in admins
        ):
            raise ValueError("PORTAL_ADMIN_EMAILS must be a list of email addresses")
        self.admins = {email.lower() for email in admins}
        self.policy = OIDCPolicy.model_validate_json(settings.oidc_policy)
        if settings.auth_mode not in {"omnigent", "oidc", "caipe"}:
            raise ValueError("PORTAL_AUTH_MODE must be omnigent, oidc or caipe")
        self.hosted = None
        self.terminal_credentials = None
        if settings.auth_mode == "caipe":
            from .integrations.caipe.auth import CaipeAuthentication

            self.hosted = CaipeAuthentication(settings)
            self.terminal_credentials = TerminalCredentials(settings.session_secret)
            if (
                settings.session_secret.strip()
                == settings.caipe_verification_key.strip()
            ):
                raise ValueError(
                    "Use separate CAIPE verification and Sandbox session keys"
                )
        self.client = None
        if settings.auth_mode == "oidc":
            issuer = urlsplit(self.policy.issuer)
            if (
                issuer.scheme != "https"
                or not issuer.netloc
                or issuer.username
                or issuer.query
                or issuer.fragment
                or not self.policy.client_id
                or not settings.oidc_client_secret
                or len(settings.session_secret) < 32
                or urlsplit(settings.origin).scheme != "https"
            ):
                raise ValueError(
                    "OIDC requires HTTPS origin/issuer, client ID/secret and a session secret of at least 32 characters"
                )
            if not self.policy.default_role and not any(
                self.policy.role_groups.values()
            ):
                raise ValueError(
                    "OIDC requires role mappings or an explicit default role"
                )
            oauth = OAuth()
            self.client = oauth.register(
                "portal",
                client_id=self.policy.client_id,
                client_secret=settings.oidc_client_secret,
                server_metadata_url=self.policy.issuer.rstrip("/")
                + "/.well-known/openid-configuration",
                client_kwargs={
                    "scope": self.policy.scopes,
                    "code_challenge_method": "S256",
                    "timeout": 15,
                },
            )

    @property
    def oidc(self):
        return self.settings.auth_mode == "oidc"

    @property
    def login_url(self):
        if self.hosted:
            return None
        if self.oidc:
            return self.settings.base_path + "/auth/login"
        return "/auth/login?return_to=" + self.settings.base_path + "/"

    def session(self, claims):
        email = claims.get(self.policy.email_claim)
        if (
            not isinstance(email, str)
            or len(email) > 254
            or email.count("@") != 1
            or any(c.isspace() for c in email)
            or not all(email.split("@"))
            or not isinstance(claims.get("sub"), str)
            or not claims["sub"]
        ):
            raise HTTPException(403, "OIDC must supply a subject and email identity")
        if (
            self.policy.require_verified_email
            and claims.get("email_verified") is not True
        ):
            raise HTTPException(403, "A verified email is required")
        groups = claims.get(self.policy.groups_claim, [])
        if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
            raise HTTPException(403, "OIDC groups must be a list of strings")
        email = email.lower()
        self.policy.role(email, groups)
        # Keep only policy-relevant groups; never store provider tokens in cookies.
        relevant = set(self.policy.allowed_groups)
        for names in self.policy.role_groups.values():
            relevant.update(names)
        now = time.time()
        if float(claims["exp"]) <= now:
            raise HTTPException(401, "OIDC identity has expired")
        return {
            "owner": email,
            "subject": claims["sub"],
            "issuer": self.policy.issuer,
            "client_id": self.policy.client_id,
            "groups": sorted(set(groups).intersection(relevant)),
            "expires": now + self.policy.session_seconds,
        }

    async def principal(self, connection, upstream):
        if self.hosted:
            record = (
                getattr(connection.state, "terminal_identity", {})
                if connection.scope["type"] == "websocket"
                else self.hosted.identity(connection)
            )
            if record.get("expires", 0) <= time.time():
                raise HTTPException(
                    401, "CAIPE terminal session expired; reconnect from Sandbox"
                )
            connection.state.terminal_identity = record
            return Principal(
                record["owner"],
                "admin"
                if record["owner"] in self.admins
                else self.hosted.policy.default_role,
            )
        if self.oidc:
            record = connection.session.get("identity", {})
            if (
                record.get("issuer") != self.policy.issuer
                or record.get("client_id") != self.policy.client_id
                or not isinstance(record.get("owner"), str)
                or record.get("expires", 0) <= time.time()
            ):
                raise HTTPException(401, "Sign in to the sandbox portal")
            role = self.policy.role(record["owner"], record.get("groups", []))
            return Principal(
                record["owner"],
                "admin" if record["owner"].lower() in self.admins else role,
            )
        headers = {
            key: connection.headers[key]
            for key in ("cookie", "authorization")
            if key in connection.headers
        }
        try:
            response = await upstream.get("/v1/me", headers=headers)
        except httpx.HTTPError:
            raise HTTPException(
                503, "Omnigent authentication service is unavailable"
            ) from None
        if response.status_code != 200:
            raise HTTPException(401, "Sign in to Omnigent first")
        owner = response.json().get("user_id")
        if not isinstance(owner, str) or not owner or owner == "local":
            raise HTTPException(401, "An authenticated user account is required")
        return Principal(owner, "admin" if owner.lower() in self.admins else "user")
