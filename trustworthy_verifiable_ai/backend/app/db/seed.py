"""Idempotent database seeding script for scenarios a to f.

Enforces:
- NFR-02: Deterministic seed data with fixed IDs.
- NFR-03: Integer minor units for currency.
- SEC-01: Seeded roles (customer, agent, reviewer).
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.order import Order
from app.models.payment import Payment, PaymentEvent, PaymentStatus
from app.models.policy import Policy
from app.models.refund import Refund, RefundStatus
from app.models.user import User, UserRole


def load_seed_json() -> dict[str, Any]:
    """Load raw seed data from canonical JSON file."""
    candidates = [
        Path(__file__).resolve().parents[3] / "data" / "seed" / "seed_data.json",
        Path(__file__).resolve().parents[4] / "data" / "seed" / "seed_data.json",
        Path("data/seed/seed_data.json"),
        Path("../data/seed/seed_data.json"),
    ]
    for seed_path in candidates:
        if seed_path.exists():
            with open(seed_path, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("Could not find seed_data.json")


def parse_iso(dt_str: str) -> datetime:
    """Parse ISO datetime string to timezone-aware UTC datetime."""
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


def seed_database(db: Session | None = None) -> dict[str, int]:
    """Idempotently seed the database with deterministic scenario data.

    Returns:
        Dict with counts of seeded entities.
    """
    should_close = False
    if db is None:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        should_close = True

    counts = {
        "users": 0,
        "policies": 0,
        "orders": 0,
        "payments": 0,
        "refunds": 0,
        "payment_events": 0,
    }

    try:
        data = load_seed_json()

        # 1. Seed Users
        for u in data.get("users", []):
            existing_user = db.query(User).filter(User.id == u["id"]).first()
            if not existing_user:
                new_user = User(
                    id=u["id"],
                    email=u["email"],
                    name=u["name"],
                    role=UserRole(u["role"]),
                    hashed_password=get_password_hash(u["password"]),
                )
                db.add(new_user)
                counts["users"] += 1

        # 2. Seed Policies
        for p in data.get("policies", []):
            existing_pol = db.query(Policy).filter(Policy.id == p["id"]).first()
            if not existing_pol:
                new_pol = Policy(
                    id=p["id"],
                    name=p["name"],
                    description=p.get("description"),
                    rules_json=p["rules_json"],
                )
                db.add(new_pol)
                counts["policies"] += 1

        db.flush()

        # 3. Seed Scenarios (a through f)
        for _, scenario in data.get("scenarios", {}).items():
            cust_id = scenario["customer_id"]

            for o in scenario.get("orders", []):
                if not db.query(Order).filter(Order.id == o["id"]).first():
                    order = Order(
                        id=o["id"],
                        customer_id=cust_id,
                        order_number=o["order_number"],
                        amount=o["amount"],
                        currency="USD",
                        status=o["status"],
                    )
                    db.add(order)
                    counts["orders"] += 1

            for p in scenario.get("payments", []):
                if not db.query(Payment).filter(Payment.id == p["id"]).first():
                    payment = Payment(
                        id=p["id"],
                        customer_id=cust_id,
                        order_id=p.get("order_id"),
                        amount=p["amount"],
                        currency="USD",
                        status=PaymentStatus(p["status"]),
                    )
                    db.add(payment)
                    counts["payments"] += 1

            for r in scenario.get("refunds", []):
                if not db.query(Refund).filter(Refund.id == r["id"]).first():
                    refund = Refund(
                        id=r["id"],
                        payment_id=r["payment_id"],
                        customer_id=cust_id,
                        amount=r["amount"],
                        currency="USD",
                        status=RefundStatus(r["status"]),
                        reason=r.get("reason"),
                    )
                    db.add(refund)
                    counts["refunds"] += 1

            for pe in scenario.get("payment_events", []):
                existing_evt = db.query(PaymentEvent).filter(
                    PaymentEvent.provider_event_id == pe["provider_event_id"]
                ).first()
                if not existing_evt:
                    evt = PaymentEvent(
                        provider_event_id=pe["provider_event_id"],
                        payment_id=pe.get("payment_id"),
                        event_type=pe["event_type"],
                        amount=pe["amount"],
                        currency="USD",
                        occurred_at=parse_iso(pe["occurred_at"]),
                        received_at=parse_iso(pe["received_at"]),
                        raw_payload=pe["raw_payload"],
                    )
                    db.add(evt)
                    counts["payment_events"] += 1

        db.commit()
        return counts

    except Exception:
        db.rollback()
        raise
    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    print("Seeding database...")
    created = seed_database()
    print("Seed complete:", created)
