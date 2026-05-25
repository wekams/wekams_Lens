"""Generate demo application logs as JSON-lines files.

Two log streams:
  /tmp/wekams-demo/logs/checkout/checkout-YYYY-MM-DD.log  — checkout service
  /tmp/wekams-demo/logs/payment/payment-YYYY-MM-DD.log    — payment service

The data is intentionally aligned with the Postgres demo (demo-shop) and
S3 demo (demo-lake) so cross-source questions have real answers:

- emails of failing checkouts match customers.email (in particular
  aria@example.com and noah@example.com — the two we see in
  demo-lake.web_events viewing /checkout 5 times each)
- a clear error spike on the most recent 5 days explains why the
  revenue dip in demo-shop.orders exists ("why did orders drop last
  week?" → "payment gateway returning card_declined at 3x normal rate")

Run:
  backend/.venv/bin/python scripts/demo-seed/build_logs_demo.py
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT_ROOT = Path("/tmp/wekams-demo/logs")

CHECKOUT_USERS_NORMAL = [
    "aria@example.com",
    "liam@example.com",
    "sofia@example.com",
    "noah@example.com",
    "emma@example.com",
    "kai@example.com",
    "mia@example.com",
    "guest_43781@anon",
    "guest_19283@anon",
    "guest_55012@anon",
]
CHECKOUT_USERS_HEAVY_FAIL = ["aria@example.com", "noah@example.com"]

PRODUCTS = [
    ("SKU-001", "Wireless Headphones", 12900),
    ("SKU-002", "Bluetooth Speaker", 6900),
    ("SKU-003", "Mechanical Keyboard", 14900),
    ("SKU-004", "Cotton T-Shirt", 2400),
    ("SKU-005", "Running Shoes", 8900),
    ("SKU-006", "Stainless Bottle", 1800),
    ("SKU-007", "Ceramic Mug", 900),
    ("SKU-008", "Yoga Mat", 3200),
]


def random_ts(day: datetime) -> datetime:
    """Random timestamp within a given calendar day."""
    return day.replace(
        hour=random.randint(0, 23),
        minute=random.randint(0, 59),
        second=random.randint(0, 59),
        microsecond=0,
    )


def write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    events.sort(key=lambda e: e["ts"])
    with path.open("w") as f:
        for e in events:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")


def build_checkout_logs() -> int:
    """One file per day for the last 14 days. Days 0..4 (last 5) have a
    failure-rate spike; days 5..13 are normal."""
    random.seed(7)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    total = 0
    for days_ago in range(14):
        day = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0)
        is_spike = days_ago < 5
        n_events = random.randint(40, 80)
        events: list[dict] = []

        for _ in range(n_events):
            ts = random_ts(day)
            user = random.choice(CHECKOUT_USERS_NORMAL)
            sku, name, price = random.choice(PRODUCTS)

            # Page-view-ish event
            events.append(
                {
                    "ts": ts.isoformat(),
                    "level": "info",
                    "service": "checkout",
                    "event": "page_view",
                    "user_email": user,
                    "page": random.choice(["/checkout", "/checkout/payment", "/checkout/review"]),
                }
            )

            # Then an attempted submit
            if random.random() < 0.7:
                fail_rate = 0.55 if is_spike else 0.15
                if random.random() < fail_rate:
                    code = random.choice(
                        ["card_declined", "card_declined", "card_declined", "rate_limited", "timeout"]
                        if is_spike
                        else ["card_declined", "insufficient_funds"]
                    )
                    events.append(
                        {
                            "ts": (ts + timedelta(seconds=random.randint(5, 90))).isoformat(),
                            "level": "error",
                            "service": "checkout",
                            "event": "checkout_failed",
                            "user_email": user,
                            "sku": sku,
                            "amount_cents": price,
                            "error_code": code,
                        }
                    )
                else:
                    events.append(
                        {
                            "ts": (ts + timedelta(seconds=random.randint(5, 90))).isoformat(),
                            "level": "info",
                            "service": "checkout",
                            "event": "checkout_succeeded",
                            "user_email": user,
                            "sku": sku,
                            "amount_cents": price,
                        }
                    )

        # Heavy failers — extra failed events for a couple of named users.
        if is_spike:
            for u in CHECKOUT_USERS_HEAVY_FAIL:
                for _ in range(random.randint(2, 5)):
                    ts = random_ts(day)
                    sku, _name, price = random.choice(PRODUCTS)
                    events.append(
                        {
                            "ts": ts.isoformat(),
                            "level": "error",
                            "service": "checkout",
                            "event": "checkout_failed",
                            "user_email": u,
                            "sku": sku,
                            "amount_cents": price,
                            "error_code": "card_declined",
                        }
                    )

        path = OUT_ROOT / "checkout" / f"checkout-{day.date().isoformat()}.log"
        write_jsonl(path, events)
        total += len(events)
    return total


def build_payment_logs() -> int:
    """Payment-gateway events. Spike of upstream timeouts on days 0..4."""
    random.seed(13)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    total = 0
    for days_ago in range(14):
        day = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0)
        is_spike = days_ago < 5
        events: list[dict] = []
        baseline = random.randint(30, 60)
        upstream_timeouts = random.randint(20, 40) if is_spike else random.randint(0, 3)

        for _ in range(baseline):
            ts = random_ts(day)
            ok = random.random() < (0.7 if is_spike else 0.92)
            events.append(
                {
                    "ts": ts.isoformat(),
                    "level": "info" if ok else "error",
                    "service": "payment",
                    "event": "charge_attempted",
                    "gateway": random.choice(["stripe", "stripe", "adyen"]),
                    "outcome": "succeeded" if ok else random.choice(["card_declined", "fraud_review"]),
                    "amount_cents": random.choice([500, 1290, 2400, 3200, 6900, 8900, 14900]),
                }
            )

        for _ in range(upstream_timeouts):
            ts = random_ts(day)
            events.append(
                {
                    "ts": ts.isoformat(),
                    "level": "error",
                    "service": "payment",
                    "event": "upstream_timeout",
                    "gateway": "stripe",
                    "upstream_latency_ms": random.randint(8000, 30000),
                    "message": "gateway response exceeded 8s; circuit breaker tripped",
                }
            )

        path = OUT_ROOT / "payment" / f"payment-{day.date().isoformat()}.log"
        write_jsonl(path, events)
        total += len(events)
    return total


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    n_checkout = build_checkout_logs()
    n_payment = build_payment_logs()
    print(f"Wrote {n_checkout} checkout events to {OUT_ROOT}/checkout/*.log")
    print(f"Wrote {n_payment} payment events to {OUT_ROOT}/payment/*.log")
    print("Spike pattern: days 0..4 have ~3x failure rate vs days 5..13.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
