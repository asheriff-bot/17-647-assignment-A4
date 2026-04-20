"""
Mobile BFF — A2: JWT then X-Client-Type; genre non-fiction → 3; strip address fields.
"""
import json
import os
from urllib.parse import unquote

import requests
from flask import Flask, Response, jsonify, request

import sys

_app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _app_dir)
sys.path.insert(0, os.path.join(_app_dir, ".."))
from shared.bff_auth import require_mobile_bff
from shared.bff_book_transform import (
    apply_book_genre_after_request,
    transform_book_response,
)
from shared.bff_response import absolute_location_header

app = Flask(__name__)
app.url_map.strict_slashes = False
_backend = (os.environ.get("URL_BASE_BACKEND_SERVICES") or "").strip()
BACKEND_BASE = (_backend or "http://localhost:3000").rstrip("/")
BOOK_CMD_BASE = (
    os.environ.get("BOOK_COMMAND_SERVICE_URL") or os.environ.get("URL_BOOK_COMMAND") or ""
).strip().rstrip("/")
BOOK_QUERY_BASE = (
    os.environ.get("BOOK_QUERY_SERVICE_URL") or os.environ.get("URL_BOOK_QUERY") or ""
).strip().rstrip("/")

PROXY_TIMEOUT = int(os.environ.get("BFF_PROXY_TIMEOUT", "120"))

CUSTOMER_ATTRS_TO_REMOVE = {"address", "address2", "city", "state", "zipcode"}


def _backend_base_for(path: str, method: str) -> str:
    if path.startswith("/cmd/"):
        return (BOOK_CMD_BASE or BACKEND_BASE).rstrip("/")
    if path.startswith("/books"):
        return (BOOK_QUERY_BASE or BACKEND_BASE).rstrip("/")
    return BACKEND_BASE


def proxy_to_backend(path: str, method: str = "GET", **kwargs):
    base = _backend_base_for(path, method)
    url = f"{base}{path}"
    if request.query_string:
        url += "?" + request.query_string.decode()

    m = (method or "GET").upper()
    # Forward X-Client-Type so book_service emits genre int 3 for iOS/Android (not Web string).
    skip = {
        "host",
        "authorization",
        "content-length",
        "transfer-encoding",
    }
    headers = {k: v for k, v in request.headers if k.lower() not in skip}
    # Book service maps non-fiction -> 3 when this is set (survives even if BFF JSON rewrite fails).
    headers["X-A2-Mobile-BFF"] = "1"

    if m in ("GET", "HEAD"):
        headers = {
            k: v
            for k, v in headers.items()
            if k.lower() not in ("content-type", "content-length", "transfer-encoding")
        }
    else:
        kwargs["data"] = request.get_data()

    # Avoid compressed bodies — mobile BFF must json-parse responses for genre non-fiction → 3.
    headers["Accept-Encoding"] = "identity"

    try:
        r = requests.request(m, url, timeout=PROXY_TIMEOUT, headers=headers, **kwargs)
        return r.content, r.status_code, dict(r.headers)
    except requests.RequestException:
        return b"Bad Gateway", 502, {}


def transform_customer_response(data: bytes) -> bytes:
    try:
        obj = json.loads(data.decode("utf-8"))
        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    for k in CUSTOMER_ATTRS_TO_REMOVE:
                        item.pop(k, None)
        elif isinstance(obj, dict):
            for k in CUSTOMER_ATTRS_TO_REMOVE:
                obj.pop(k, None)
        return json.dumps(obj).encode("utf-8")
    except Exception:
        return data


def _path_norm() -> str:
    return (request.path or "").rstrip("/") or "/"


def _query_string_has_userid_param() -> bool:
    """
    True if ?userId= or ?user_id= is present (parse raw query; Werkzeug treats '+' as space).
    Matches customer_service behavior for emails like user+tag@domain.com.
    """
    raw = request.query_string.decode("utf-8", errors="replace")
    if not raw:
        return False
    for segment in raw.split("&"):
        if not segment or "=" not in segment:
            continue
        key, _, _ = segment.partition("=")
        k = unquote(key.strip(), errors="replace").strip().lower()
        if k in ("userid", "user_id"):
            return True
    return False


def _a2_should_transform_customer_get() -> bool:
    """Single-customer GET: by path or ?userId= (not GET /customers list)."""
    p = _path_norm()
    if p == "/customers" and _query_string_has_userid_param():
        return True
    return p.startswith("/customers/")


def build_response(body, status_code, headers, apply_book=False, apply_customer=False):
    # Redundant with book service X-A2-Mobile-BFF mapping; keeps responses correct if header stripped.
    if body and apply_book:
        if not (request.method in ("POST", "PUT") and status_code in (200, 201)):
            body = transform_book_response(body)
    if body and request.method == "GET" and status_code == 200:
        if apply_customer and _a2_should_transform_customer_get():
            body = transform_customer_response(body)
    resp = Response(body, status=status_code)
    for k, v in headers.items():
        lk = k.lower()
        if lk == "location":
            resp.headers[k] = absolute_location_header(v)
        elif lk in ("content-type", "content-length"):
            resp.headers[k] = v
    if body is not None:
        blen = len(body) if isinstance(body, (bytes, bytearray)) else 0
        resp.headers["Content-Length"] = str(blen)
    return resp


@app.route("/status", methods=["GET"])
def status():
    return Response("OK", status=200, mimetype="text/plain")


@app.route("/customers", methods=["GET", "POST"])
@require_mobile_bff
def customers():
    body, status_code, headers = proxy_to_backend("/customers", method=request.method)
    return build_response(
        body, status_code, headers, apply_book=False, apply_customer=True
    )


@app.route("/customers/<path:subpath>", methods=["GET"])
@require_mobile_bff
def customer_by_id(subpath):
    body, status_code, headers = proxy_to_backend(f"/customers/{subpath}")
    return build_response(
        body, status_code, headers, apply_book=False, apply_customer=True
    )


@app.route("/cmd/books", methods=["POST"])
@require_mobile_bff
def cmd_books_post():
    body, status_code, headers = proxy_to_backend("/cmd/books", method="POST")
    return build_response(body, status_code, headers, apply_book=True, apply_customer=False)


@app.route("/cmd/books/<path:subpath>", methods=["PUT"])
@require_mobile_bff
def cmd_books_put(subpath):
    body, status_code, headers = proxy_to_backend(f"/cmd/books/{subpath}", method="PUT")
    return build_response(body, status_code, headers, apply_book=True, apply_customer=False)


@app.route("/books", methods=["GET", "POST"])
@require_mobile_bff
def books():
    if request.method == "POST":
        return jsonify({}), 405
    body, status_code, headers = proxy_to_backend("/books", method="GET")
    return build_response(body, status_code, headers, apply_book=True, apply_customer=False)


@app.route("/books/<path:subpath>", methods=["GET", "PUT"])
@require_mobile_bff
def book_subpath(subpath):
    if request.method == "PUT":
        return jsonify({}), 405
    body, status_code, headers = proxy_to_backend(f"/books/{subpath}", method="GET")
    return build_response(body, status_code, headers, apply_book=True, apply_customer=False)


@app.after_request
def _after_book_genre_mobile(resp):
    return apply_book_genre_after_request(resp, web_bff=False)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)
