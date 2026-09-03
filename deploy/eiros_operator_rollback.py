from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.vps_operator.recovery import RecoveryManager  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: eiros_operator_rollback.py <tx_id>")
    result = RecoveryManager().rollback(sys.argv[1])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
