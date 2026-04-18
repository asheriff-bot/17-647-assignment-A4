"""
Web BFF — A1/A2: proxy to Internal ALB (:3000); JWT then X-Client-Type; /status public.
"""
import os
import requests
from flask import Flask, Response, request

import sys

_app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _app_dir)
sys.path.insert(0, os.path.join(_app_dir, ".."))
from shared.bff_auth import require_web_bff
from shared.bff_book_transform import (
    apply_book_genre_after_request,
    transform_book_response,
    transform_web_client_book_response,
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

# Book POST may call LLM synchronously; allow headroom
PROXY_TIMEOUT = int(os.environ.get("BFF_PROXY_TIMEOUT", "120"))


def _backend_base_for(path: str, method: str) -> str:
    m = (method or "GET").upper()
    if path.startswith("/books"):
        if m in ("POST", "PUT"):
            return (BOOK_CMD_BASE or BACKEND_BASE).rstrip("/")
        return (BOOK_QUERY_BASE or BACKEND_BASE).rstrip("/")
    return BACKEND_BASE


def proxy_to_backend(path: str, method: str = "GET", **kwargs):
    base = _backend_base_for(path, method)
    m = (method or "GET").upper()
    if path.startswith("/books") and m in ("POST", "PUT"):
        path = "/cmd" + path
    url = f"{base}{path}"
    if request.query_string:
        url += "?" + request.query_string.decode()

    m = (method or "GET").upper()

    # Never forward these to internal services / Internal ALB (path routing only).
    # X-Client-Type MUST be forwarded so book_service can emit genre string vs int 3 at the source.
    skip = {
        "host",
        "authorization",
        "content-length",
        "transfer-encoding",
    }
    headers = {k: v for k, v in request.headers if k.lower() not in skip}

    # Same as mobile BFF: book service maps non-fiction → genre 3 when this is set.
    # Needed when External ALB sends iOS/Android traffic to Web BFF targets.
    xt = (request.headers.get("X-Client-Type") or "").strip().lower()
    if xt in ("ios", "android"):
        headers["X-A2-Mobile-BFF"] = "1"

    if m in ("GET", "HEAD"):
        headers = {
            k: v
            for k, v in headers.items()
            if k.lower() not in ("content-type", "content-length", "transfer-encoding")
        }
    else:
        # POST/PUT/PATCH/DELETE: always pass body bytes; requests sets Content-Length
        kwargs["data"] = request.get_data()

    # Avoid compressed bodies from backends/ALB — BFF must json-parse responses for mobile genre rewrite.
    headers["Accept-Encoding"] = "identity"

    try:
        r = requests.request(m, url, timeout=PROXY_TIMEOUT, headers=headers, **kwargs)
        return r.content, r.status_code, dict(r.headers)
    except requests.RequestException:
        return b"Bad Gateway", 502, {}


def build_response(body, status_code, headers, apply_book=False):
    # Book service emits genre int 3 for non-fiction on single-book JSON; Web BFF maps 3 -> 'non-fiction' for Web.
    if body and apply_book:
        skip_write_echo = request.method in ("POST", "PUT") and status_code in (200, 201)
        if not skip_write_echo:
            xt = (request.headers.get("X-Client-Type") or "").strip().lower()
            if xt == "web":
                body = transform_web_client_book_response(body)
            elif xt in ("ios", "android"):
                body = transform_book_response(body)
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
@require_web_bff
def customers():
    body, status_code, headers = proxy_to_backend("/customers", method=request.method)
    return build_response(body, status_code, headers)


@app.route("/customers/<path:subpath>", methods=["GET"])
@require_web_bff
def customer_by_id(subpath):
    body, status_code, headers = proxy_to_backend(f"/customers/{subpath}")
    return build_response(body, status_code, headers)


@app.route("/books", methods=["GET", "POST"])
@require_web_bff
def books():
    body, status_code, headers = proxy_to_backend("/books", method=request.method)
    return build_response(body, status_code, headers, apply_book=True)


@app.route("/books/<path:subpath>", methods=["GET", "PUT"])
@require_web_bff
def book_subpath(subpath):
    body, status_code, headers = proxy_to_backend(f"/books/{subpath}", method=request.method)
    return build_response(body, status_code, headers, apply_book=True)


@app.after_request
def _after_book_genre_web(resp):
    return apply_book_genre_after_request(resp, web_bff=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)
