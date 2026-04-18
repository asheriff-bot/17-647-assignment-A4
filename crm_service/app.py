"""
CRM async service — A3 Task 4.

Consumes Kafka topic ``<ANDREW_ID>.customer.evt``, parses Customer Registered
events (same JSON as POST /customers response), and sends SMTP email per spec.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import sys
import time
from email.message import EmailMessage
from typing import Any

from kafka import KafkaConsumer

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOG = logging.getLogger("crm_service")


def _topic() -> str:
    andrew_id = (os.environ.get("ANDREW_ID") or "").strip()
    if not andrew_id:
        raise RuntimeError("ANDREW_ID must be set (Kafka topic is <ANDREW_ID>.customer.evt).")
    return f"{andrew_id}.customer.evt"


def _kafka_security_kwargs() -> dict[str, Any]:
    """Optional TLS/SASL for brokers (e.g. MSK or secured course clusters)."""
    out: dict[str, Any] = {}
    proto = (os.environ.get("KAFKA_SECURITY_PROTOCOL") or "PLAINTEXT").strip().upper()
    if proto:
        out["security_protocol"] = proto
    ca = (os.environ.get("KAFKA_SSL_CAFILE") or "").strip()
    if ca:
        out["ssl_cafile"] = ca
    mech = (os.environ.get("KAFKA_SASL_MECHANISM") or "").strip()
    user = (os.environ.get("KAFKA_SASL_USERNAME") or "").strip()
    pwd = (os.environ.get("KAFKA_SASL_PASSWORD") or "").strip()
    if mech and user:
        out["sasl_mechanism"] = mech
        out["sasl_plain_username"] = user
        out["sasl_plain_password"] = pwd
    return out


def _deserialize_event(raw: bytes | None) -> dict[str, Any]:
    """Parse Kafka message value into a customer dict (A3: same shape as REST response)."""
    if not raw:
        return {}
    try:
        text = raw.decode("utf-8")
    except Exception:
        return {}
    try:
        obj = json.loads(text)
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _consumer() -> KafkaConsumer:
    brokers = (os.environ.get("KAFKA_BROKERS") or "").strip()
    if not brokers:
        raise RuntimeError("KAFKA_BROKERS must be set (comma-separated broker list).")
    topic = _topic()
    extra = _kafka_security_kwargs()
    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=[b.strip() for b in brokers.split(",") if b.strip()],
        auto_offset_reset="earliest",
        group_id=(os.environ.get("CRM_CONSUMER_GROUP") or "crm-service"),
        enable_auto_commit=False,
        value_deserializer=lambda m: _deserialize_event(m),
        **extra,
    )
    LOG.info("Subscribed to topic %s brokers=%s", topic, brokers)
    return consumer


def _activation_email_body(customer_name: str, andrew_id: str) -> str:
    """Exact assignment wording (A3 Task 4)."""
    return (
        f"Dear {customer_name},\n"
        f"Welcome to the Book store created by {andrew_id}.\n"
        "Exceptionally this time we won't ask you to click a link to activate your account.\n"
    )


def _recipient_from_event(customer: dict[str, Any]) -> str:
    """To-address for activation mail (customer email from Kafka JSON)."""
    for key in ("userId", "user_id", "email", "Email"):
        v = customer.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _send_email(customer: dict[str, Any]) -> None:
    to_addr = _recipient_from_event(customer)
    if not to_addr:
        LOG.warning("Skip email: no recipient (userId/email) in event keys=%s", list(customer.keys()))
        return
    customer_name = (customer.get("name") or "Customer").strip() or "Customer"
    andrew_id = (os.environ.get("ANDREW_ID") or "").strip()
    if not andrew_id:
        LOG.warning("Skip email: ANDREW_ID not set")
        return
    sender = (os.environ.get("SMTP_SENDER_EMAIL") or os.environ.get("SMTP_USERNAME") or "").strip()
    if not sender:
        LOG.warning("Skip email: set SMTP_SENDER_EMAIL or SMTP_USERNAME")
        return
    host = (os.environ.get("SMTP_HOST") or "").strip()
    if not host:
        LOG.warning("Skip email: SMTP_HOST not set")
        return

    msg = EmailMessage()
    msg["Subject"] = "Activate your book store account"
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(_activation_email_body(customer_name, andrew_id), charset="utf-8")

    port = int(os.environ.get("SMTP_PORT", "587"))
    username = (os.environ.get("SMTP_USERNAME") or "").strip()
    password = (os.environ.get("SMTP_PASSWORD") or "").strip()
    use_tls = (os.environ.get("SMTP_STARTTLS", "true").strip().lower() in ("1", "true", "yes"))

    if "gmail" in host.lower() and username and sender.lower() != username.lower():
        LOG.warning(
            "Gmail usually requires From (%s) to match SMTP_USERNAME (%s); delivery may fail.",
            sender,
            username,
        )

    with smtplib.SMTP(host=host, port=port, timeout=60) as server:
        if use_tls:
            server.starttls()
        if username:
            server.login(username, password)
        server.send_message(msg)
    LOG.info("Sent activation email to %s from %s", to_addr, sender)


def main() -> None:
    try:
        _topic()
    except RuntimeError as e:
        LOG.error("%s", e)
        sys.exit(1)
    backoff = 5
    while True:
        try:
            consumer = _consumer()
            backoff = 5
            for message in consumer:
                payload = message.value if isinstance(message.value, dict) else {}
                try:
                    _send_email(payload)
                    consumer.commit()
                except Exception as ex:
                    LOG.exception("Email send failed (offset not committed; will retry): %s", ex)
                    time.sleep(2)
        except Exception as ex:
            LOG.exception("Kafka consumer error, retry in %ss: %s", backoff, ex)
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)


if __name__ == "__main__":
    main()
