from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(code: str, data_root: Path) -> dict:
    env = dict(os.environ)
    env["EIROS_DATA_DIR"] = str(data_root)
    env["PYTHONPATH"] = str(ROOT)
    process = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if process.returncode != 0:
        raise AssertionError(process.stderr or process.stdout)
    return json.loads(process.stdout)


def main() -> None:
    checks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="eiros-foundation-") as temp:
        data_root = Path(temp)
        bootstrap = run(
            "from runtime.bootstrap import bootstrap; import json; print(json.dumps(bootstrap('Portable Test','','alpha')))",
            data_root,
        )
        assert bootstrap["ok"] and bootstrap["data_root"] == str(data_root)
        checks.append("portable bootstrap")

        channel_result = run(
            """
from runtime import events
import json
settings=events.cfg()
a=events.emit('A',source='test',channel='alpha',idempotency_key='same')
b=events.emit('B',source='test',channel='beta',idempotency_key='same')
pa=events.poll('wa',0,'alpha',settings['instance_id'])
pb=events.poll('wb',0,'beta',settings['instance_id'])
events.mark_delivered(a['id'],'wa','alpha')
events.acknowledge(a['id'],'ok')
print(json.dumps({'a':pa['event']['id'],'b':pb['event']['id'],'alpha':events.status(10,'alpha'),'beta':events.status(10,'beta')}))
""",
            data_root,
        )
        assert channel_result["a"] != channel_result["b"]
        assert channel_result["alpha"]["pending_count"] == 0
        assert channel_result["beta"]["pending_count"] == 1
        checks.append("channel isolation")

        mismatch = run(
            """
from runtime import events
import json
try:
    events.poll('w',0,'alpha','wrong-instance')
    result={'rejected':False}
except RuntimeError:
    result={'rejected':True}
print(json.dumps(result))
""",
            data_root,
        )
        assert mismatch["rejected"] is True
        checks.append("instance mismatch rejected")

        doctor = run(
            "from runtime.doctor import run_doctor; import json; print(json.dumps(run_doctor(offline=True)))",
            data_root,
        )
        assert doctor["ok"] is True
        checks.append("portable doctor")

    print(json.dumps({"ok": True, "checks": checks, "count": len(checks)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
