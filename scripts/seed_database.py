"""Load the full demo hospital: structured data, knowledge base and AI insights.

    python scripts/seed_database.py            # wipes and reloads everything
    python scripts/seed_database.py --if-empty # no-op when users already exist

Run `alembic upgrade head` (from backend/) first. Every record created is synthetic.
"""
import argparse
import asyncio

import _bootstrap  # noqa: F401
from app.core.config import settings
from app.core.db import SessionLocal
from app.services import bootstrap


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--if-empty", action="store_true", help="only seed when the database has no users")
    parser.add_argument("--scale", type=float, default=1.0, help="patient/feedback volume multiplier")
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.if_empty:
            settings.auto_seed = True
            await bootstrap.seed_if_empty(db)
            return
        counts = await bootstrap.load_demo(db, scale=args.scale)
    print("Demo hospital loaded:")
    for name, value in counts.items():
        print(f"  {name:<20} {value}")
    print(f"\nSign in with any @demo.medflow.ai account. Password: {settings.demo_password}")


if __name__ == "__main__":
    asyncio.run(main())
