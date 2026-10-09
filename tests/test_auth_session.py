import os
import secrets
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Request

from api.auth import hash_password, install_auth, verify_password
from api.ui import install_ui


class AuthSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.password = secrets.token_urlsafe(24)
        self.user_id = "server-configured-user"
        settings = {
            "HERMES_LOGIN_USERNAME": "operator",
            "HERMES_LOGIN_USER_ID": self.user_id,
            "HERMES_LOGIN_PASSWORD_HASH": hash_password(self.password),
            "HERMES_SESSION_COOKIE_SECURE": "false",
            "HERMES_SESSION_TTL_SECONDS": "3600",
        }
        with patch.dict(os.environ, settings):
            self.app = FastAPI()
            install_auth(self.app)
            install_ui(self.app)

        @self.app.get("/protected")
        def protected(request: Request):
            return {"user_id": request.state.user_id}

        @self.app.get("/health")
        def health():
            return {"status": "ok"}

        @self.app.post("/identity-check")
        def identity_check(request: Request, payload: dict):
            return {"user_id": request.state.user_id}

    async def _client(self, host="127.0.0.1"):
        transport = httpx.ASGITransport(
            app=self.app,
            client=(host, 12345),
        )
        return httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
        )

    async def test_login_session_identity_and_logout(self):
        async with await self._client() as client:
            self.assertEqual((await client.get("/protected")).status_code, 401)
            bad = await client.post(
                "/auth/login",
                json={"username": "operator", "password": "wrong"},
            )
            self.assertEqual(bad.status_code, 401)

            login = await client.post(
                "/auth/login",
                json={
                    "username": "operator",
                    "password": self.password,
                    "user_id": "forged-user",
                },
            )
            self.assertEqual(login.status_code, 200)
            self.assertEqual(login.json()["user_id"], self.user_id)
            self.assertIn("HttpOnly", login.headers["set-cookie"])
            self.assertIn("SameSite=strict", login.headers["set-cookie"])
            self.assertEqual(
                (await client.get("/protected")).json()["user_id"],
                self.user_id,
            )
            self.assertEqual(
                (
                    await client.post(
                        "/identity-check", json={"user_id": "forged-user"},
                    )
                ).json()["user_id"],
                self.user_id,
            )
            self.assertEqual(
                (await client.get("/auth/me?user_id=forged-user")).json()["user_id"],
                self.user_id,
            )

            self.assertEqual((await client.post("/auth/logout")).status_code, 200)
            self.assertEqual((await client.get("/protected")).status_code, 401)

    async def test_ui_login_page_and_protected_app(self):
        async with await self._client() as client:
            login_page = await client.get("/login")
            self.assertEqual(login_page.status_code, 200)
            self.assertIn("login-form", login_page.text)
            self.assertEqual(login_page.headers["cache-control"], "no-store")

            app_page = await client.get("/app", follow_redirects=False)
            self.assertEqual(app_page.status_code, 303)
            self.assertEqual(app_page.headers["location"], "/login")
            self.assertEqual((await client.get("/static/chat.js")).status_code, 401)

            await client.post(
                "/auth/login",
                json={"username": "operator", "password": self.password},
            )
            self.assertEqual((await client.get("/app")).status_code, 200)
            self.assertEqual((await client.get("/static/chat.js")).status_code, 200)

    async def test_health_requires_session(self):
        async with await self._client() as client:
            self.assertEqual((await client.get("/health")).status_code, 401)
            await client.post(
                "/auth/login",
                json={"username": "operator", "password": self.password},
            )
            self.assertEqual((await client.get("/health")).status_code, 200)
            await client.post("/auth/logout")
            self.assertEqual((await client.get("/health")).status_code, 401)

    async def test_remote_plain_http_is_rejected(self):
        async with await self._client(host="192.0.2.7") as client:
            response = await client.post(
                "/auth/login",
                json={"username": "operator", "password": self.password},
            )
            self.assertEqual(response.status_code, 403)

    async def test_cross_origin_post_is_rejected(self):
        async with await self._client() as client:
            response = await client.post(
                "/auth/login",
                headers={"Origin": "http://untrusted.example"},
                json={"username": "operator", "password": self.password},
            )
            self.assertEqual(response.status_code, 403)

    async def test_secure_cookie_and_logout(self):
        settings = {
            "HERMES_LOGIN_USERNAME": "operator",
            "HERMES_LOGIN_USER_ID": self.user_id,
            "HERMES_LOGIN_PASSWORD_HASH": hash_password(self.password),
            "HERMES_SESSION_COOKIE_SECURE": "true",
        }
        with patch.dict(os.environ, settings):
            app = FastAPI()
            install_auth(app)
        transport = httpx.ASGITransport(app=app, client=("192.0.2.7", 12345))
        async with httpx.AsyncClient(transport=transport, base_url="https://hermes.example") as client:
            login = await client.post(
                "/auth/login", json={"username": "operator", "password": self.password},
            )
            self.assertEqual(login.status_code, 200)
            self.assertIn("Secure", login.headers["set-cookie"])
            self.assertIn("__Host-hermes_session", login.headers["set-cookie"])
            self.assertEqual((await client.get("/auth/me")).json()["user_id"], self.user_id)
            logout = await client.post("/auth/logout")
            self.assertIn("Secure", logout.headers["set-cookie"])
            self.assertEqual((await client.get("/auth/me")).status_code, 401)

    def test_missing_credentials_fail_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                install_auth(FastAPI())

    def test_password_hash_is_salted_and_verifiable(self):
        first = hash_password(self.password)
        second = hash_password(self.password)
        self.assertNotEqual(first, second)
        self.assertNotIn(self.password, first)
        self.assertTrue(verify_password(self.password, first))
        self.assertFalse(verify_password("wrong", first))


if __name__ == "__main__":
    unittest.main()
