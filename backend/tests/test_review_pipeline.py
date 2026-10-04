"""
End-to-end test of the manual-review pipeline, run against moto (in-memory AWS):

  ML warning -> DynamoDB event + S3 clip -> score 0 -> session PENDING_REVIEW
  -> mentor lists / opens behaviour log -> presigned URL -> mentor decision persisted
  -> students (and other mentors) are locked out.

Run from the project root:
    py -3.11 -m pytest backend/tests -q -s

Firebase is replaced by dependency overrides; AWS by moto. The monitoring WebSocket is
exercised for real with a scripted stand-in for the ML model (no webcam / browser).
"""

from __future__ import annotations

import base64
import os
import time

import boto3
import cv2
import numpy as np
import pytest
import requests
from fastapi.testclient import TestClient
from moto import mock_aws

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
os.environ["AWS_REGION"] = "ap-south-1"
os.environ["DYNAMO_TABLE"] = "exam_events"
os.environ["RECORDING_BUCKET"] = "test-recordings"

EXAM, STUDENT, MENTOR, OTHER_MENTOR, STUDENT_USER = "exam-test-1", "student-test-1", "mentor-1", "mentor-2", "student-test-1"


def _make_table():
    """Same schema as infra/dynamo_setup.py."""
    boto3.client("dynamodb", region_name="ap-south-1").create_table(
        TableName="exam_events",
        KeySchema=[{"AttributeName": "exam_id", "KeyType": "HASH"}, {"AttributeName": "sort_key", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "exam_id", "AttributeType": "S"},
            {"AttributeName": "sort_key", "AttributeType": "S"},
            {"AttributeName": "student_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "student-index",
            "KeySchema": [{"AttributeName": "student_id", "KeyType": "HASH"}, {"AttributeName": "sort_key", "KeyType": "RANGE"}],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )


def _jpeg_b64(i: int) -> str:
    img = np.full((240, 320, 3), (i * 7) % 255, np.uint8)
    cv2.putText(img, f"frame {i}", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    ok, buf = cv2.imencode(".jpg", img)
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


class ScriptedMonitor:
    """Stands in for the ML model: fires one warning on frame 4 that drops the score to 0."""
    def __init__(self):
        self.n = 0

    def process_frame(self, frame):
        from backend.monitor_session import MonitorResult
        self.n += 1
        if self.n == 4:
            return MonitorResult(score=0, warnings=5, new_warning="Phone detected for 10s.")
        return MonitorResult(score=0 if self.n > 4 else 100, warnings=5 if self.n > 4 else 0)

    def close(self): ...


@pytest.fixture()
def env(monkeypatch):
    with mock_aws():
        from backend import dynamo_logger, s3_store, auth, recorder
        dynamo_logger.reset_clients()
        s3_store.reset_clients()
        _make_table()
        boto3.client("s3", region_name="ap-south-1").create_bucket(
            Bucket="test-recordings", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        # short post-roll so the test does not wait 4 real seconds
        monkeypatch.setattr(recorder, "POST_ROLL_SEC", 0.3)
        monkeypatch.setattr(recorder.ClipRecorder, "post_roll", 0.3, raising=False)

        import backend.main as main
        monkeypatch.setattr(main.registry, "get_or_create_monitor", lambda sid: ScriptedMonitor())
        monkeypatch.setattr(auth, "fetch_exam_owner", lambda exam_id, token: MENTOR if exam_id == EXAM else None)

        with TestClient(main.app) as client:
            yield client, main, dynamo_logger, s3_store, auth


def _as(main, auth, uid, role):
    main.app.dependency_overrides[auth.get_caller] = lambda: auth.Caller(uid=uid, role=role, token="t")


def _run_student_exam(client):
    with client.websocket_connect(f"/ws/student/{STUDENT}?exam_id={EXAM}&session_id=sess-1") as ws:
        for i in range(10):
            ws.send_json({"type": "frame", "data": _jpeg_b64(i)})
            ws.receive_json()
            time.sleep(0.1)


def _wait(fn, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    raise AssertionError("timed out waiting for condition")


def test_full_manual_review_pipeline(env):
    client, main, db, s3, auth = env

    # 1-3. ML warning -> DynamoDB event, S3 clip, event carries the S3 key
    _run_student_exam(client)
    event = _wait(lambda: next(
        (e for e in db.list_events(EXAM, STUDENT) if e.get("s3_object_key")), None))
    assert event["warning_type"] == "Phone detected for 10s."
    assert event["sanity_score"] == 0 and event["flagged"] is True
    assert event["exam_id"] == EXAM and event["student_id"] == STUDENT and event["event_id"]
    assert event["session_id"] == "sess-1"
    assert event["s3_object_key"] == f"recordings/{EXAM}/{STUDENT}/{event['event_id']}.mp4"
    assert event["recording_status"] == "READY"
    print("\n[1-3] event + S3 key:", event["s3_object_key"])

    obj = boto3.client("s3", region_name="ap-south-1").get_object(Bucket="test-recordings", Key=event["s3_object_key"])
    body = obj["Body"].read()
    assert b"ftyp" in body[:64] and len(body) > 1000, "clip is not a valid MP4"
    print("[2]   clip size:", len(body), "bytes, MP4 header OK")

    # 4. score 0 -> session needs manual review, not cheating
    session = db.get_session(EXAM, STUDENT)
    assert session["review_status"] == "PENDING_REVIEW"
    assert session["last_score"] == 0 and session["warning_count"] >= 1
    assert "CONFIRMED" not in str(session["review_status"])
    print("[4]   session status:", session["review_status"])

    # mentor dashboard list
    _as(main, auth, MENTOR, "mentor")
    r = client.get(f"/api/exams/{EXAM}/reviews")
    assert r.status_code == 200
    assert r.json()["sessions"][0]["student_id"] == STUDENT
    assert r.json()["sessions"][0]["review_status"] == "PENDING_REVIEW"

    # 5. behaviour log (no internal S3 key leaked to the browser)
    r = client.get(f"/api/events/{STUDENT}", params={"exam_id": EXAM})
    assert r.status_code == 200
    data = r.json()
    ev = data["events"][0]
    assert ev["has_recording"] is True and "s3_object_key" not in ev
    assert data["session"]["review_status"] == "PENDING_REVIEW"
    print("[5]   behaviour log OK:", ev["warning_type"], "score", ev["sanity_score"])

    # 6-8. presigned URL -> bytes come back as the recording
    r = client.get(f"/api/events/{ev['event_id']}/recording", params={"exam_id": EXAM})
    assert r.status_code == 200
    url = r.json()["url"]
    assert "Signature" in url or "X-Amz-Signature" in url, "URL is not presigned"
    assert r.json()["expires_in"] <= 900
    fetched = requests.get(url)
    assert fetched.status_code == 200 and fetched.content == body
    print("[6-8] presigned URL works, expires in", r.json()["expires_in"], "s")

    # 9-10. mentor decision persists
    r = client.patch(f"/api/events/{ev['event_id']}/review", params={"exam_id": EXAM},
                     json={"decision": "CLEARED", "notes": "Looked at a calculator, allowed."})
    assert r.status_code == 200
    s = db.get_session(EXAM, STUDENT)
    assert s["review_status"] == "CLEARED" and s["reviewed_by"] == MENTOR
    assert s["mentor_notes"].startswith("Looked") and s["reviewed_at"]
    r = client.patch(f"/api/events/{ev['event_id']}/review", params={"exam_id": EXAM},
                     json={"decision": "CONFIRMED_VIOLATION", "notes": "Second look: phone."})
    assert db.get_session(EXAM, STUDENT)["review_status"] == "CONFIRMED_VIOLATION"
    assert client.patch(f"/api/events/{ev['event_id']}/review", params={"exam_id": EXAM},
                        json={"decision": "FAILED"}).status_code == 422
    print("[9-10] decisions persisted:", db.get_session(EXAM, STUDENT)["review_status"])

    # a later warning must not overwrite the mentor's decision
    db.create_event(EXAM, STUDENT, "Face absent", 0, "sess-1", 6)
    assert db.get_session(EXAM, STUDENT)["review_status"] == "CONFIRMED_VIOLATION"

    # 11. students and other mentors are locked out
    for uid, role in ((STUDENT_USER, "student"),):
        _as(main, auth, uid, role)
        assert client.get(f"/api/events/{STUDENT}", params={"exam_id": EXAM}).status_code == 403
        assert client.get(f"/api/events/{ev['event_id']}/recording", params={"exam_id": EXAM}).status_code == 403
        assert client.patch(f"/api/events/{ev['event_id']}/review", params={"exam_id": EXAM},
                            json={"decision": "CLEARED"}).status_code == 403
        assert client.get(f"/api/exams/{EXAM}/reviews").status_code == 403
    _as(main, auth, OTHER_MENTOR, "mentor")           # a mentor who does not own the exam
    assert client.get(f"/api/events/{STUDENT}", params={"exam_id": EXAM}).status_code == 403
    assert client.get(f"/api/events/{ev['event_id']}/recording", params={"exam_id": EXAM}).status_code == 403
    _as(main, auth, "admin-1", "admin")                # admins can review any exam
    assert client.get(f"/api/events/{STUDENT}", params={"exam_id": EXAM}).status_code == 200
    main.app.dependency_overrides.clear()
    assert client.get(f"/api/events/{STUDENT}", params={"exam_id": EXAM}).status_code == 401
    print("[11]  student / other mentor 403, no token 401, admin allowed")


def test_score_zero_never_fails_or_cheats_student(env):
    """Reaching score 0 only flags the session — no automatic verdict."""
    client, main, db, s3, auth = env
    db.create_event(EXAM, STUDENT, "Head turned left", 0, "s", 5)
    s = db.get_session(EXAM, STUDENT)
    assert s["review_status"] == "PENDING_REVIEW"
    assert "mentor_decision" not in s and "reviewed_by" not in s


def test_recording_pending_returns_404_not_a_url(env):
    client, main, db, s3, auth = env
    e = db.create_event(EXAM, STUDENT, "Face absent", 40, "s", 2)
    _as(main, auth, MENTOR, "mentor")
    r = client.get(f"/api/events/{e['event_id']}/recording", params={"exam_id": EXAM})
    assert r.status_code == 404
    main.app.dependency_overrides.clear()
