"""Regenerate only the structured synthetic data (people, appointments, queues, beds, feedback).

Unlike seed_database.py this does not ingest knowledge documents or compute
insights, which makes it quick for testing the generator at different sizes:

    python scripts/generate_demo_data.py --scale 0.2 --days 14
"""
import argparse

import _bootstrap  # noqa: F401
from app.core.db import SessionLocal
from app.services import seed

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--days", type=int, default=45, help="days of appointment history")
    args = parser.parse_args()
    with SessionLocal() as db:
        for name, value in seed.run(db, scale=args.scale, days_back=args.days).items():
            print(f"{name:<16} {value}")
