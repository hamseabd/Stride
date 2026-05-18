#!/usr/bin/env python3
"""
Step 0: Pull real conversation traces from DynamoDB for eval calibration.

Usage:
    DYNAMODB_TABLE_NAME=stride-prod AWS_REGION=us-east-1 \
        python scripts/dump_traces.py --limit 100 --out evals/fixtures/raw/
"""
import argparse
import json
import os
import pathlib

import boto3
from boto3.dynamodb.conditions import Key


def main():
    parser = argparse.ArgumentParser(description="Pull conversation traces from DynamoDB")
    parser.add_argument("--limit", type=int, default=100, help="Max users to pull")
    parser.add_argument("--out", default="evals/fixtures/raw/", help="Output directory")
    args = parser.parse_args()

    table_name = os.environ["DYNAMODB_TABLE_NAME"]
    region = os.getenv("AWS_REGION", "us-east-1")
    endpoint = os.getenv("AWS_ENDPOINT_URL")
    kwargs = {"endpoint_url": endpoint} if endpoint else {}
    table = boto3.resource("dynamodb", region_name=region, **kwargs).Table(table_name)

    response = table.query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq("PROACTIVE#ACTIVE"),
        Limit=args.limit,
    )
    user_ids = [item["gsi1sk"].replace("USER#", "") for item in response.get("Items", [])]

    if not user_ids:
        print("No consented users found. Make sure DYNAMODB_TABLE_NAME points to the right table.")
        return

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for user_id in user_ids:
        conv = table.get_item(
            Key={"pk": f"USER#{user_id}", "sk": "CONVERSATION#CURRENT"}
        ).get("Item")
        if not conv:
            continue
        safe = user_id.replace("+", "").replace("-", "")
        path = out_dir / f"{safe}.json"
        path.write_text(json.dumps(conv, indent=2, default=str))
        print(f"  Wrote {path}")
        written += 1

    print(f"\nDone. {written} traces written to {out_dir}")
    print("Review the JSON files before writing L2 judge prompts.")


if __name__ == "__main__":
    main()
