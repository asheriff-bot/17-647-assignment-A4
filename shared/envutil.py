"""Safe parsing of integer environment variables (empty string must not crash the process)."""
import os


def env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return default
    try:
        return int(str(v).strip(), 10)
    except ValueError:
        return default
