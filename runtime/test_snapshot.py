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
        timeout=60,
    )
    if process.returncode != 0:
        raise AssertionError(process.stderr or process.stdout)
    return json.loads(process.stdout)


def main() -> None:
    checks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="eiros-snapshot-test-") as temp:
        base = Path(temp)
        source = base / "source"
        restored = base / "restored"
        archive = base / "runtime-snapshot.tar.gz"

        initialized = run(
            "from runtime.bootstrap import bootstrap; import json; print(json.dumps(bootstrap('Snapshot Test','','snapshot')))",
            source,
        )
        instance_id = initialized["instance_id"]
        checks.append("bootstrap")

        run(
            """
from runtime import events
from runtime.config import DATA_ROOT
import json
(DATA_ROOT/'memory').mkdir(parents=True,exist_ok=True)
(DATA_ROOT/'memory'/'fact.txt').write_text('durable memory',encoding='utf-8')
e=events.emit('snapshot event',channel='snapshot',idempotency_key='snapshot-test')
print(json.dumps({'event_id':e['id']}))
""",
            source,
        )
        checks.append("durable data written")

        created = run(
            f"from runtime.snapshot import create_snapshot; from pathlib import Path; import json; print(json.dumps(create_snapshot(Path({str(archive)!r}))))",
            source,
        )
        assert created["ok"] and archive.is_file()
        assert created["manifest"]["instance_id"] == instance_id
        checks.append("snapshot created")

        inspected = run(
            f"from runtime.snapshot import inspect_snapshot; from pathlib import Path; import json; print(json.dumps(inspect_snapshot(Path({str(archive)!r}))))",
            source,
        )
        assert inspected["sha256"] == created["sha256"]
        checks.append("snapshot verified")

        restored_result = run(
            f"from runtime.snapshot import restore_snapshot; from pathlib import Path; import json; print(json.dumps(restore_snapshot(Path({str(archive)!r}),Path({str(restored)!r}))))",
            source,
        )
        assert restored_result["instance_id"] == instance_id
        assert (restored / "memory" / "fact.txt").read_text(encoding="utf-8") == "durable memory"
        source_config = json.loads((source / "config" / "instance.json").read_text(encoding="utf-8"))
        restored_config = json.loads((restored / "config" / "instance.json").read_text(encoding="utf-8"))
        assert source_config["instance_id"] == restored_config["instance_id"]
        checks.append("snapshot restored")

        rejected = subprocess.run(
            [sys.executable, "-c", f"from runtime.snapshot import restore_snapshot; from pathlib import Path; restore_snapshot(Path({str(archive)!r}),Path({str(restored)!r}))"],
            cwd=ROOT,
            env={**os.environ, "EIROS_DATA_DIR": str(source), "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert rejected.returncode != 0 and "not empty" in rejected.stderr
        checks.append("unsafe overwrite rejected")

    print(json.dumps({"ok": True, "checks": checks, "count": len(checks)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
