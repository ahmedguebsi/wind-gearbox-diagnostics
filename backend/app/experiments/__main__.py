"""CLI: ``python -m app.experiments reproduce EXP-YYYYMMDD-NNN`` (M-31).

Exit code 0 on EXACT/TOLERANCE match, 1 on MISMATCH.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.experiments.reproduce import ReproductionStatus, reproduce
from app.experiments.store import ArtifactStore


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.experiments")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reproduce_parser = subparsers.add_parser(
        "reproduce", help="Re-run an experiment from its artifacts and diff results"
    )
    reproduce_parser.add_argument("experiment_id")
    reproduce_parser.add_argument(
        "--root", type=Path, default=Path("artifacts"), help="Artifact root directory"
    )
    args = parser.parse_args(argv)

    store = ArtifactStore(args.root)
    report = reproduce(args.experiment_id, store)
    print(json.dumps(report.as_dict(), indent=2))
    return 1 if report.status is ReproductionStatus.MISMATCH else 0


if __name__ == "__main__":
    sys.exit(main())
