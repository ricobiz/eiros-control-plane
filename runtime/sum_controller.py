from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


def now() -> int:
    return int(time.time())


class SumControllerStore:
    """Durable state machine for one SUM auto-wake controller."""

    def __init__(
        self,
        path: Path,
        log_path: Path,
        *,
        clock: Callable[[], int] = now,
        static_debounce_seconds: int = 3,
        ack_timeout_seconds: int = 120,
        retry_interval_seconds: int = 60,
        response_grace_seconds: int = 300,
        max_wake_attempts: int = 3,
        max_cycles: int = 100,
        max_runtime_seconds: int = 4 * 60 * 60,
    ) -> None:
        self.path = Path(path)
        self.log_path = Path(log_path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.clock = clock
        self.static_debounce_seconds = max(1, int(static_debounce_seconds))
        self.ack_timeout_seconds = max(1, int(ack_timeout_seconds))
        self.retry_interval_seconds = max(1, int(retry_interval_seconds))
        self.response_grace_seconds = max(1, int(response_grace_seconds))
        self.max_wake_attempts = max(1, int(max_wake_attempts))
        self.max_cycles = max(1, int(max_cycles))
        self.max_runtime_seconds = max(1, int(max_runtime_seconds))

    def _timestamp(self) -> int:
        return int(self.clock())

    def _default_state(self) -> dict[str, Any]:
        timestamp = self._timestamp()
        return {
            "schema_version": 1,
            "controller_id": f"sum-{uuid.uuid4().hex}",
            "enabled": False,
            "state": "IDLE",
            "color": "gray",
            "revision": 0,
            "cycle_id": 0,
            "awake_epoch": 0,
            "wake_id": "",
            "wake_attempt": 0,
            "send_required": False,
            "started_at": 0,
            "state_entered_at": timestamp,
            "listener_session_id": "",
            "last_ack_at": 0,
            "last_activity_at": 0,
            "last_static_candidate_at": 0,
            "last_wake_sent_at": 0,
            "wake_wait_until": 0,
            "wake_response_started_at": 0,
            "last_acked_wake_id": "",
            "activity_observed": False,
            "stop_reason": None,
            "error_code": "",
            "counters": {
                "cycles_started": 0,
                "wakes_sent": 0,
                "wakes_acked": 0,
                "retries": 0,
                "errors": 0,
            },
            "limits": {
                "static_debounce_seconds": self.static_debounce_seconds,
                "ack_timeout_seconds": self.ack_timeout_seconds,
                "retry_interval_seconds": self.retry_interval_seconds,
                "response_grace_seconds": self.response_grace_seconds,
                "max_wake_attempts": self.max_wake_attempts,
                "max_cycles": self.max_cycles,
                "max_runtime_seconds": self.max_runtime_seconds,
            },
        }

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_state()
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("SUM controller state must be a JSON object")
        value.setdefault("wake_wait_until", 0)
        value.setdefault("wake_response_started_at", 0)
        limits = value.setdefault("limits", {})
        limits.update({
            "static_debounce_seconds": self.static_debounce_seconds,
            "ack_timeout_seconds": self.ack_timeout_seconds,
            "retry_interval_seconds": self.retry_interval_seconds,
            "response_grace_seconds": self.response_grace_seconds,
            "max_wake_attempts": self.max_wake_attempts,
            "max_cycles": self.max_cycles,
            "max_runtime_seconds": self.max_runtime_seconds,
        })
        return value

    def _write_unlocked(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @contextmanager
    def _locked_state(self) -> Iterator[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = self._read_unlocked()
            if not self.path.exists():
                self._write_unlocked(state)
            try:
                yield state
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _append_log(
        self,
        state: dict[str, Any],
        *,
        previous_state: str,
        reason: str,
        actor: str,
        host_signal: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": self._timestamp(),
            "controller_id": state["controller_id"],
            "revision": state["revision"],
            "cycle_id": state["cycle_id"],
            "awake_epoch": state["awake_epoch"],
            "wake_id": state["wake_id"],
            "previous_state": previous_state,
            "new_state": state["state"],
            "reason": reason,
            "actor": actor,
            "attempt": state["wake_attempt"],
            "listener_session_id": state["listener_session_id"],
            "host_signal": host_signal,
            "error_code": state.get("error_code", ""),
            "detail": detail or {},
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _commit(
        self,
        state: dict[str, Any],
        *,
        previous_state: str,
        reason: str,
        actor: str,
        host_signal: str = "",
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state["revision"] = int(state.get("revision", 0)) + 1
        self._write_unlocked(state)
        self._append_log(
            state,
            previous_state=previous_state,
            reason=reason,
            actor=actor,
            host_signal=host_signal,
            detail=detail,
        )
        return dict(state)

    def _start_wake(
        self,
        state: dict[str, Any],
        *,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        previous_state = str(state.get("state") or "IDLE")
        timestamp = self._timestamp()
        state["state"] = "WAKE"
        state["color"] = "red"
        state["cycle_id"] = int(state.get("cycle_id", 0)) + 1
        state["awake_epoch"] = int(state.get("awake_epoch", 0)) + 1
        state["wake_id"] = f"wake-{uuid.uuid4().hex}"
        state["wake_attempt"] = 0
        state["send_required"] = True
        state["last_wake_sent_at"] = 0
        state["wake_wait_until"] = 0
        state["wake_response_started_at"] = 0
        state["last_static_candidate_at"] = 0
        state["activity_observed"] = False
        state["state_entered_at"] = timestamp
        state["error_code"] = ""
        state["stop_reason"] = None
        state["counters"]["cycles_started"] = int(
            state["counters"].get("cycles_started", 0)
        ) + 1
        return self._commit(
            state,
            previous_state=previous_state,
            reason=reason,
            actor=actor,
        )

    def status(self) -> dict[str, Any]:
        with self._locked_state() as state:
            return dict(state)

    def set_enabled(
        self,
        enabled: bool,
        actor: str,
        listener_session_id: str = "",
    ) -> dict[str, Any]:
        with self._locked_state() as state:
            previous_state = str(state.get("state") or "IDLE")
            timestamp = self._timestamp()
            state["enabled"] = bool(enabled)
            state["state"] = "ARMED" if enabled else "IDLE"
            state["color"] = "gray"
            state["state_entered_at"] = timestamp
            state["listener_session_id"] = str(listener_session_id or "")[:180]
            state["stop_reason"] = None if enabled else "disabled"
            state["error_code"] = ""
            state["send_required"] = False
            state["wake_wait_until"] = 0
            state["wake_response_started_at"] = 0
            if enabled and not int(state.get("started_at", 0)):
                state["started_at"] = timestamp
            return self._commit(
                state,
                previous_state=previous_state,
                reason="CYCLE_ARMED" if enabled else "CYCLE_DISABLED",
                actor=str(actor or "unknown")[:80],
            )

    def tick(
        self,
        listener_session_id: str,
        *,
        pip_active: bool,
        listener_healthy: bool,
    ) -> dict[str, Any]:
        with self._locked_state() as state:
            if not bool(state.get("enabled")):
                return dict(state)
            state["listener_session_id"] = str(listener_session_id or "")[:180]
            if not pip_active or not listener_healthy:
                return dict(state)
            current = str(state.get("state") or "IDLE")
            if current == "ARMED":
                return self._start_wake(
                    state,
                    actor="sum",
                    reason="STATIC_CONFIRMED",
                )
            if current == "STATIC_DEBOUNCE":
                candidate_at = int(state.get("last_static_candidate_at", 0))
                if candidate_at and self._timestamp() - candidate_at >= self.static_debounce_seconds:
                    return self._start_wake(
                        state,
                        actor="sum",
                        reason="CYCLE_COMPLETE",
                    )
            if current == "WAKE":
                sent_at = int(state.get("last_wake_sent_at", 0))
                attempt = int(state.get("wake_attempt", 0))
                timestamp = self._timestamp()
                wait_until = int(state.get("wake_wait_until", 0))
                if sent_at and not wait_until:
                    wait_seconds = self.ack_timeout_seconds if attempt <= 1 else self.retry_interval_seconds
                    wait_until = sent_at + wait_seconds
                    state["wake_wait_until"] = wait_until
                response_started_at = int(state.get("wake_response_started_at", 0))
                if response_started_at:
                    wait_until = max(wait_until, response_started_at + self.response_grace_seconds)
                    state["wake_wait_until"] = wait_until
                retry_due = (
                    sent_at
                    and not bool(state.get("send_required"))
                    and timestamp >= wait_until
                )
                if retry_due and attempt < self.max_wake_attempts:
                    previous_state = current
                    state["send_required"] = True
                    return self._commit(
                        state,
                        previous_state=previous_state,
                        reason="WAKE_RETRY_READY",
                        actor="sum",
                    )
                if retry_due and attempt >= self.max_wake_attempts:
                    previous_state = current
                    state["enabled"] = False
                    state["state"] = "ERROR"
                    state["color"] = "red"
                    state["send_required"] = False
                    state["state_entered_at"] = self._timestamp()
                    state["error_code"] = "ACK_TIMEOUT"
                    state["stop_reason"] = "ack_timeout"
                    state["counters"]["errors"] = int(
                        state["counters"].get("errors", 0)
                    ) + 1
                    return self._commit(
                        state,
                        previous_state=previous_state,
                        reason="ACK_TIMEOUT",
                        actor="sum",
                    )
            return dict(state)

    def mark_wake_sent(
        self,
        listener_session_id: str,
        delivery_mode: str,
    ) -> dict[str, Any]:
        with self._locked_state() as state:
            if str(state.get("state")) != "WAKE" or not state.get("wake_id"):
                return dict(state)
            if not bool(state.get("send_required")):
                return dict(state)
            previous_state = str(state.get("state"))
            state["listener_session_id"] = str(listener_session_id or "")[:180]
            previous_attempt = int(state.get("wake_attempt", 0))
            state["wake_attempt"] = previous_attempt + 1
            state["send_required"] = False
            timestamp = self._timestamp()
            state["last_wake_sent_at"] = timestamp
            wait_seconds = self.ack_timeout_seconds if previous_attempt == 0 else self.retry_interval_seconds
            state["wake_wait_until"] = timestamp + wait_seconds
            if previous_attempt == 0:
                state["wake_response_started_at"] = 0
            state["counters"]["wakes_sent"] = int(
                state["counters"].get("wakes_sent", 0)
            ) + 1
            if previous_attempt > 0:
                state["counters"]["retries"] = int(
                    state["counters"].get("retries", 0)
                ) + 1
            return self._commit(
                state,
                previous_state=previous_state,
                reason="WAKE_RETRY" if previous_attempt > 0 else "WAKE_SENT",
                actor="listener",
                detail={"delivery_mode": str(delivery_mode or "")[:80]},
            )

    def ack_current(
        self,
        *,
        actor: str,
        listener_session_id: str = "",
    ) -> dict[str, Any]:
        with self._locked_state() as state:
            wake_id = str(state.get("wake_id") or "")
            if (
                wake_id
                and str(state.get("last_acked_wake_id") or "") == wake_id
                and str(state.get("state")) in {"AWAKE", "WORKING", "STATIC_DEBOUNCE"}
            ):
                return dict(state)
            current_state = str(state.get("state"))
            late_timeout_recovery = (
                current_state == "ERROR"
                and str(state.get("error_code") or "") == "ACK_TIMEOUT"
                and bool(wake_id)
            )
            if current_state != "WAKE" and not late_timeout_recovery:
                return dict(state)
            previous_state = current_state
            state["enabled"] = True
            state["state"] = "AWAKE"
            state["color"] = "green"
            state["state_entered_at"] = self._timestamp()
            state["last_ack_at"] = self._timestamp()
            state["last_acked_wake_id"] = wake_id
            state["send_required"] = False
            state["wake_wait_until"] = 0
            state["wake_response_started_at"] = 0
            state["error_code"] = ""
            state["stop_reason"] = None
            state["activity_observed"] = False
            if listener_session_id:
                state["listener_session_id"] = str(listener_session_id)[:180]
            state["counters"]["wakes_acked"] = int(
                state["counters"].get("wakes_acked", 0)
            ) + 1
            return self._commit(
                state,
                previous_state=previous_state,
                reason="LATE_WAKE_ACK_RECOVERY" if late_timeout_recovery else "WAKE_ACK",
                actor=str(actor or "unknown")[:80],
            )

    def ack_wake(
        self,
        wake_id: str,
        cycle_id: int,
        awake_epoch: int,
        actor: str,
    ) -> dict[str, Any]:
        with self._locked_state() as state:
            if (
                str(state.get("wake_id") or "") != str(wake_id or "")
                or int(state.get("cycle_id", 0)) != int(cycle_id)
                or int(state.get("awake_epoch", 0)) != int(awake_epoch)
            ):
                return dict(state)
        return self.ack_current(actor=actor)

    def record_host_signal(
        self,
        signal: str,
        active: bool | None,
        listener_session_id: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._locked_state() as state:
            previous_state = str(state.get("state") or "IDLE")
            timestamp = self._timestamp()
            state["listener_session_id"] = str(listener_session_id or "")[:180]
            if active is True and previous_state == "WAKE":
                state["activity_observed"] = True
                state["last_activity_at"] = timestamp
                state["wake_response_started_at"] = timestamp
                state["wake_wait_until"] = max(
                    int(state.get("wake_wait_until", 0)),
                    timestamp + self.response_grace_seconds,
                )
                return self._commit(
                    state,
                    previous_state=previous_state,
                    reason="WAKE_RESPONSE_STARTED",
                    actor="listener",
                    host_signal=str(signal or "")[:120],
                    detail=detail,
                )
            if active is True and previous_state in {"AWAKE", "WORKING", "STATIC_DEBOUNCE"}:
                state["state"] = "WORKING"
                state["color"] = "yellow"
                state["state_entered_at"] = timestamp if previous_state != "WORKING" else state["state_entered_at"]
                state["last_activity_at"] = timestamp
                state["last_static_candidate_at"] = 0
                state["activity_observed"] = True
                return self._commit(
                    state,
                    previous_state=previous_state,
                    reason="HOST_ACTIVE",
                    actor="listener",
                    host_signal=str(signal or "")[:120],
                    detail=detail,
                )
            if active is False and previous_state == "WORKING" and bool(state.get("activity_observed")):
                state["state"] = "STATIC_DEBOUNCE"
                state["color"] = "green"
                state["state_entered_at"] = timestamp
                state["last_static_candidate_at"] = timestamp
                return self._commit(
                    state,
                    previous_state=previous_state,
                    reason="STATIC_CANDIDATE",
                    actor="listener",
                    host_signal=str(signal or "")[:120],
                    detail=detail,
                )
            return dict(state)

    def reset_statistics(
        self,
        *,
        actor: str,
        listener_session_id: str = "",
    ) -> dict[str, Any]:
        with self._locked_state() as state:
            previous_state = str(state.get("state") or "IDLE")
            timestamp = self._timestamp()
            state["enabled"] = False
            state["state"] = "IDLE"
            state["color"] = "gray"
            state["cycle_id"] = 0
            state["awake_epoch"] = 0
            state["wake_id"] = ""
            state["wake_attempt"] = 0
            state["send_required"] = False
            state["started_at"] = 0
            state["state_entered_at"] = timestamp
            state["listener_session_id"] = str(listener_session_id or "")[:180]
            state["last_ack_at"] = 0
            state["last_activity_at"] = 0
            state["last_static_candidate_at"] = 0
            state["last_wake_sent_at"] = 0
            state["last_acked_wake_id"] = ""
            state["activity_observed"] = False
            state["stop_reason"] = "statistics_reset"
            state["error_code"] = ""
            state["counters"] = {
                "cycles_started": 0,
                "wakes_sent": 0,
                "wakes_acked": 0,
                "retries": 0,
                "errors": 0,
            }
            return self._commit(
                state,
                previous_state=previous_state,
                reason="STATISTICS_RESET",
                actor=str(actor or "unknown")[:80],
            )

    def read_log(self, limit: int = 100) -> dict[str, Any]:
        bounded = max(1, min(int(limit or 100), 1000))
        if not self.log_path.exists():
            return {"entries": [], "count": 0}
        entries: list[dict[str, Any]] = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                entries.append(item)
        entries = entries[-bounded:]
        return {"entries": entries, "count": len(entries)}
