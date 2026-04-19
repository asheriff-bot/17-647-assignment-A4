#!/usr/bin/env python3
"""
Create a MongoDB text index for GET /books?keyword= (book_query_service).

Uses the same env vars as book-query / sync: MONGO_URI (or MONGODB_URI), MONGO_DB_NAME,
MONGO_COLLECTION, and optionally MONGO_TLS_CA_FILE / DOCDB_TLS_CA_FILE for TLS.

Examples:
  export MONGO_URI='mongodb+srv://user:pass@cluster.mongodb.net/?appName=bookstore'
  export MONGO_DB_NAME=books
  export MONGO_COLLECTION=books_asheriff
  python scripts/atlas_text_index.py

  MONGO_URI='...' python scripts/atlas_text_index.py --db books --collection books_asheriff

Requires: pip install pymongo  (same as book_query_service)
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    p = argparse.ArgumentParser(description="Create text index on MongoDB Atlas / MongoDB.")
    p.add_argument(
        "--uri",
        default="",
        help="Connection URI (default: MONGO_URI or MONGODB_URI env)",
    )
    p.add_argument(
        "--db",
        default="",
        help="Database name (default: MONGO_DB_NAME env or books)",
    )
    p.add_argument(
        "--collection",
        default="",
        help="Collection name (default: MONGO_COLLECTION env or books_asheriff)",
    )
    args = p.parse_args()

    uri = (args.uri or os.environ.get("MONGO_URI") or os.environ.get("MONGODB_URI") or "").strip()
    if not uri:
        print("error: set MONGO_URI or pass --uri", file=sys.stderr)
        return 1

    db_name = (
        (args.db or os.environ.get("MONGO_DB_NAME") or os.environ.get("MONGO_DATABASE") or "books")
        .strip()
    )
    coll_name = (
        (args.collection or os.environ.get("MONGO_COLLECTION") or "books_asheriff").strip()
    )

    tls_ca = os.environ.get("MONGO_TLS_CA_FILE") or os.environ.get("DOCDB_TLS_CA_FILE")
    kwargs: dict = {}
    if tls_ca and os.path.isfile(tls_ca):
        kwargs["tls"] = True
        kwargs["tlsCAFile"] = tls_ca

    try:
        from pymongo import MongoClient
    except ImportError:
        print("error: install pymongo: pip install pymongo", file=sys.stderr)
        return 1

    client = MongoClient(uri, **kwargs)
    coll = client[db_name][coll_name]

    # Same fields as book_query regex fallback + Atlas text search
    index_spec = [
        ("title", "text"),
        ("description", "text"),
        ("Author", "text"),
        ("summary", "text"),
        ("genre", "text"),
    ]
    name = coll.create_index(index_spec, name="books_keyword_text", default_language="english")
    print(f"created index: {name} on {db_name}.{coll_name}")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
