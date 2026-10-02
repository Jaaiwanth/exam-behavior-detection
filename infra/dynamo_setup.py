"""
infra/dynamo_setup.py — One-time DynamoDB Table Creation
=========================================================

Run this ONCE before deploying to create the exam_events table.

Usage:
    py -3.11 infra/dynamo_setup.py

Requires:
    - boto3 installed
    - AWS credentials configured (aws configure OR environment variables)
    - Sufficient IAM permissions: dynamodb:CreateTable, dynamodb:DescribeTable
"""

import boto3
import os

TABLE_NAME = os.environ.get("DYNAMO_TABLE", "exam_events")
REGION     = os.environ.get("AWS_REGION",   "ap-south-1")

def create_table():
    client = boto3.client("dynamodb", region_name=REGION)

    existing = [t for t in client.list_tables()["TableNames"]]
    if TABLE_NAME in existing:
        print(f"Table '{TABLE_NAME}' already exists in {REGION}.")
        return

    print(f"Creating DynamoDB table '{TABLE_NAME}' in {REGION}...")
    client.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "student_id", "KeyType": "HASH"},   # Partition key
            {"AttributeName": "timestamp",  "KeyType": "RANGE"},  # Sort key
        ],
        AttributeDefinitions=[
            {"AttributeName": "student_id", "AttributeType": "S"},
            {"AttributeName": "timestamp",  "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",   # On-demand — no capacity planning needed
    )
    print(f"Table '{TABLE_NAME}' created. It may take a few seconds to become active.")
    print("You can check status at: https://console.aws.amazon.com/dynamodb/")

if __name__ == "__main__":
    create_table()
