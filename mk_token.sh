#!/usr/bin/env bash
python3 -c '
import json, base64, hmac, hashlib, time
def b64url(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")
h = b64url(json.dumps({"alg":"HS256","typ":"JWT"}, separators=(",",":")).encode())
p = b64url(json.dumps({"sub":"starlord","iss":"cmu.edu","exp": int(time.time())+86400}, separators=(",",":")).encode())
msg = f"{h}.{p}".encode()
s = b64url(hmac.new(b"dummy-secret-at-least-32-bytes-long!!", msg, hashlib.sha256).digest())
print(f"{h}.{p}.{s}")
'
