from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, Sequence


class WorkerState(StrEnum):
    RUNNING = 'running'
    STOPPED = 'stopped'
    UNKNOWN = 'unknown'


class AttemptState(StrEnum):
    MISSING = 'missing'
    RUNNING = 'running'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class WorkerStatus:
    state: WorkerState
    endpoint: str = ''


@dataclass(frozen=True)
class RemoteAttempt:
    state: AttemptState
    exit_code: int | None = None
    output_path: str = ''
    detail: str = ''


class RunPodLifecycle(Protocol):
    def ensure_running(self, target_file: Path) -> WorkerStatus: ...
    def stop_compute(self) -> None: ...


class RunPodProvider(Protocol):
    def ensure_running(self) -> WorkerStatus: ...
    def inspect_attempt(self, job_id: str, attempt_token: str) -> RemoteAttempt: ...
    def stage(self, local_path: Path, remote_path: str) -> None: ...
    def launch(self, job_id: str, attempt_token: str, command: Sequence[str]) -> RemoteAttempt: ...
    def collect(self, remote_path: str, local_path: Path) -> None: ...
    def stop_compute(self) -> None: ...


class SshRunPodProvider:
    """Direct SSH worker adapter; lifecycle start/stop is supplied separately.

    Job state never stores the endpoint. The provider rereads target JSON for each
    operation so migration/endpoint refresh is orthogonal to job durability.
    """

    def __init__(
        self,
        target_file: str | Path,
        key_file: str | Path,
        *,
        start_command: Sequence[str] | None = None,
        stop_command: Sequence[str] | None = None,
        lifecycle: RunPodLifecycle | None = None,
    ):
        self.target_file = Path(target_file)
        self.key_file = Path(key_file)
        self.start_command = list(start_command or [])
        self.stop_command = list(stop_command or [])
        self.lifecycle = lifecycle

    def _target(self) -> tuple[str, int]:
        data = json.loads(self.target_file.read_text(encoding='utf-8'))
        return str(data['host']), int(data['port'])

    def _ssh_base(self) -> list[str]:
        host, port = self._target()
        return [
            '/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
            '-o', 'StrictHostKeyChecking=no', '-i', str(self.key_file), '-p', str(port), f'root@{host}'
        ]

    def _run_remote(self, script: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(self._ssh_base() + [script], text=True, capture_output=True, timeout=timeout)

    def ensure_running(self) -> WorkerStatus:
        probe = None
        try:
            probe = self._run_remote('echo OK', timeout=15)
        except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError, OSError, subprocess.TimeoutExpired):
            probe = None
        if probe is not None and probe.returncode == 0:
            host, port = self._target()
            return WorkerStatus(WorkerState.RUNNING, f'{host}:{port}')
        if self.lifecycle is not None:
            pub = self.key_file.with_suffix('.pub')
            repair = getattr(self.lifecycle, 'ensure_public_key', None)
            if callable(repair) and pub.is_file():
                repair(pub.read_text(encoding='utf-8').strip())
            status = self.lifecycle.ensure_running(self.target_file)
            if status.state is not WorkerState.RUNNING:
                return status
            for _ in range(12):
                probe = self._run_remote('echo OK', timeout=15)
                if probe.returncode == 0:
                    host, port = self._target()
                    return WorkerStatus(WorkerState.RUNNING, f'{host}:{port}')
                import time as _time
                _time.sleep(2)
            return WorkerStatus(WorkerState.UNKNOWN)
        if self.start_command:
            subprocess.run(self.start_command, check=True, timeout=120)
            host, port = self._target()
            return WorkerStatus(WorkerState.RUNNING, f'{host}:{port}')
        return WorkerStatus(WorkerState.UNKNOWN)

    @staticmethod
    def _remote_dir(job_id: str, attempt_token: str) -> str:
        return f'/workspace/eiros_jobs/{job_id}/{attempt_token}'

    def inspect_attempt(self, job_id: str, attempt_token: str) -> RemoteAttempt:
        d = self._remote_dir(job_id, attempt_token)
        script = (
            f"d={shlex.quote(d)}; "
            "if [ -f \"$d/exit_code\" ]; then rc=$(cat \"$d/exit_code\"); "
            "if [ \"$rc\" = 0 ]; then echo SUCCEEDED:$rc; else echo FAILED:$rc; fi; "
            "elif [ -f \"$d/pid\" ] && kill -0 $(cat \"$d/pid\") 2>/dev/null; then echo RUNNING; "
            "elif [ -d \"$d\" ]; then echo MISSING; else echo ABSENT; fi"
        )
        try:
            p = self._run_remote(script, timeout=20)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return RemoteAttempt(AttemptState.UNKNOWN, detail=str(exc))
        if p.returncode != 0:
            return RemoteAttempt(AttemptState.UNKNOWN, detail=(p.stderr or '')[-1000:])
        out = (p.stdout or '').strip()
        if out.startswith('SUCCEEDED:'):
            return RemoteAttempt(AttemptState.SUCCEEDED, int(out.split(':', 1)[1]), f'{d}/result.mp4')
        if out.startswith('FAILED:'):
            return RemoteAttempt(AttemptState.FAILED, int(out.split(':', 1)[1]))
        if out == 'RUNNING':
            return RemoteAttempt(AttemptState.RUNNING)
        return RemoteAttempt(AttemptState.MISSING)

    def stage(self, local_path: Path, remote_path: str) -> None:
        host, port = self._target()
        remote_parent = str(Path(remote_path).parent)
        p = self._run_remote(f'mkdir -p {shlex.quote(remote_parent)}', timeout=20)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or 'remote mkdir failed')[-2000:])
        subprocess.run([
            '/usr/bin/scp', '-q', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=no',
            '-i', str(self.key_file), '-P', str(port), str(local_path), f'root@{host}:{remote_path}'
        ], check=True, timeout=120)

    def launch(self, job_id: str, attempt_token: str, command: Sequence[str]) -> RemoteAttempt:
        existing = self.inspect_attempt(job_id, attempt_token)
        if existing.state in {AttemptState.RUNNING, AttemptState.SUCCEEDED, AttemptState.FAILED, AttemptState.UNKNOWN}:
            return existing
        d = self._remote_dir(job_id, attempt_token)
        quoted = ' '.join(shlex.quote(str(x)) for x in command)
        script = (
            f"d={shlex.quote(d)}; mkdir -p \"$d\"; "
            f"nohup bash -lc {shlex.quote(quoted + '; rc=$?; echo $rc > ' + d + '/exit_code; exit $rc')} "
            f">\"$d/stdout.log\" 2>\"$d/stderr.log\" < /dev/null & echo $! > \"$d/pid\""
        )
        try:
            p = self._run_remote(script, timeout=20)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return RemoteAttempt(AttemptState.UNKNOWN, detail=str(exc))
        if p.returncode != 0:
            return RemoteAttempt(AttemptState.UNKNOWN, detail=(p.stderr or '')[-1000:])
        return RemoteAttempt(AttemptState.RUNNING)

    def collect(self, remote_path: str, local_path: Path) -> None:
        host, port = self._target()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            '/usr/bin/scp', '-q', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=no',
            '-i', str(self.key_file), '-P', str(port), f'root@{host}:{remote_path}', str(local_path)
        ], check=True, timeout=120)

    def stop_compute(self) -> None:
        if self.lifecycle is not None:
            self.lifecycle.stop_compute()
            return
        if not self.stop_command:
            raise RuntimeError('RunPod stop command is not configured')
        subprocess.run(self.stop_command, check=True, timeout=120)
