"""
backend/auth.py — Firebase login + role checks for the REST API
================================================================

The frontend sends the signed-in user's Firebase ID token:

    Authorization: Bearer <id token>

1. The token is verified against Google's public keys (no service account needed).
2. The caller's role is read from Firestore `users/{uid}` using THAT SAME TOKEN, so
   Firestore's own security rules apply — the backend never holds admin credentials.
3. Mentors may only act on exams they created; admins may act on any exam.

Environment:
    FIREBASE_PROJECT_ID   default "exam-proctor-31750"
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from fastapi import Depends, Header, HTTPException, WebSocket

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "exam-proctor-31750")
_FIRESTORE = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"
_ROLE_TTL_SEC = 60

_role_cache: Dict[str, Tuple[float, str]] = {}


@dataclass
class Caller:
    uid:   str
    role:  str
    token: str


def verify_id_token(token: str) -> dict:
    """Validate a Firebase ID token and return its claims. Raises ValueError if invalid."""
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    return id_token.verify_firebase_token(token, g_requests.Request(), audience=PROJECT_ID)


def _firestore_get(path: str, token: str) -> Optional[dict]:
    import requests

    resp = requests.get(f"{_FIRESTORE}/{path}", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("fields", {})


def fetch_role(uid: str, token: str) -> str:
    cached = _role_cache.get(uid)
    if cached and time.time() - cached[0] < _ROLE_TTL_SEC:
        return cached[1]
    fields = _firestore_get(f"users/{uid}", token) or {}
    role = fields.get("role", {}).get("stringValue", "")
    _role_cache[uid] = (time.time(), role)
    return role


def fetch_exam_owner(exam_id: str, token: str) -> Optional[str]:
    """uid of the mentor who created the exam, or None if the exam does not exist."""
    fields = _firestore_get(f"exams/{exam_id}", token)
    if fields is None:
        return None
    return fields.get("created_by", {}).get("stringValue", "")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def get_caller(authorization: Optional[str] = Header(default=None)) -> Caller:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = verify_id_token(token)
    except Exception as exc:  # noqa: BLE001
        logger.info("Token rejected: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    uid = claims.get("user_id") or claims.get("sub")
    try:
        role = fetch_role(uid, token)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Role lookup failed for %s: %s", uid, exc)
        raise HTTPException(status_code=503, detail="Could not verify your role.")
    return Caller(uid=uid, role=role, token=token)


def require_staff(caller: Caller = Depends(get_caller)) -> Caller:
    """Mentors and admins only. Students (and everyone else) get 403."""
    if caller.role not in ("mentor", "admin"):
        raise HTTPException(status_code=403, detail="Mentor or admin access required.")
    return caller


def ensure_exam_access(caller: Caller, exam_id: str) -> None:
    """Admin: any exam. Mentor: only exams they created."""
    if caller.role == "admin":
        return
    try:
        owner = fetch_exam_owner(exam_id, caller.token)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Exam lookup failed (%s): %s", exam_id, exc)
        raise HTTPException(status_code=503, detail="Could not verify exam ownership.")
    if owner is None:
        raise HTTPException(status_code=404, detail="Exam not found.")
    if owner != caller.uid:
        raise HTTPException(status_code=403, detail="You do not own this exam.")


# ---------------------------------------------------------------------------
# WebSocket handshake
# ---------------------------------------------------------------------------

WS_AUTH_ENABLED = os.environ.get("WS_AUTH", "1") != "0"     # "0" only for local harness tests
WS_AUTH_TIMEOUT = 10.0


async def authenticate_ws(
    websocket: WebSocket,
    expected_uid: Optional[str],
    roles: tuple,
) -> Optional[Caller]:
    """
    Browsers cannot set an Authorization header on a WebSocket, so the first message
    must be {"type": "auth", "token": "<Firebase ID token>"}.

    Closes the socket and returns None unless the token is valid, the user's role is in
    `roles`, and (when given) the token's uid equals `expected_uid`.
    Close codes: 4401 not authenticated, 4403 not allowed.
    """
    import json

    if not WS_AUTH_ENABLED:
        # Local harness mode: same protocol (client still sends an auth message), no verification.
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=WS_AUTH_TIMEOUT)
            if json.loads(raw).get("type") != "auth":
                raise ValueError("first message must be an auth message")
        except Exception:  # noqa: BLE001
            await websocket.close(code=4401)
            return None
        await websocket.send_text(json.dumps({"type": "auth_ok"}))
        return Caller(uid=expected_uid or "dev", role=roles[0], token="")

    loop = asyncio.get_running_loop()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=WS_AUTH_TIMEOUT)
        msg = json.loads(raw)
        if msg.get("type") != "auth" or not msg.get("token"):
            raise ValueError("first message must be an auth message")
        token = msg["token"]
        claims = await loop.run_in_executor(None, verify_id_token, token)
        uid = claims.get("user_id") or claims.get("sub")
        role = await loop.run_in_executor(None, fetch_role, uid, token)
    except Exception as exc:  # noqa: BLE001 — any failure means "not authenticated"
        logger.info("WebSocket auth failed: %s", exc)
        await websocket.close(code=4401)
        return None

    if role not in roles or (expected_uid is not None and uid != expected_uid):
        logger.info("WebSocket auth rejected: uid=%s role=%s expected=%s", uid, role, expected_uid)
        await websocket.close(code=4403)
        return None

    await websocket.send_text(json.dumps({"type": "auth_ok"}))
    return Caller(uid=uid, role=role, token=token)
