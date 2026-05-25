"""Generate demo S3 data and upload to MinIO.

Produces two files in the wekams demo bucket:

  marketing/campaigns.parquet  — marketing campaign spend
  events/web_events.csv        — web pageview events

The web_events.user_email values overlap with customers.email in the
demo-shop Postgres so cross-source queries in Phase 2b have something
real to join.

Usage:
  .venv/bin/python scripts/demo-seed/build_s3_demo.py
"""

from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta, timezone

import duckdb


BUCKET = "demo-lake"
ENDPOINT = "http://localhost:9000"
ACCESS_KEY = "wekams_dev"
SECRET_KEY = "wekams_dev_secret"


def main() -> int:
    now = datetime.now(timezone.utc)

    # ── 1) Build the dataframes via DuckDB so we don't pull pandas. ──
    con = duckdb.connect()

    # Campaigns: 6 marketing campaigns over the last 120 days.
    campaigns_rows = [
        (1, "Spring Sale",       "google_ads", now - timedelta(days=110), now - timedelta(days=90),  450000),
        (2, "Brand Awareness",   "meta_ads",   now - timedelta(days=80),  now - timedelta(days=60),  320000),
        (3, "Retargeting Pilot", "meta_ads",   now - timedelta(days=55),  now - timedelta(days=40),  180000),
        (4, "Influencer Push",   "tiktok",     now - timedelta(days=45),  now - timedelta(days=30),  220000),
        (5, "Summer Launch",     "google_ads", now - timedelta(days=25),  now - timedelta(days=10),  610000),
        (6, "Email Reactivation","email",      now - timedelta(days=15),  now - timedelta(days=1),    45000),
    ]
    con.execute(
        """
        CREATE TABLE campaigns(
            id INTEGER,
            name VARCHAR,
            channel VARCHAR,
            started_at TIMESTAMP,
            ended_at TIMESTAMP,
            spend_cents BIGINT
        );
        """
    )
    con.executemany("INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, ?)", campaigns_rows)

    # Web events: 30 rows of pageviews; some emails match customers in Postgres
    # so cross-source joins are meaningful (Phase 2b).
    matching = ["aria@example.com", "liam@example.com", "noah@example.com", "mia@example.com"]
    non_matching = ["visitor1@example.com", "visitor2@example.com", "lurker@example.com"]
    pages = ["/", "/products", "/products/headphones", "/products/keyboard", "/checkout", "/about"]

    events_rows = []
    eid = 1
    for d in range(60):
        ts = now - timedelta(days=d, hours=(eid * 7) % 23)
        emails = matching if d % 3 == 0 else (matching + non_matching)
        email = emails[eid % len(emails)]
        page = pages[eid % len(pages)]
        events_rows.append((eid, email, page, ts.isoformat()))
        eid += 1

    con.execute(
        "CREATE TABLE web_events(id INTEGER, user_email VARCHAR, page VARCHAR, ts VARCHAR);"
    )
    con.executemany("INSERT INTO web_events VALUES (?, ?, ?, ?)", events_rows)

    # ── 2) Write to /tmp, then upload to MinIO via DuckDB httpfs ──

    parquet_path = "/tmp/wekams-campaigns.parquet"
    csv_path = "/tmp/wekams-web-events.csv"
    con.execute(f"COPY campaigns TO '{parquet_path}' (FORMAT 'parquet')")
    con.execute(f"COPY web_events TO '{csv_path}' (HEADER, DELIMITER ',')")

    # ── 3) Upload to MinIO via the s3 client (boto would be heavyweight;
    # mc would be ideal but we'd shell out). DuckDB's httpfs can write to
    # S3-compatible endpoints — use that.

    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(
        f"""
        CREATE SECRET wekams_minio (
            TYPE S3,
            KEY_ID '{ACCESS_KEY}',
            SECRET '{SECRET_KEY}',
            ENDPOINT 'localhost:9000',
            URL_STYLE 'path',
            USE_SSL false
        );
        """
    )

    s3_campaigns = f"s3://{BUCKET}/marketing/campaigns.parquet"
    s3_events    = f"s3://{BUCKET}/events/web_events.csv"

    con.execute(f"COPY campaigns TO '{s3_campaigns}' (FORMAT 'parquet')")
    con.execute(f"COPY web_events TO '{s3_events}' (HEADER, DELIMITER ',')")

    # ── 4) Verify by re-reading from S3 ──
    n_campaigns = con.execute(f"SELECT COUNT(*) FROM '{s3_campaigns}'").fetchone()[0]
    n_events    = con.execute(f"SELECT COUNT(*) FROM '{s3_events}'").fetchone()[0]

    print(f"Uploaded → s3://{BUCKET}/marketing/campaigns.parquet ({n_campaigns} rows)")
    print(f"Uploaded → s3://{BUCKET}/events/web_events.csv      ({n_events} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
