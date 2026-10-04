"""
infra/test_review_e2e_aws.py — end-to-end check of the manual-review pipeline on REAL AWS
=========================================================================================

    warning event -> DynamoDB -> S3 clip -> read event back -> presigned URL -> download
    -> mentor decision -> cleanup

Uses a unique throw-away exam id ("e2e-<timestamp>"), and deletes ONLY the items and the
S3 object it created. No student browser / webcam involved.

Run (needs AWS credentials, region ap-south-1):
    py -3.11 infra/test_review_e2e_aws.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("AWS_REGION", "ap-south-1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3
import numpy as np
import requests

from backend import dynamo_logger as db, s3_store
from backend.recorder import ClipRecorder, encode_and_upload

EXAM    = f"e2e-{int(time.time())}"
STUDENT = "e2e-student"
failures = []


def check(label: str, ok: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}")
    if not ok:
        failures.append(label)


def main() -> int:
    region = os.environ["AWS_REGION"]
    table = db._get_table()
    s3 = boto3.client("s3", region_name=region)
    s3_key = None
    event = None

    try:
        print(f"Exam id for this run: {EXAM}\n")

        print("1. Warning event with sanity_score = 0 -> DynamoDB")
        event = db.create_event(EXAM, STUDENT, "Phone detected for 10s.", 0, "e2e-session", 5)
        check("event written", event is not None)
        stored = db.get_event(EXAM, event["event_id"])
        check("event readable from DynamoDB", stored is not None)
        check("event has exam/student/score fields",
              stored["exam_id"] == EXAM and stored["student_id"] == STUDENT and stored["sanity_score"] == 0)

        print("2. Recording clip -> S3")
        rec = ClipRecorder(pre_roll=6, post_roll=0)
        for i in range(8):
            rec.feed(np.full((240, 320, 3), i * 25, np.uint8), now=i * 0.5)
        rec.arm(event, now=4.0)
        done = rec.feed(np.full((240, 320, 3), 200, np.uint8), now=4.5)
        check("clip ready for upload", len(done) == 1)
        s3_key = s3_store.recording_key(EXAM, STUDENT, event["event_id"])
        ok = encode_and_upload(done[0][1], s3_key, s3_store.upload_clip)
        check("clip encoded and uploaded to S3", ok, s3_key)
        db.attach_recording(EXAM, event["sort_key"], s3_key if ok else None)

        print("3. Event now links to the S3 object")
        stored = db.get_event(EXAM, event["event_id"])
        check("s3_object_key stored (key only, no URL)",
              stored.get("s3_object_key") == s3_key and "http" not in stored["s3_object_key"])
        check("recording_status READY", stored.get("recording_status") == "READY")

        print("4. Session needs manual review (score 0 is not a verdict)")
        session = db.get_session(EXAM, STUDENT)
        check("session PENDING_REVIEW", session["review_status"] == "PENDING_REVIEW")
        check("no mentor decision yet", "mentor_decision" not in session)

        print("5. Presigned URL")
        url = s3_store.presign_get(s3_key)
        check("URL is presigned and expires", "X-Amz-Signature" in url and "X-Amz-Expires=300" in url)
        r = requests.get(url, timeout=30)
        check("URL downloads the clip", r.status_code == 200 and b"ftyp" in r.content[:64],
              f"({len(r.content)} bytes, content-type {r.headers.get('Content-Type')})")
        anon = requests.get(f"https://{s3_store.bucket_name()}.s3.{region}.amazonaws.com/{s3_key}", timeout=30)
        check("bucket is private (unsigned URL denied)", anon.status_code in (401, 403), f"(HTTP {anon.status_code})")

        print("6. Mentor decision")
        after = db.set_review(EXAM, stored, "CLEARED", "e2e-mentor", "e2e test note")
        check("decision persisted on session", after["review_status"] == "CLEARED"
              and after["reviewed_by"] == "e2e-mentor" and after["reviewed_at"])
        check("event shows decision", db.get_event(EXAM, event["event_id"])["review_status"] == "CLEARED")
    finally:
        print("\nCleanup (only this run's test data)")
        try:
            if s3_key:
                s3.delete_object(Bucket=s3_store.bucket_name(), Key=s3_key)
                print(f"  deleted s3://{s3_store.bucket_name()}/{s3_key}")
            for item in db._query_exam(EXAM):
                if item["exam_id"] == EXAM:          # safety: only the throw-away exam
                    table.delete_item(Key={"exam_id": item["exam_id"], "sort_key": item["sort_key"]})
                    print(f"  deleted DynamoDB item {item['sort_key']}")
            left = db._query_exam(EXAM)
            check("no test items left in DynamoDB", len(left) == 0)
        except Exception as exc:  # noqa: BLE001
            print(f"  CLEANUP ERROR: {exc}")
            failures.append("cleanup")

    print("\nRESULT:", "ALL PASSED" if not failures else f"FAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
