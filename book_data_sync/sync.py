#!/usr/bin/env python3
"""
A4 Book data sync: RDS books table -> MongoDB collection books_<ANDREW_ID> (full refresh upsert).
Run on a schedule via Kubernetes CronJob (e.g. every 60s).
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from typing import Any

import pymongo
import pymysql


def _db_host() -> str:
    return (os.environ.get("DB_HOST") or os.environ.get("DB_ENDPOINT") or "localhost").strip()


def _mongo_uri() -> str:
    return (os.environ.get("MONGO_URI") or os.environ.get("MONGODB_URI") or "").strip()


def _collection_name() -> str:
    aid = (os.environ.get("ANDREW_ID") or os.environ.get("ANDREWID") or "local").strip()
    return os.environ.get("MONGO_COLLECTION") or f"books_{aid}"


def _canonical_isbn(isbn: Any) -> str:
    s = str(isbn or "")
    return "".join(c for c in s if c.isdigit())


def _to_bson_price(v: Any):
    if v is None:
        return None
    if isinstance(v, Decimal):
        d = v
    else:
        d = Decimal(str(v))
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def main() -> int:
    mongo_uri = _mongo_uri()
    if not mongo_uri:
        print("sync: MONGO_URI is required", file=sys.stderr)
        return 1

    db_cfg = {
        "host": _db_host(),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "books_db"),
        "cursorclass": pymysql.cursors.DictCursor,
    }

    tls_ca = os.environ.get("MONGO_TLS_CA_FILE") or os.environ.get("DOCDB_TLS_CA_FILE")
    mkw: dict = {}
    if tls_ca and os.path.isfile(tls_ca):
        mkw["tls"] = True
        mkw["tlsCAFile"] = tls_ca

    client = pymongo.MongoClient(mongo_uri, **mkw)
    db_name = os.environ.get("MONGO_DB_NAME") or os.environ.get("MONGO_DATABASE") or "books"
    coll = client[db_name][_collection_name()]

    conn = pymysql.connect(**db_cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT isbn, title, author, description, genre, price, quantity, summary FROM books"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    for row in rows:
        canon = _canonical_isbn(row.get("isbn"))
        if not canon:
            continue
        # A4 Task 3: stored document keys match the public REST book JSON (ISBN, Author, …).
        doc = {
            "ISBN": row.get("isbn"),
            "title": row.get("title"),
            "Author": row.get("author"),
            "description": row.get("description"),
            "genre": row.get("genre"),
            "price": _to_bson_price(row.get("price")),
            "quantity": int(row.get("quantity") or 0),
            "summary": row.get("summary") or "",
            "isbn_canonical": canon,
        }
        coll.replace_one({"isbn_canonical": canon}, doc, upsert=True)

    print(f"sync: upserted {len(rows)} rows into {db_name}.{_collection_name()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
