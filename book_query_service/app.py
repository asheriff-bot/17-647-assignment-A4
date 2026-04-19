"""
Book query microservice — A4 CQRS (reads from MongoDB only; related-books uses external API).
GET /books, GET /books?keyword=, GET /books/<ISBN>, GET /books/isbn/<ISBN>, GET /books/<ISBN>/related-books
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
import socket
import threading
import time
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Any, Optional

import pymongo
from pymongo.errors import OperationFailure
import requests
from flask import Flask, Response, has_request_context, jsonify, request

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

_GENRE_NONFICTION_RE = re.compile(
    r"[\s\-_\u2010-\u2015\u00AD\u200b\u200c\u200d\ufeff\u2060]+"
)


def _stored_genre_is_nonfiction(gv: Any) -> bool:
    if gv is None:
        return False
    if isinstance(gv, bytes):
        s = gv.decode("utf-8", errors="replace")
    else:
        s = str(gv).strip()
    s = _GENRE_NONFICTION_RE.sub("", s.lower())
    return s == "nonfiction"


CIRCUIT_OPEN_SECONDS = int(os.environ.get("RELATED_BOOKS_CIRCUIT_OPEN_SECONDS", "60"))
RELATED_BOOKS_TIMEOUT_SECONDS = int(os.environ.get("RELATED_BOOKS_TIMEOUT_SECONDS", "3"))
RECOMMENDATION_BASE_URL = (
    os.environ.get("RECOMMENDATION_SERVICE_URL", "").strip().rstrip("/")
)
_STATE_FILE = Path(
    os.environ.get("CIRCUIT_STATE_FILE", "/tmp/related_books_circuit_state.json")
)
_RELATED_BOOKS_CIRCUIT_LOCK = threading.Lock()


def _mongo_uri() -> str:
    return (os.environ.get("MONGO_URI") or os.environ.get("MONGODB_URI") or "").strip()


def _mongo_collection_name() -> str:
    aid = (os.environ.get("ANDREW_ID") or os.environ.get("ANDREWID") or "local").strip()
    return os.environ.get("MONGO_COLLECTION") or f"books_{aid}"


_mongo_client: pymongo.MongoClient | None = None


def get_mongo_collection():
    global _mongo_client
    uri = _mongo_uri()
    if not uri:
        raise RuntimeError("MONGO_URI (or MONGODB_URI) is required for book query service")
    if _mongo_client is None:
        tls_ca = os.environ.get("MONGO_TLS_CA_FILE") or os.environ.get("DOCDB_TLS_CA_FILE")
        kwargs: dict = {}
        if tls_ca and os.path.isfile(tls_ca):
            kwargs["tls"] = True
            kwargs["tlsCAFile"] = tls_ca
        _mongo_client = pymongo.MongoClient(uri, **kwargs)
    db_name = os.environ.get("MONGO_DB_NAME") or os.environ.get("MONGO_DATABASE") or "books"
    db = _mongo_client[db_name]
    return db[_mongo_collection_name()]


def _load_circuit_state() -> dict:
    try:
        if not _STATE_FILE.exists():
            return {"state": "closed", "opened_at": 0}
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"state": "closed", "opened_at": 0}
        return {
            "state": "open" if data.get("state") == "open" else "closed",
            "opened_at": int(data.get("opened_at") or 0),
        }
    except Exception:
        return {"state": "closed", "opened_at": 0}


def _save_circuit_state(state: str, opened_at: int) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps({"state": state, "opened_at": int(opened_at)}),
            encoding="utf-8",
        )
    except Exception:
        pass


def _set_circuit_open(now_ts: int) -> None:
    _save_circuit_state("open", now_ts)


def _set_circuit_closed() -> None:
    _save_circuit_state("closed", 0)


def _parse_related_books_body(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("related_books", "relatedBooks", "books", "recommendations", "data"):
            v = payload.get(key)
            if isinstance(v, list):
                return v
    return []


def _to_assignment_related_book_row(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    isbn_v = item.get("ISBN") if item.get("ISBN") is not None else item.get("isbn")
    title_v = item.get("title")
    author_v = item.get("Author") if item.get("Author") is not None else item.get("authors")
    if isbn_v is None and title_v is None and author_v is None:
        return None
    out: dict = {}
    if isbn_v is not None:
        out["ISBN"] = format_isbn_for_json(str(isbn_v).strip())
    if title_v is not None:
        out["title"] = title_v
    if author_v is not None:
        out["Author"] = author_v
    return out if out else None


def _normalize_related_books_response(raw_list: list) -> list:
    out: list = []
    for it in raw_list:
        row = _to_assignment_related_book_row(it)
        if row:
            out.append(row)
    return out


def _recommendation_urls(isbn: str) -> list[str]:
    if not RECOMMENDATION_BASE_URL:
        return []
    path_template = os.environ.get("RECOMMENDATION_PATH_TEMPLATE", "").strip()
    if path_template:
        return [f"{RECOMMENDATION_BASE_URL}{path_template.format(isbn=isbn)}"]
    return [
        f"{RECOMMENDATION_BASE_URL}/recommended-titles/isbn/{isbn}",
        f"{RECOMMENDATION_BASE_URL}/books/{isbn}/related-books",
        f"{RECOMMENDATION_BASE_URL}/recommendations/{isbn}",
        f"{RECOMMENDATION_BASE_URL}/related-books/{isbn}",
    ]


def _recommendation_http_get(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(
            req, timeout=float(RELATED_BOOKS_TIMEOUT_SECONDS)
        ) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return e.code, body
    except TimeoutError:
        raise requests.Timeout()
    except socket.timeout:
        raise requests.Timeout()
    except urllib.error.URLError:
        raise requests.Timeout()


def _fetch_related_books_external(isbn: str) -> tuple[int, list]:
    urls = _recommendation_urls(isbn)
    if not urls:
        raise requests.Timeout()
    last_status = 204
    for url in urls:
        status, raw = _recommendation_http_get(url)
        if status == 204:
            return 204, []
        if status == 200:
            try:
                payload = json.loads(raw.decode("utf-8"))
                return 200, _parse_related_books_body(payload)
            except Exception:
                return 200, []
        last_status = status
    if last_status == 404:
        return 204, []
    raise requests.HTTPError(f"Unexpected status from recommendation service: {last_status}")


def _json_price(row_price) -> float | int:
    if row_price is None:
        return None
    d = Decimal(str(row_price))
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def _request_client_type_lower() -> str:
    try:
        if not has_request_context():
            return ""
        return (request.headers.get("X-Client-Type") or "").strip().lower()
    except Exception:
        return ""


def _mobile_bff_genre_int_header() -> bool:
    try:
        if not has_request_context():
            return False
        return (request.headers.get("X-A2-Mobile-BFF") or "").strip() == "1"
    except Exception:
        return False


def _genre_for_json_response(genre_value: Any) -> Any:
    if isinstance(genre_value, bool):
        return genre_value
    if isinstance(genre_value, (int, float)):
        try:
            if int(genre_value) == 3:
                return 3
        except (ValueError, OverflowError):
            pass
        return genre_value
    if isinstance(genre_value, str) and genre_value.strip() == "3":
        return 3
    if _stored_genre_is_nonfiction(genre_value):
        if _mobile_bff_genre_int_header():
            return 3
        if _request_client_type_lower() == "web":
            return "non-fiction"
        return 3
    return genre_value


def format_isbn_for_json(isbn_stored: str) -> str:
    if not isbn_stored:
        return isbn_stored
    s = str(isbn_stored).strip()
    if "-" in s:
        return s
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) == 13 and not digits.startswith(("978", "979")):
        return f"{digits[:3]}-{digits[3:]}"
    return s


def row_to_book_json(row: dict, include_summary: bool) -> dict:
    out = {
        "ISBN": format_isbn_for_json(row["isbn"]),
        "title": row["title"],
        "Author": row["author"],
        "description": row["description"],
        "genre": _genre_for_json_response(row["genre"]),
        "price": _json_price(row["price"]),
        "quantity": int(row["quantity"]),
    }
    if include_summary:
        out["summary"] = row.get("summary") or ""
    return out


def normalize_isbn_value(v: Any) -> Optional[str]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        s = str(v)
    elif isinstance(v, float):
        if not (math.isfinite(v) and v.is_integer()):
            return None
        s = str(int(v))
    else:
        s = str(v).strip()
        if not s:
            return None
    digits = "".join(c for c in s if c.isdigit())
    return digits if digits else None


def mongo_doc_to_row(doc: dict) -> dict:
    """Map Mongo book doc to SQL-shaped row for row_to_book_json (supports A4 REST-shaped docs or legacy SQL keys)."""
    isbn = doc.get("isbn") if doc.get("isbn") is not None else doc.get("ISBN")
    author = doc.get("author") if doc.get("author") is not None else doc.get("Author")
    return {
        "isbn": isbn,
        "title": doc.get("title"),
        "author": author,
        "description": doc.get("description"),
        "genre": doc.get("genre"),
        "price": doc.get("price"),
        "quantity": doc.get("quantity"),
        "summary": doc.get("summary"),
    }


def fetch_book_row_from_mongo(isbn_canonical: str) -> Optional[dict]:
    coll = get_mongo_collection()
    doc = coll.find_one({"isbn_canonical": isbn_canonical})
    if doc:
        return mongo_doc_to_row(doc)
    for doc in coll.find({}):
        row = mongo_doc_to_row(doc)
        if normalize_isbn_value(str(row.get("isbn") or "")) == isbn_canonical:
            return row
    return None


_KEYWORD_RE = re.compile(r"^[a-zA-Z]+$")


@app.route("/status", methods=["GET"])
def status():
    return Response("OK", status=200, mimetype="text/plain")


@app.route("/books", methods=["GET"])
def list_or_search_books():
    kw = request.args.get("keyword")
    if kw is not None:
        if not _KEYWORD_RE.match(kw):
            return jsonify({}), 400
        try:
            coll = get_mongo_collection()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        use_text = os.environ.get("MONGO_KEYWORD_TEXT_SEARCH", "1").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        docs: list = []
        if use_text:
            try:
                docs = list(coll.find({"$text": {"$search": kw}}))
            except OperationFailure:
                docs = []
        if not docs:
            rx = re.compile(re.escape(kw), re.IGNORECASE)
            flt = {
                "$or": [
                    {"title": rx},
                    {"author": rx},
                    {"Author": rx},
                    {"description": rx},
                    {"genre": rx},
                    {"summary": rx},
                ]
            }
            try:
                docs = list(coll.find(flt))
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        rows = [mongo_doc_to_row(d) for d in docs]
        out = [row_to_book_json(r, True) for r in rows]
        if not out:
            return Response(status=204)
        return jsonify(out), 200

    try:
        coll = get_mongo_collection()
        docs = list(coll.find({}))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    rows = [mongo_doc_to_row(d) for d in docs]
    return jsonify([row_to_book_json(r, True) for r in rows]), 200


@app.route("/books/<isbn>/related-books", methods=["GET"])
def related_books_route(isbn):
    isbn_canonical = normalize_isbn_value(str(isbn).strip())
    if not isbn_canonical:
        return jsonify({}), 400
    if not RECOMMENDATION_BASE_URL:
        return jsonify({}), 503

    with _RELATED_BOOKS_CIRCUIT_LOCK:
        now_ts = int(time.time())
        state = _load_circuit_state()
        is_open = state.get("state") == "open"
        opened_at = int(state.get("opened_at") or 0)
        if is_open and (now_ts - opened_at) < CIRCUIT_OPEN_SECONDS:
            return jsonify({}), 503

        try:
            st, books = _fetch_related_books_external(isbn_canonical)
            _set_circuit_closed()
            if st == 204 or not books:
                return Response(status=204)
            books = _normalize_related_books_response(books)
            if not books:
                return Response(status=204)
            return jsonify(books), 200
        except requests.Timeout:
            if is_open:
                _set_circuit_open(now_ts)
                return jsonify({}), 503
            _set_circuit_open(now_ts)
            return jsonify({}), 504
        except Exception:
            if is_open:
                _set_circuit_open(now_ts)
                return jsonify({}), 503
            return jsonify({}), 504


@app.route("/books/<isbn>", methods=["GET"])
def book_by_isbn(isbn):
    isbn_path_raw = str(isbn).strip()
    isbn_canonical = normalize_isbn_value(isbn_path_raw)
    if not isbn_canonical:
        return jsonify({}), 400
    try:
        row = fetch_book_row_from_mongo(isbn_canonical)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    if not row:
        return jsonify({}), 404
    return jsonify(row_to_book_json(row, True)), 200


@app.route("/books/isbn/<isbn>", methods=["GET"])
def get_book_by_isbn_path(isbn):
    return book_by_isbn(isbn)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
