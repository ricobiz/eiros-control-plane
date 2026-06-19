from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from deploy.install import atomic_symlink, build_plan, copy_source, rollback_release, switch_release

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    checks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="eiros-installer-test-") as temp:
        base = Path(temp)
        args = argparse.Namespace(
            source=str(ROOT),
            prefix=str(base / "prefix"),
            data_dir=str(base / "data"),
            user="eiros",
            no_systemd=True,
            widget_domain="https://widget.example",
            channel="test-channel",
        )
        plan = build_plan(args, timestamp=1234567890)
        assert plan.release.endswith(f"{plan.version}-1234567890")
        assert plan.channel == "test-channel"
        checks.append("deterministic plan")

        source = base / "source"
        source.mkdir()
        (source / "keep.txt").write_text("keep", encoding="utf-8")
        (source / "runtime").mkdir()
        (source / "runtime" / "queue.json").write_text("{}", encoding="utf-8")
        (source / "runtime" / "module.py").write_text("x=1", encoding="utf-8")
        (source / "config").mkdir()
        (source / "config" / "instance.json").write_text("{}", encoding="utf-8")
        (source / "config" / "instance.example.json").write_text("{}", encoding="utf-8")
        copied = base / "copied"
        copy_source(source, copied)
        assert (copied / "keep.txt").exists()
        assert (copied / "runtime" / "module.py").exists()
        assert not (copied / "runtime" / "queue.json").exists()
        assert not (copied / "config" / "instance.json").exists()
        assert (copied / "config" / "instance.example.json").exists()
        checks.append("runtime data excluded")

        prefix = base / "links"
        old_release = prefix / "releases" / "old"
        new_release = prefix / "releases" / "new"
        old_release.mkdir(parents=True)
        new_release.mkdir(parents=True)
        current = prefix / "current"
        previous = prefix / "previous"
        atomic_symlink(current, old_release)
        old = switch_release(current, previous, new_release)
        assert old == old_release.resolve()
        assert current.resolve() == new_release.resolve()
        assert previous.resolve() == old_release.resolve()
        restored = rollback_release(current, previous)
        assert restored == old_release.resolve()
        assert current.resolve() == old_release.resolve()
        checks.append("atomic switch and rollback")

    print(json.dumps({"ok": True, "checks": checks, "count": len(checks)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
