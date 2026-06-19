from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from runtime import events, queue
from runtime.bootstrap import bootstrap
from runtime.doctor import run_doctor
from runtime.version import __version__
from runtime.release_check import run_release_check
from runtime.snapshot import create_snapshot, inspect_snapshot, restore_snapshot


def dump(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def command_init(args: argparse.Namespace) -> None:
    dump(bootstrap(args.display_name, args.widget_domain, args.channel))


def command_doctor(args: argparse.Namespace) -> None:
    dump(run_doctor(offline=args.offline))


def command_signal(args: argparse.Namespace) -> None:
    dump(events.emit(
        text=" ".join(args.text),
        source=args.source,
        priority=args.priority,
        channel=args.channel,
        idempotency_key=args.idempotency_key,
        payload=json.loads(args.payload),
    ))


def command_status(args: argparse.Namespace) -> None:
    dump({
        "version": __version__,
        "doctor": run_doctor(offline=args.offline),
        "pulse": events.status(args.limit, args.channel),
        "scheduler": queue.next_wakeup(),
    })


def command_release_check(_args: argparse.Namespace) -> None:
    dump(run_release_check())


def command_snapshot_create(args: argparse.Namespace) -> None:
    dump(create_snapshot(Path(args.output)))


def command_snapshot_inspect(args: argparse.Namespace) -> None:
    dump(inspect_snapshot(Path(args.snapshot)))


def command_snapshot_restore(args: argparse.Namespace) -> None:
    dump(restore_snapshot(Path(args.snapshot), Path(args.target), force=args.force))


def command_test_pulse(args: argparse.Namespace) -> None:
    dump(events.emit(
        text="EIROS_PULSE_END_TO_END_TEST",
        source="eiros-cli",
        priority=1000,
        channel=args.channel,
        idempotency_key=args.idempotency_key,
        payload={"test": "reverse_wake", "requested_by": "eiros-cli"},
    ))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="eiros", description="EIROS control-plane command line")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Initialize or update an EIROS instance")
    init.add_argument("--display-name", default="")
    init.add_argument("--widget-domain", default="")
    init.add_argument("--channel", default="")
    init.set_defaults(func=command_init)

    doctor = commands.add_parser("doctor", help="Run installation and runtime diagnostics")
    doctor.add_argument("--offline", action="store_true")
    doctor.set_defaults(func=command_doctor)

    signal = commands.add_parser("signal", help="Send a durable event to a mounted Pulse")
    signal.add_argument("text", nargs="+")
    signal.add_argument("--source", default="terminal")
    signal.add_argument("--priority", type=int, default=0)
    signal.add_argument("--channel", default="")
    signal.add_argument("--idempotency-key", default="")
    signal.add_argument("--payload", default="{}")
    signal.set_defaults(func=command_signal)

    status = commands.add_parser("status", help="Show doctor, Pulse and scheduler state")
    status.add_argument("--offline", action="store_true")
    status.add_argument("--channel", default="")
    status.add_argument("--limit", type=int, default=20)
    status.set_defaults(func=command_status)

    release = commands.add_parser("release-check", help="Run all release gates")
    release.set_defaults(func=command_release_check)

    snapshot = commands.add_parser("snapshot", help="Create, inspect or restore durable runtime snapshots")
    snapshot_commands = snapshot.add_subparsers(dest="snapshot_command", required=True)

    snapshot_create = snapshot_commands.add_parser("create")
    snapshot_create.add_argument("output")
    snapshot_create.set_defaults(func=command_snapshot_create)

    snapshot_inspect = snapshot_commands.add_parser("inspect")
    snapshot_inspect.add_argument("snapshot")
    snapshot_inspect.set_defaults(func=command_snapshot_inspect)

    snapshot_restore = snapshot_commands.add_parser("restore")
    snapshot_restore.add_argument("snapshot")
    snapshot_restore.add_argument("target")
    snapshot_restore.add_argument("--force", action="store_true")
    snapshot_restore.set_defaults(func=command_snapshot_restore)

    test = commands.add_parser("test-pulse", help="Emit a reproducible reverse-wake test")
    test.add_argument("--channel", default="")
    test.add_argument("--idempotency-key", default="")
    test.set_defaults(func=command_test_pulse)
    return root


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
