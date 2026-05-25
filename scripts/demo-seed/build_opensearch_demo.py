"""Seed demo events into the local OpenSearch instance.

Creates an index `wekams-events` and bulk-loads ~2 weeks of synthetic
application events. The shape matches what most real apps emit through
structured logging libraries (Pino, Bunyan, Loguru, Serilog, etc.):

  ts            timestamp (date)
  level         info | warn | error
  service       checkout | payment | inventory | search
  event         page_view | order_placed | login_failed | upstream_timeout | ...
  user_email    keyword
  status_code   integer (HTTP)
  latency_ms    integer
  region        keyword

Deliberate spike: the most recent 3 days have a ~4x rate of
"upstream_timeout" errors in the `payment` service compared to the
prior 11 days. So a question like "why are recent payments failing?"
has a real, findable answer.

Usage:
  backend/.venv/bin/python scripts/demo-seed/build_opensearch_demo.py
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone

from opensearchpy import OpenSearch, helpers

HOST = "http://localhost:9200"
INDEX = "wekams-events"

USERS = [
    "aria@example.com", "liam@example.com", "sofia@example.com",
    "noah@example.com", "emma@example.com", "kai@example.com",
    "mia@example.com",
    "guest_43781@anon", "guest_19283@anon", "guest_55012@anon",
]
SERVICES = ["checkout", "payment", "inventory", "search"]
REGIONS = ["us-east-1", "eu-west-1", "ap-southeast-1"]
EVENT_TYPES = {
    "checkout": ["page_view", "cart_updated", "order_placed", "order_failed"],
    "payment": ["charge_attempted", "charge_succeeded", "charge_failed", "upstream_timeout"],
    "inventory": ["item_reserved", "stock_low", "stock_out"],
    "search":   ["query_issued", "query_slow"],
}


def random_ts(day: datetime) -> datetime:
    return day.replace(
        hour=random.randint(0, 23),
        minute=random.randint(0, 59),
        second=random.randint(0, 59),
        microsecond=0,
    )


def build_doc(day: datetime, spike: bool) -> dict:
    service = random.choice(SERVICES)
    event = random.choice(EVENT_TYPES[service])
    user = random.choice(USERS)
    ts = random_ts(day)
    # Decide if this is an error event
    if spike and service == "payment" and random.random() < 0.55:
        event = "upstream_timeout"
        level = "error"
        status_code = 504
        latency_ms = random.randint(8000, 30000)
    elif random.random() < 0.10:
        level = "error"
        status_code = random.choice([500, 502, 504, 400, 401])
        latency_ms = random.randint(1000, 8000)
    elif random.random() < 0.15:
        level = "warn"
        status_code = random.choice([200, 202, 204])
        latency_ms = random.randint(500, 2500)
    else:
        level = "info"
        status_code = 200
        latency_ms = random.randint(20, 800)
    return {
        "ts": ts.isoformat(),
        "level": level,
        "service": service,
        "event": event,
        "user_email": user,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "region": random.choice(REGIONS),
    }


def main() -> int:
    random.seed(11)
    client = OpenSearch(HOST)

    # Reset the index so this script is idempotent.
    if client.indices.exists(index=INDEX):
        client.indices.delete(index=INDEX)
        print(f"deleted existing index {INDEX}")

    client.indices.create(
        index=INDEX,
        body={
            "settings": {
                "index": {"number_of_shards": 1, "number_of_replicas": 0},
            },
            "mappings": {
                "properties": {
                    "ts":          {"type": "date"},
                    "level":       {"type": "keyword"},
                    "service":     {"type": "keyword"},
                    "event":       {"type": "keyword"},
                    "user_email":  {"type": "keyword"},
                    "status_code": {"type": "integer"},
                    "latency_ms":  {"type": "integer"},
                    "region":      {"type": "keyword"},
                }
            },
        },
    )
    print(f"created index {INDEX}")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    docs: list[dict] = []
    for days_ago in range(14):
        day = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0)
        spike = days_ago < 3
        n = random.randint(120, 200)
        for _ in range(n):
            docs.append(
                {
                    "_index": INDEX,
                    "_source": build_doc(day, spike),
                }
            )

    helpers.bulk(client, docs, chunk_size=1000)
    client.indices.refresh(index=INDEX)

    count = client.count(index=INDEX)["count"]
    print(f"bulk loaded {count} events into {INDEX}")

    # Quick check: errors-by-day for the payment service over last 14 days.
    agg = client.search(
        index=INDEX,
        body={
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"service": "payment"}},
                        {"term": {"level": "error"}},
                    ]
                }
            },
            "aggs": {
                "by_day": {
                    "date_histogram": {"field": "ts", "calendar_interval": "day"}
                }
            },
        },
    )
    print("\npayment errors by day:")
    for b in agg["aggregations"]["by_day"]["buckets"]:
        ds = b["key_as_string"][:10]
        print(f"  {ds}  {b['doc_count']:4d}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
