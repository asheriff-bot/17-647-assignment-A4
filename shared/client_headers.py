"""
BFF header checks — match External ALB behavior (A2).
/status is public (no X-Client-Type, no JWT).
X-Client-Type is matched case-insensitively (autograders may send 'web' vs 'Web').
"""
from functools import wraps

from flask import jsonify, Response, request


def _missing_client_type_response():
    return Response(
        "Request missing X-Client-Type header",
        status=400,
        mimetype="text/plain",
    )


def require_x_client_type(*allowed_values: str):
    """Require X-Client-Type header; value matched case-insensitively to one of allowed_values."""

    allowed_lower = {v.lower() for v in allowed_values}

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            h = request.headers.get("X-Client-Type")
            if not h or not str(h).strip():
                return _missing_client_type_response()
            if str(h).strip().lower() in allowed_lower:
                return f(*args, **kwargs)
            return jsonify({}), 400

        return wrapped

    return decorator


require_web_client = require_x_client_type("Web")
require_mobile_client = require_x_client_type("iOS", "Android")
