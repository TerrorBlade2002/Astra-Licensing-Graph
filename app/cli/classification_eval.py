"""Run the offline, versioned classification regression dataset."""

import argparse
import json
from pathlib import Path

from app.evaluations.runner import evaluate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.dataset).as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
