"""Redis 7, stockage objet S3 et Mailpit : disponibilité, authentification, aller-retour réel."""

from __future__ import annotations

import json
import smtplib
import urllib.error
import urllib.request
import uuid
from email.message import EmailMessage
from typing import Any, cast
from urllib.parse import quote, urlsplit, urlunsplit

import boto3
import pytest
import redis
from botocore.client import Config
from botocore.exceptions import ClientError

from .support import env

# --- Redis ------------------------------------------------------------------


def test_redis_version_and_persistence() -> None:
    client = redis.Redis.from_url(env("RBI_REDIS_URL"))
    info = cast(dict[str, Any], client.info("server"))
    assert str(info["redis_version"]).startswith("7.")
    assert client.config_get("appendonly") == {"appendonly": "yes"}
    # Broker Celery : jamais d'éviction silencieuse de messages.
    assert client.config_get("maxmemory-policy") == {"maxmemory-policy": "noeviction"}


def test_redis_requires_password() -> None:
    parts = urlsplit(env("RBI_REDIS_URL"))
    anonymous = urlunsplit((parts.scheme, f"{parts.hostname}:{parts.port}", parts.path, "", ""))
    with pytest.raises(redis.exceptions.AuthenticationError):
        redis.Redis.from_url(anonymous).ping()


def test_redis_round_trip() -> None:
    client = redis.Redis.from_url(env("RBI_REDIS_URL"))
    key = f"rbi:infra-check:{uuid.uuid4().hex}"
    assert client.set(key, "ok", ex=30)
    assert client.get(key) == b"ok"
    client.delete(key)


# --- Stockage objet S3 ------------------------------------------------------


def s3_client(access_key: str | None = None, secret_key: str | None = None):  # type: ignore[no-untyped-def]
    return boto3.client(
        "s3",
        endpoint_url=env("RBI_S3_ENDPOINT_URL"),
        aws_access_key_id=access_key or env("RBI_S3_ACCESS_KEY"),
        aws_secret_access_key=secret_key or env("RBI_S3_SECRET_KEY"),
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def test_s3_bucket_exists_and_round_trip() -> None:
    client = s3_client()
    bucket = env("RBI_S3_BUCKET")
    client.head_bucket(Bucket=bucket)
    # Préfixe par organisme (§12.3, niveau 4) — illustré ici avec un identifiant fictif.
    key = f"org/{uuid.uuid4()}/infra-check/{uuid.uuid4().hex}.txt"
    client.put_object(Bucket=bucket, Key=key, Body=b"rbi", ContentType="text/plain")
    try:
        assert client.get_object(Bucket=bucket, Key=key)["Body"].read() == b"rbi"
        url = client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=60)
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - URL interne signée
            assert response.read() == b"rbi"
    finally:
        client.delete_object(Bucket=bucket, Key=key)


def test_s3_rejects_anonymous_access() -> None:
    url = f"{env('RBI_S3_ENDPOINT_URL')}/{env('RBI_S3_BUCKET')}"
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(url, timeout=5)  # noqa: S310
    assert excinfo.value.code == 403


def test_s3_rejects_wrong_credentials() -> None:
    client = s3_client("wrong-access-key", "wrong-secret-key-000000")
    with pytest.raises(ClientError):
        client.list_objects_v2(Bucket=env("RBI_S3_BUCKET"))


# --- Mailpit ----------------------------------------------------------------


def test_mailpit_captures_outgoing_mail() -> None:
    subject = f"RBI infra check {uuid.uuid4().hex}"
    message = EmailMessage()
    message["From"] = "noreply@rbi.test"
    message["To"] = "destinataire@demo-a.rbi.test"
    message["Subject"] = subject
    message.set_content("Message de vérification — données fictives.")
    with smtplib.SMTP(env("RBI_SMTP_HOST"), int(env("RBI_SMTP_PORT")), timeout=5) as smtp:
        smtp.send_message(message)

    api = env("RBI_MAILPIT_API_URL")
    query = quote(f'subject:"{subject}"')
    with urllib.request.urlopen(f"{api}/api/v1/search?query={query}", timeout=5) as response:  # noqa: S310
        found = json.load(response)
    assert found["messages_count"] == 1
    message_id = found["messages"][0]["ID"]
    delete = urllib.request.Request(  # noqa: S310 - API Mailpit interne
        f"{api}/api/v1/messages",
        data=json.dumps({"IDs": [message_id]}).encode(),
        method="DELETE",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(delete, timeout=5):  # noqa: S310
        pass
