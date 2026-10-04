"""
infra/test_aws.py — Verify DynamoDB + S3 access from EC2
=========================================================

Run this script ON THE EC2 INSTANCE (via SSH) to confirm that:
  1. The EC2 IAM role has DynamoDB PutItem + Query permissions
  2. The exam_events table exists and is reachable
  3. The EC2 IAM role has S3 PutObject + GetObject permissions
  4. The recording bucket exists and is reachable

Usage (on EC2):
    python3.11 infra/test_aws.py

Expected output when everything is working:
    [DynamoDB] Connecting to table 'exam_events' in ap-south-1...
    [DynamoDB] PutItem OK — test event written.
    [DynamoDB] Query OK — found 1 test event(s).
    [DynamoDB] DeleteItem OK — test item cleaned up.
    [S3] Connecting to bucket 'jaaiwanth-exam-monitor-recordings'...
    [S3] PutObject OK — test file uploaded.
    [S3] GetObject OK — test file downloaded (12 bytes).
    [S3] DeleteObject OK — test file cleaned up.

    ALL CHECKS PASSED. AWS integration is ready.
"""

from __future__ import annotations

import os
import sys
import time
import uuid

TABLE_NAME      = os.environ.get("DYNAMO_TABLE",      "exam_events")
RECORDING_BUCKET = os.environ.get("RECORDING_BUCKET", "jaaiwanth-exam-monitor-recordings")
REGION          = os.environ.get("AWS_REGION",         "ap-south-1")

_PASS = "\033[32mOK\033[0m"
_FAIL = "\033[31mFAIL\033[0m"

errors = []


def check_dynamodb() -> None:
    print(f"\n[DynamoDB] Connecting to table '{TABLE_NAME}' in {REGION}...")
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        errors.append("boto3 not installed — run: pip install boto3")
        print(f"  boto3 import: {_FAIL}")
        return

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE_NAME)

    # Test PutItem
    test_exam_id = "test-exam-infra-check"
    test_sort_key = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}#test-student"
    try:
        table.put_item(Item={
            "exam_id":    test_exam_id,
            "sort_key":   test_sort_key,
            "student_id": "test-student",
            "session_id": str(uuid.uuid4()),
            "event_type": "WARNING",
            "reason":     "Infrastructure test — safe to delete",
            "score_after": 95,
            "flagged":    False,
        })
        print(f"  PutItem: {_PASS}")
    except Exception as exc:
        errors.append(f"DynamoDB PutItem failed: {exc}")
        print(f"  PutItem: {_FAIL} — {exc}")
        return

    # Test Query
    try:
        resp = table.query(
            KeyConditionExpression="exam_id = :eid AND sort_key = :sk",
            ExpressionAttributeValues={":eid": test_exam_id, ":sk": test_sort_key},
        )
        count = len(resp.get("Items", []))
        print(f"  Query: {_PASS} — found {count} test event(s).")
    except Exception as exc:
        errors.append(f"DynamoDB Query failed: {exc}")
        print(f"  Query: {_FAIL} — {exc}")

    # Cleanup test item
    try:
        table.delete_item(Key={"exam_id": test_exam_id, "sort_key": test_sort_key})
        print(f"  DeleteItem (cleanup): {_PASS}")
    except Exception as exc:
        print(f"  DeleteItem (cleanup): {_FAIL} — {exc} (non-critical)")


def check_s3() -> None:
    print(f"\n[S3] Connecting to bucket '{RECORDING_BUCKET}'...")
    try:
        import boto3
    except ImportError:
        errors.append("boto3 not installed")
        return

    s3 = boto3.client("s3", region_name=REGION)
    test_key = f"infra-test/{uuid.uuid4()}.txt"
    test_content = b"exam-proctor-infra-test"

    # Test PutObject
    try:
        s3.put_object(Bucket=RECORDING_BUCKET, Key=test_key, Body=test_content)
        print(f"  PutObject: {_PASS}")
    except Exception as exc:
        errors.append(f"S3 PutObject failed: {exc}")
        print(f"  PutObject: {_FAIL} — {exc}")
        return

    # Test GetObject
    try:
        resp = s3.get_object(Bucket=RECORDING_BUCKET, Key=test_key)
        data = resp["Body"].read()
        print(f"  GetObject: {_PASS} — received {len(data)} bytes.")
    except Exception as exc:
        errors.append(f"S3 GetObject failed: {exc}")
        print(f"  GetObject: {_FAIL} — {exc}")

    # Test presigned URL generation (needed for faculty clip playback)
    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": RECORDING_BUCKET, "Key": test_key},
            ExpiresIn=300,
        )
        print(f"  Presigned URL: {_PASS} — ({url[:60]}...)")
    except Exception as exc:
        errors.append(f"S3 presigned URL failed: {exc}")
        print(f"  Presigned URL: {_FAIL} — {exc}")

    # Cleanup
    try:
        s3.delete_object(Bucket=RECORDING_BUCKET, Key=test_key)
        print(f"  DeleteObject (cleanup): {_PASS}")
    except Exception as exc:
        print(f"  DeleteObject (cleanup): {_FAIL} — {exc} (non-critical)")


if __name__ == "__main__":
    print("=" * 55)
    print("  AWS Integration Test — Exam Proctor")
    print("=" * 55)
    print(f"  Region   : {REGION}")
    print(f"  DynamoDB : {TABLE_NAME}")
    print(f"  S3       : {RECORDING_BUCKET}")

    check_dynamodb()
    check_s3()

    print("\n" + "=" * 55)
    if errors:
        print(f"  {_FAIL} — {len(errors)} check(s) failed:")
        for e in errors:
            print(f"    • {e}")
        print("\n  Fix the errors above, then re-run this script.")
        sys.exit(1)
    else:
        print(f"  \033[32mALL CHECKS PASSED.\033[0m AWS integration is ready.")
        print("  You can now start the FastAPI server and it will")
        print("  successfully write to DynamoDB and S3.")
    print("=" * 55)
