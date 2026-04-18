"""
Customer microservice — A1 REST + A2 deployment (port 3000).
"""
from __future__ import annotations

import os
import re
import json
from typing import Any, Optional
from urllib.parse import unquote

from kafka import KafkaProducer
import pymysql
import pymysql.err
from flask import Flask, Response, jsonify, request

app = Flask(__name__)
app.url_map.strict_slashes = False

def _db_host() -> str:
    return (os.environ.get("DB_HOST") or os.environ.get("DB_ENDPOINT") or "localhost").strip()


DB_CONFIG = {
    "host": _db_host(),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "customers_db"),
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": True,
}

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
# Path segment must be a plain integer id (invalid shapes → 400 per A1)
_CUSTOMER_PATH_ID = re.compile(r"^[+-]?\d+$")


def get_db():
    return pymysql.connect(**DB_CONFIG)


def _kafka_topic() -> str:
    andrew_id = (os.environ.get("ANDREW_ID") or "").strip()
    if not andrew_id:
        raise ValueError("ANDREW_ID is required for topic <ANDREW_ID>.customer.evt")
    return f"{andrew_id}.customer.evt"


def _kafka_security_kwargs() -> dict[str, Any]:
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


def _publish_customer_registered(evt: dict) -> None:
    brokers = (os.environ.get("KAFKA_BROKERS") or "").strip()
    if not brokers:
        return
    try:
        topic = _kafka_topic()
    except ValueError:
        return
    producer = KafkaProducer(
        bootstrap_servers=[b.strip() for b in brokers.split(",") if b.strip()],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        **_kafka_security_kwargs(),
    )
    try:
        producer.send(topic, evt).get(timeout=5)
        producer.flush(timeout=5)
    finally:
        producer.close(timeout=5)


def _read_json_dict():
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else None


def row_to_customer_json(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "userId": row["userId"],
        "name": row["name"],
        "phone": row["phone"],
        "address": row["address"],
        "address2": row["address2"] if row.get("address2") is not None else "",
        "city": row["city"],
        "state": row["state"],
        "zipcode": row["zipcode"],
    }


def valid_email(s: str) -> bool:
    return bool(s and EMAIL_RE.match(s))


def _canonical_user_id(s: str) -> str:
    """Strip + lowercase so duplicate checks match A1 / shared RDS (same email, different casing)."""
    return str(s).strip().lower()


def get_user_id_query_param() -> Optional[str]:
    """
    Read userId from the raw query string using unquote (not form-style unquote_plus).
    Werkzeug/request.args treats '+' as space, which breaks emails like user+tag@domain.com.
    """
    raw = request.query_string.decode("utf-8", errors="replace")
    if not raw:
        return None
    for segment in raw.split("&"):
        if not segment or "=" not in segment:
            continue
        key, _, val = segment.partition("=")
        key_dec = unquote(key.strip(), errors="replace").strip()
        if key_dec.lower() in ("userid", "user_id"):
            return unquote(val, errors="replace").strip()
    return None


def normalize_customer_post_body(data: dict) -> None:
    """Map alternate JSON keys (snake_case, PascalCase) to A1 canonical names."""
    aliases = (
        ("userId", ("user_id", "UserId", "USERID")),
        ("name", ("Name",)),
        ("phone", ("Phone",)),
        ("address", ("Address",)),
        ("address2", ("Address2",)),
        ("city", ("City",)),
        ("state", ("State",)),
        ("zipcode", ("zipCode", "Zipcode", "ZipCode", "ZIPCODE")),
    )
    for canonical, alts in aliases:
        if canonical not in data:
            for a in alts:
                if a in data:
                    data[canonical] = data[a]
                    break


def _non_empty_scalar(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str) and not v.strip():
        return False
    return True


def post_customer_required(data: dict) -> bool:
    if not data:
        return False
    mandatory = ["userId", "name", "phone", "address", "city", "state", "zipcode"]
    for k in mandatory:
        if k not in data:
            return False
        if not _non_empty_scalar(data.get(k)):
            return False
    return True


@app.route("/status", methods=["GET"])
def status():
    return Response("OK", status=200, mimetype="text/plain")


@app.route("/customers", methods=["GET"])
def list_or_query_customers():
    # Do not fall back to request.args.get("userId") — Werkzeug treats '+' as space and breaks emails like a+b@x.com.
    user_id = get_user_id_query_param()
    if user_id is not None:
        user_id = _canonical_user_id(user_id)
    if user_id is None:
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, userId, name, phone, address, address2, city, state, zipcode FROM customers"
                )
                rows = cur.fetchall()
            conn.close()
            return jsonify([row_to_customer_json(r) for r in rows]), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    if not valid_email(user_id):
        return jsonify({}), 400
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, userId, name, phone, address, address2, city, state, zipcode FROM customers WHERE userId = %s",
                (user_id,),
            )
            row = cur.fetchone()
        conn.close()
        if not row:
            return jsonify({}), 404
        return jsonify(row_to_customer_json(row)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    s = str(customer_id).strip()
    if not _CUSTOMER_PATH_ID.match(s):
        return jsonify({}), 400
    try:
        cid = int(s, 10)
    except ValueError:
        return jsonify({}), 400
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, userId, name, phone, address, address2, city, state, zipcode FROM customers WHERE id = %s",
                (cid,),
            )
            row = cur.fetchone()
        conn.close()
        if not row:
            return jsonify({}), 404
        return jsonify(row_to_customer_json(row)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/customers", methods=["POST"])
def create_customer():
    data = _read_json_dict()
    if data is None:
        return jsonify({}), 400
    normalize_customer_post_body(data)
    if not post_customer_required(data):
        return jsonify({}), 400
    data["userId"] = _canonical_user_id(data["userId"])
    if not valid_email(data.get("userId", "")):
        return jsonify({}), 400
    st = (data.get("state") or "").strip().upper()
    if st not in US_STATES:
        return jsonify({}), 400

    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM customers WHERE userId = %s",
                (data["userId"],),
            )
            if cur.fetchone():
                conn.close()
                return jsonify({"message": "This user ID already exists in the system."}), 422
            cur.execute(
                """INSERT INTO customers (userId, name, phone, address, address2, city, state, zipcode)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    data["userId"],
                    data["name"],
                    data["phone"],
                    data["address"],
                    data.get("address2") if data.get("address2") is not None else "",
                    data["city"],
                    st,
                    data["zipcode"],
                ),
            )
            cid = cur.lastrowid
        conn.close()
        body = row_to_customer_json(
            {
                "id": cid,
                "userId": data["userId"],
                "name": data["name"],
                "phone": data["phone"],
                "address": data["address"],
                "address2": data.get("address2") or "",
                "city": data["city"],
                "state": st,
                "zipcode": data["zipcode"],
            }
        )
        resp = jsonify(body)
        resp.status_code = 201
        resp.headers["Location"] = f"/customers/{cid}"
        try:
            _publish_customer_registered(body)
        except Exception:
            # Customer creation succeeds even if async notification cannot be sent now.
            pass
        return resp
    except pymysql.err.IntegrityError as e:
        # 1062: duplicate entry (e.g. race on userId unique key)
        if getattr(e, "args", (None,))[0] == 1062:
            return jsonify({"message": "This user ID already exists in the system."}), 422
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
