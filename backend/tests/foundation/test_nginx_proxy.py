"""P2.10 — Pile réelle derrière Nginx (conteneur ``proxy``) : routage, en-têtes, erreurs, CSRF, adresse
cliente.

Les requêtes partent du conteneur d'outillage (réseau ``edge``) vers Nginx avec l'en-tête ``Host`` d'un
navigateur
local (``localhost:8080``). Les adresses inscrites au journal d'audit sont lues dans la base de développement
par
le rôle propriétaire, via l'identifiant de requête renvoyé par l'API (événements ``auth.login`` en échec, sur
des
comptes fictifs inexistants). La configuration TLS est vérifiée dans l'environnement E2E (scripts/e2e.py).
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import psycopg
import pytest

PROXY = urlparse(os.environ.get("RBI_PROXY_URL", "http://proxy"))
PROXY_IP = os.environ.get("RBI_EDGE_PROXY_IP", "172.29.89.2")
BROWSER_HOST = "localhost:8080"
FORGED = "203.0.113.66"


class Response:
    def __init__(self, status: int, headers: dict[str, str], body: bytes, local_ip: str) -> None:
        self.status, self.headers, self.body, self.local_ip = status, headers, body, local_ip

    def json(self) -> Any:
        return json.loads(self.body)

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")


def send(
    method: str,
    path: str,
    *,
    host: str = PROXY.hostname or "proxy",
    port: int = PROXY.port or 80,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> Response:
    connection = http.client.HTTPConnection(host, port, timeout=15)
    connection.connect()
    assert connection.sock is not None
    local_ip = connection.sock.getsockname()[0]  # adresse vue par le serveur (pair TCP)
    request_headers = {"Host": BROWSER_HOST, **(headers or {})}
    connection.request(method, path, body=body, headers=request_headers)
    raw = connection.getresponse()
    data = raw.read()
    headers_out = {k.lower(): v for k, v in raw.getheaders()}
    connection.close()
    return Response(raw.status, headers_out, data, local_ip)


def audit_ip(request_id: str) -> str | None:
    with psycopg.connect(
        host=os.environ["RBI_DB_HOST"],
        port=int(os.environ["RBI_DB_PORT"]),
        dbname=os.environ["RBI_DB_NAME"],
        user=os.environ["RBI_DB_OWNER"],
        password=os.environ["RBI_DB_OWNER_PASSWORD"],
        connect_timeout=5,
    ) as conn:
        row = conn.execute(
            "SELECT host(ip_address) FROM audit_auditlog WHERE request_id = %s AND action = 'auth.login'",
            [request_id],
        ).fetchone()
    return row[0] if row else None


def csrf_session() -> tuple[str, str]:
    response = send("GET", "/api/v1/auth/csrf")
    assert response.status == 204
    cookie = response.header("set-cookie")
    token = re.search(r"csrftoken=([^;]+)", cookie)
    assert token, cookie
    return token.group(1), f"csrftoken={token.group(1)}"


def failed_login(**extra_headers: str) -> Response:
    token, cookie = csrf_session()
    return send(
        "POST",
        "/api/v1/auth/login",
        headers={
            "Content-Type": "application/json",
            "Cookie": cookie,
            "X-CSRFToken": token,
            "Origin": f"http://{BROWSER_HOST}",
            **extra_headers,
        },
        body=json.dumps({"email": f"inconnu-{uuid.uuid4().hex[:8]}@demo.rbi.test", "password": "x"}).encode(),
    )


# --- Routage et en-têtes --------------------------------------------------------------------------------


def test_api_is_routed_under_api() -> None:
    response = send("GET", "/api/v1/health/ready")
    assert response.status == 200
    assert response.json()["status"] == "ok"
    assert response.header("x-request-id")


def test_frontend_is_served_with_strict_csp_and_per_request_nonce() -> None:
    first, second = send("GET", "/"), send("GET", "/connexion")
    assert first.status == 200 and "text/html" in first.header("content-type")
    csp = first.header("content-security-policy")
    nonce = re.search(r"'nonce-([0-9a-f]{32})'", csp)
    assert nonce, csp
    for directive in (
        "default-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "img-src 'self'",
    ):
        assert directive in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    html = first.body.decode()
    assert "RBI_CSP_NONCE" not in html
    assert f'nonce="{nonce.group(1)}"' in html  # balises générées par Vite : nonce de CETTE réponse
    assert nonce.group(1) not in second.header("content-security-policy")  # renouvelé à chaque requête
    for name, value in {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "same-origin",
        "cross-origin-opener-policy": "same-origin",
    }.items():
        assert first.header(name) == value
    assert first.header("strict-transport-security") == ""  # HTTP local : jamais de HSTS
    assert first.header("server") == "nginx"  # aucune version (server_tokens off)


def test_api_keeps_its_own_security_headers_through_the_proxy() -> None:
    response = send("GET", "/api/v1/me")
    assert response.status == 401
    assert response.header("content-type") == "application/problem+json"
    assert response.header("content-security-policy") == "default-src 'none'; frame-ancestors 'none'"
    assert response.header("cache-control") == "no-store"


def test_unknown_host_is_refused_without_response() -> None:
    with pytest.raises((http.client.RemoteDisconnected, ConnectionResetError)):
        send("GET", "/", headers={"Host": "rbi.attaquant.test"})


@pytest.mark.parametrize(
    ("method", "path", "body", "status"),
    [
        ("GET", "/api/v1/inexistant", None, 404),
        ("OPTIONS", "/api/v1/health/live", None, 405),  # POST : refusé avant par le CSRF (403)
        ("OPTIONS", "/api/v1/auth/csrf", None, 405),  # route publique DRF : OPTIONS retiré (P2.8)
        ("POST", "/api/v1/auth/login", b"x" * (65 * 1024), 413),
    ],
)
def test_errors_through_the_proxy_are_problem_json(
    method: str, path: str, body: bytes | None, status: int
) -> None:
    response = send(method, path, body=body, headers={"Content-Type": "application/json"} if body else None)
    assert response.status == status
    assert response.header("content-type") == "application/problem+json"
    assert response.json()["status"] == status
    assert b"nginx" not in response.body and b"<html" not in response.body


# --- CSRF derrière le proxy -------------------------------------------------------------------------------


def test_csrf_is_enforced_behind_the_proxy() -> None:
    assert failed_login().status == 401  # jeton et origine valides : la vue répond (identifiants incorrects)
    token, cookie = csrf_session()
    base = {"Content-Type": "application/json", "Cookie": cookie, "Origin": f"http://{BROWSER_HOST}"}
    body = b'{"email": "x@demo.rbi.test", "password": "x"}'
    assert send("POST", "/api/v1/auth/login", headers=base, body=body).status == 403  # sans jeton
    forged = {**base, "X-CSRFToken": "jeton-forge-0123456789abcdef0123456789"}
    assert send("POST", "/api/v1/auth/login", headers=forged, body=body).status == 403
    other_origin = {**base, "X-CSRFToken": token, "Origin": "http://rbi.attaquant.test"}
    assert send("POST", "/api/v1/auth/login", headers=other_origin, body=body).status == 403


# --- Adresse cliente ---------------------------------------------------------------------------------------


def test_real_client_address_is_propagated_and_forged_header_is_replaced() -> None:
    response = failed_login(**{"X-Forwarded-For": FORGED, "X-Real-IP": FORGED, "Forwarded": f"for={FORGED}"})
    assert response.status == 401
    recorded = audit_ip(response.header("x-request-id"))
    assert recorded == response.local_ip  # adresse du client de Nginx (ce conteneur)
    assert recorded not in (FORGED, PROXY_IP)


def test_direct_request_to_the_api_ignores_a_forged_header() -> None:
    token = send("GET", "/api/v1/auth/csrf", host="api", port=8000, headers={"Host": "api"})
    cookie = re.search(r"csrftoken=([^;]+)", token.header("set-cookie"))
    assert cookie
    response = send(
        "POST",
        "/api/v1/auth/login",
        host="api",
        port=8000,
        headers={
            "Host": "api",
            "Content-Type": "application/json",
            "Cookie": f"csrftoken={cookie.group(1)}",
            "X-CSRFToken": cookie.group(1),
            "Referer": "http://api/",
            "X-Forwarded-For": FORGED,
        },
        body=json.dumps({"email": f"inconnu-{uuid.uuid4().hex[:8]}@demo.rbi.test", "password": "x"}).encode(),
    )
    assert response.status == 401
    assert audit_ip(response.header("x-request-id")) == response.local_ip  # pair TCP, pas l'en-tête


def test_proxy_address_is_fixed_and_declared() -> None:
    assert socket.gethostbyname(PROXY.hostname or "proxy") == PROXY_IP


# Dernier test du module : il épuise le quota anonyme de ce conteneur, puis attend la fin de la fenêtre.
def test_anonymous_rate_limit_counts_the_real_client_whatever_the_forged_header() -> None:
    responses = [
        send("GET", "/api/v1/auth/csrf", headers={"X-Forwarded-For": f"198.51.100.{n % 250}"})
        for n in range(130)
    ]
    statuses = [r.status for r in responses]
    assert 429 in statuses, "chaque en-tête forgé aurait obtenu son propre quota"
    assert statuses.count(204) <= 120
    throttled = next(r for r in responses if r.status == 429)
    assert throttled.header("content-type") == "application/problem+json"
    wait = int(throttled.header("retry-after") or "60")
    assert 0 < wait <= 60
    time.sleep(
        wait + 1
    )  # quota du client réel rétabli : la fenêtre est la sienne, pas celle d'une adresse forgée
    assert send("GET", "/api/v1/auth/csrf").status == 204
