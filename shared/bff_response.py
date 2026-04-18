"""
Shared BFF response helpers (Location rewriting behind ALB).
"""
from flask import request


def absolute_location_header(location_value: str) -> str:
    """
    Gradescope often expects Location: http://<External-ALB>/... while backends emit /books/{isbn}.
    """
    if not location_value or not isinstance(location_value, str):
        return location_value
    loc = location_value.strip()
    if loc.startswith("http://") or loc.startswith("https://"):
        return loc
    if not loc.startswith("/"):
        return loc
    proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "http").split(",")[0].strip()
    host = (request.headers.get("Host") or "").split(",")[0].strip()
    if not host:
        return loc
    return f"{proto}://{host}{loc}"
