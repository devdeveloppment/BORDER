"""Bout en bout contre le conteneur ``api`` réel (HTTP, cookies, CSRF, base de développement, Redis des
sessions).

Un compte plateforme fictif sans rôle (donc sans MFA) est créé directement dans la base de développement
par le
rôle propriétaire, puis supprimé. Il ne reçoit aucun droit.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from django.contrib.auth.hashers import make_password

API = "http://api:8000/api/v1"
PASSWORD = "Fictif-Live-2026-mdp!"


@pytest.fixture
def live_account() -> Iterator[str]:
    email = f"e2e-{uuid.uuid4().hex[:10]}@plateforme.rbi.test"
    with psycopg.connect(
        host=os.environ["RBI_DB_HOST"],
        port=int(os.environ["RBI_DB_PORT"]),
        dbname=os.environ["RBI_DB_NAME"],
        user=os.environ["RBI_DB_OWNER"],
        password=os.environ["RBI_DB_OWNER_PASSWORD"],
        autocommit=True,
    ) as conn:
        conn.execute(
            "INSERT INTO users_user (id, password, email, first_name, last_name, is_active, date_joined, "
            "security_stamp) VALUES (%s, %s, %s, '', '', true, now(), %s)",
            (uuid.uuid4(), make_password(PASSWORD), email, uuid.uuid4()),
        )
        try:
            yield email
        finally:
            conn.execute("DELETE FROM users_user WHERE email = %s", (email,))


class Browser:
    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def cookie(self, name: str) -> str | None:
        return next((c.value for c in self.jar if c.name == name), None)

    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None, csrf: bool = True
    ) -> tuple[int, Any, dict[str, Any]]:
        """Renvoie (statut, corps JSON ou None, en-têtes) ; le corps est lu avant la fermeture de la
        connexion."""
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        token = self.cookie("csrftoken")
        if csrf and token and method != "GET":
            headers["X-CSRFToken"] = token
        data = json.dumps(body).encode() if body is not None else None
        url = f"{API}{path}"  # service interne, schéma http fixe
        req = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
        try:
            with self.opener.open(req, timeout=10) as response:
                status, raw, received = response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            status, raw, received = error.code, error.read(), error.headers
        set_cookie = " ".join(received.get_all("Set-Cookie") or [])
        meta = {"content_type": received.get("Content-Type"), "set_cookie": set_cookie}
        return status, (json.loads(raw) if raw else None), meta


def test_full_session_lifecycle_against_running_api(live_account: str) -> None:
    browser = Browser()
    status, _, _ = browser.request("GET", "/auth/csrf")
    assert status == 204 and browser.cookie("csrftoken")

    status, _, _ = browser.request(
        "POST", "/auth/login", {"email": live_account, "password": PASSWORD}, csrf=False
    )
    assert status == 403  # CSRF appliqué par le vrai serveur

    status, body, _ = browser.request(
        "POST", "/auth/login", {"email": live_account, "password": "Faux-2026-mdp!!"}
    )
    assert status == 401 and body["title"] == "Identifiants incorrects"

    status, body, meta = browser.request("POST", "/auth/login", {"email": live_account, "password": PASSWORD})
    assert status == 200 and body == {"step": "AUTHENTICATED"}
    cookie = meta["set_cookie"]
    assert "rbi_session=" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert PASSWORD not in cookie

    status, me, _ = browser.request("GET", "/me")
    assert (
        status == 200
        and me["email"] == live_account
        and me["organization"] is None
        and me["permissions"] == []
    )

    status, _, _ = browser.request("POST", "/auth/logout")
    assert status == 204
    status, _, _ = browser.request("GET", "/me")
    assert status == 401


def test_running_api_denies_anonymous_requests() -> None:
    status, body, meta = Browser().request("GET", "/me")
    assert status == 401 and body["title"] == "Authentification requise"
    assert meta["content_type"] == "application/problem+json"
