"""
infra/dynamo_setup.py — DynamoDB Table Creation
================================================

Creates the exam_events table with the schema required for:
  - Warning event storage
  - S3 clip key linkage
  - Faculty APPROVED / MALPRACTICE decisions
  - Multi-student, multi-exam querying

Schema
------
  Table name : exam_events
  PK         : exam_id      (String) — e.g. "exam-2026-10-04"
  SK         : sort_key     (String) — e.g. "2026-10-04T10:30:00Z#s001"

  GSI: student-index
    PK: student_id           — query all warnings for one student
    SK: sort_key

Attributes written per warning event (by dynamo_logger.py):
  student_id       String   Firebase UID or student code
  session_id       String   UUID per exam session
  event_type       String   "WARNING" | "SESSION_START" | "SESSION_END"
  reason           String   "Phone detected", "Head turned left", etc.
  score_after      Number   Trust score after event (0–100)
  flagged          Boolean  True when score reaches 0
  recording_key    String   S3 key for clip, populated after upload completes
  faculty_decision String   "APPROVED" | "MALPRACTICE" — null until faculty acts
  decision_ts      String   ISO-8601 timestamp of faculty decision

Usage
-----
  # From your local machine (with AWS credentials configured):
  py -3.11 infra/dynamo_setup.py

  # From EC2 (IAM role credentials auto-resolved by boto3):
  python3.11 infra/dynamo_setup.py

Requires
--------
  pip install boto3
  IAM permissions: dynamodb:CreateTable, dynamodb:DescribeTable, dynamodb:ListTables
"""

from __future__ import annotations

import boto3
import os
import sys
import time

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "exam_events")
REGION     = os.environ.get("AWS_REGION",   "ap-south-1")


def create_table() -> None:
    client = boto3.client("dynamodb", region_name=REGION)

    # Check if table already exists
    try:
        existing = client.list_tables()["TableNames"]
    except Exception as exc:
        print(f"ERROR: Could not connect to DynamoDB: {exc}")
        print("Check that boto3 is installed and AWS credentials are configured.")
        sys.exit(1)

    if TABLE_NAME in existing:
        print(f"Table '{TABLE_NAME}' already exists in {REGION}. Nothing to do.")
        _describe_table(client)
        return

    print(f"Creating DynamoDB table '{TABLE_NAME}' in {REGION}...")

    client.create_table(
        TableName=TABLE_NAME,

        # Primary key
        KeySchema=[
            {"AttributeName": "exam_id",  "KeyType": "HASH"},   # Partition key
            {"AttributeName": "sort_key", "KeyType": "RANGE"},  # Sort key
        ],
        AttributeDefinitions=[
            {"AttributeName": "exam_id",    "AttributeType": "S"},
            {"AttributeName": "sort_key",   "AttributeType": "S"},
            {"AttributeName": "student_id", "AttributeType": "S"},
        ],

        # GSI: query all warnings for a specific student across all exams
        GlobalSecondaryIndexes=[
            {
                "IndexName": "student-index",
                "KeySchema": [
                    {"AttributeName": "student_id", "KeyType": "HASH"},
                    {"AttributeName": "sort_key",   "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],

        BillingMode="PAY_PER_REQUEST",  # On-demand — no capacity planning needed
    )

    print(f"Table '{TABLE_NAME}' creation initiated. Waiting for it to become ACTIVE...")
    _wait_for_active(client)


def _wait_for_active(client) -> None:
    """Poll until table status is ACTIVE."""
    for attempt in range(30):
        try:
            resp = client.describe_table(TableName=TABLE_NAME)
            status = resp["Table"]["TableStatus"]
            if status == "ACTIVE":
                print(f"\nTable '{TABLE_NAME}' is now ACTIVE.")
                _describe_table(client)
                return
            print(f"  Status: {status} (attempt {attempt + 1}/30)...")
        except Exception as exc:
            print(f"  Waiting... ({exc})")
        time.sleep(3)
    print("Timed out waiting for table to become ACTIVE. Check the AWS Console.")


def _describe_table(client) -> None:
    """Print a summary of the table config."""
    resp = client.describe_table(TableName=TABLE_NAME)
    t = resp["Table"]
    print(f"\nTable summary:")
    print(f"  Name    : {t['TableName']}")
    print(f"  Status  : {t['TableStatus']}")
    print(f"  PK      : {t['KeySchema'][0]['AttributeName']} (HASH)")
    print(f"  SK      : {t['KeySchema'][1]['AttributeName']} (RANGE)")
    gsis = t.get("GlobalSecondaryIndexes", [])
    for gsi in gsis:
        print(f"  GSI     : {gsi['IndexName']} — status: {gsi['IndexStatus']}")
    print(f"  Billing : {t.get('BillingModeSummary', {}).get('BillingMode', 'PROVISIONED')}")
    print(f"\n  View in console:")
    print(f"  https://{REGION}.console.aws.amazon.com/dynamodbv2/home?region={REGION}#table?name={TABLE_NAME}")


if __name__ == "__main__":
    create_table()
