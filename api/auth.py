"""Single-account session authentication for the Hermes HTTP API."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

_SCRYPT_N = 1 << 15
_SCRYPT_R = 8
_SCRYPT_P = 3
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_PUBLIC_PATHS = frozenset({"/auth/login", "/login"})
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class Identity:
    user_id: str
    username: str


@dataclass(frozen=True)
class AuthConfig:
    identity: Identity
    password_hash: str
    cookie_secure: bool
    session_ttl_seconds: int

    @classmethod
    def from_environment(cls) -> "AuthConfig":
        username = os.environ.get("HERMES_LOGIN_USERNAME", "").strip()
        user_id = os.environ.get("HERMES_LOGIN_USER_ID", "").strip()
        password_hash = os.environ.get("HERMES_LOGIN_PASSWORD_HASH", "").strip()
        if not username or not user_id or not _valid_hash_format(password_hash):
            raise RuntimeError(
                "HERMES_LOGIN_USERNAME, HERMES_LOGIN_USER_ID, and a valid "
                "HERMES_LOGIN_PASSWORD_HASH are required"
            )

        secure_value = os.environ.get("HERMES_SESSION_COOKIE_SECURE", "true").lower()
        if secure_value not in ("true", "false"):
            raise RuntimeError("HERMES_SESSION_COOKIE_SECURE must be true or false")

        ttl = int(os.environ.get("HERMES_SESSION_TTL_SECONDS", "3600"))
        if not 300 <= ttl <= 86400:
            raise RuntimeError("HERMES_SESSION_TTL_SECONDS must be 300..86400")

        return cls(
            identity=Identity(user_id=user_id, username=username),
            password_hash=password_hash,
            cookie_secure=(secure_value == "true"),
            session_ttl_seconds=ttl,
        )


def _valid_hash_format(encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, digest = encoded.split("$")
        return (
            algorithm == "scrypt"
            and (int(n), int(r), int(p)) == (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
            and len(bytes.fromhex(salt)) >= 16
            and len(bytes.fromhex(digest)) == 32
        )
    except (ValueError, TypeError):
        return False


def hash_password(password: str) -> str:
    """Generate a salted password hash for secure configuration."""
    if len(password) < 12:
        raise ValueError("Login password must have at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
        maxmem=_SCRYPT_MAXMEM,
    )
    return "$".join((
        "scrypt", str(_SCRYPT_N), str(_SCRYPT_R), str(_SCRYPT_P),
        salt.hex(), digest.hex(),
    ))


def verify_password(password: str, encoded: str) -> bool:
    if not _valid_hash_format(encoded):
        return False
    _, _, _, _, salt_hex, digest_hex = encoded.split("$")
    candidate = hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt_hex),
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
        maxmem=_SCRYPT_MAXMEM,
    )
    return hmac.compare_digest(candidate, bytes.fromhex(digest_hex))


class SessionStore:
    """Process-local opaque sessions; a process restart invalidates all sessions."""

    def __init__(self, identity: Identity, ttl_seconds: int):
        self.identity = identity
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, tuple[float, Identity]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create(self, identity: Identity) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = time.monotonic() + self.ttl_seconds
        with self._lock:
            self._sessions[self._key(token)] = (expires_at, identity)
        return token

    def resolve(self, token: str | None) -> Identity | None:
        if not token or len(token) > 256:
            return None
        key = self._key(token)
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            expires_at, identity = session
            if expires_at <= time.monotonic():
                self._sessions.pop(key, None)
                return None
        return identity

    def revoke(self, token: str | None) -> None:
        if token and len(token) <= 256:
            with self._lock:
                self._sessions.pop(self._key(token), None)


class LoginRequest(BaseModel):
    username: str
    password: str


def _transport_allowed(request: Request, secure_cookie: bool) -> bool:
    if secure_cookie:
        return request.url.scheme == "https"
    if request.client is None:
        return False
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def install_auth(app: FastAPI) -> SessionStore:
    config = AuthConfig.from_environment()
    sessions = SessionStore(config.identity, config.session_ttl_seconds)
    cookie_name = (
        "__Host-hermes_session" if config.cookie_secure else "hermes_session"
    )

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        if not _transport_allowed(request, config.cookie_secure):
            return JSONResponse(
                status_code=403,
                content={"detail": "Secure or loopback transport required"},
            )

        if request.method in _UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Origin not allowed"},
                )

        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        identity = sessions.resolve(request.cookies.get(cookie_name))
        if identity is None:
            if request.url.path == "/app" and request.method == "GET":
                return RedirectResponse(url="/login", status_code=303)
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )

        request.state.identity = identity
        request.state.user_id = identity.user_id
        return await call_next(request)

    @app.post("/auth/login")
    async def login(payload: LoginRequest, response: Response):
        username_ok = hmac.compare_digest(
            payload.username.encode("utf-8"),
            config.identity.username.encode("utf-8"),
        )
        password_ok = verify_password(payload.password, config.password_hash)
        if not (username_ok and password_ok):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = sessions.create(config.identity)
        response.set_cookie(
            key=cookie_name,
            value=token,
            max_age=config.session_ttl_seconds,
            httponly=True,
            secure=config.cookie_secure,
            samesite="strict",
            path="/",
        )
        return {
            "user_id": config.identity.user_id,
            "username": config.identity.username,
        }

    @app.get("/auth/me")
    async def me(request: Request):
        identity: Identity = request.state.identity
        return {"user_id": identity.user_id, "username": identity.username}

    @app.post("/auth/logout")
    async def logout(request: Request, response: Response):
        sessions.revoke(request.cookies.get(cookie_name))
        response.delete_cookie(
            key=cookie_name, path="/", secure=config.cookie_secure,
            httponly=True, samesite="strict",
        )
        return {"ok": True}

    return sessions


if __name__ == "__main__":
    import getpass

    print(hash_password(getpass.getpass("New Hermes login password: ")))
