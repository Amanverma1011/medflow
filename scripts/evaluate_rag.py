"""Evaluate the RAG pipeline against data/sample/rag_eval.json.

    python scripts/evaluate_rag.py            # summary
    python scripts/evaluate_rag.py --details  # per-question rows
"""
import asyncio
import sys

import _bootstrap  # noqa: F401
from app.core.db import SessionLocal
from app.rag import evaluate


async def main() -> int:
    with SessionLocal() as db:
        report = await evaluate.run(db)
    print(f"RAG evaluation · {report['cases']} cases · k={report['k']}")
    print("providers: " + ", ".join(f"{k}={v}" for k, v in report["providers"].items()))
    for section in ("retrieval", "generation", "safety"):
        print(f"\n{section.upper()} ({report[section]['cases']} cases)")
        for name, value in report[section].items():
            if name != "cases":
                print(f"  {name:<22} {value}")
    if "--details" in sys.argv:
        print()
        for row in report["details"]:
            extras = {k: v for k, v in row.items() if k not in ("question", "type")}
            print(f"[{row['type']}] {row['question']}\n    {extras}")
    print(f"\n{report['note']}")
    # Non-zero exit when a safety case fails, so this can gate CI.
    return 0 if report["safety"]["pass_rate"] in (None, 1.0) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
