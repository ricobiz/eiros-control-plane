from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

from .runpod import WorkerState, WorkerStatus


class RunPodApiError(RuntimeError):
    pass


class RunPodRestLifecycle:
    BASE = 'https://rest.runpod.io/v1/pods'

    def __init__(self, api_key: str, pod_id: str, *, opener=urlopen, sleep=time.sleep, max_polls: int = 24, poll_seconds: float = 5.0):
        if not api_key:
            raise ValueError('RunPod API key is required')
        if not pod_id:
            raise ValueError('RunPod pod id is required')
        self._api_key = api_key
        self.pod_id = pod_id
        self._opener = opener
        self._sleep = sleep
        self.max_polls = max(1, int(max_polls))
        self.poll_seconds = max(0.0, float(poll_seconds))

    def _request(self, method: str, suffix: str = '') -> dict:
        url = f'{self.BASE}/{self.pod_id}{suffix}'
        req = Request(url, method=method, headers={'Authorization': f'Bearer {self._api_key}', 'Accept': 'application/json'})
        try:
            with self._opener(req, timeout=30) as resp:
                raw = resp.read()
        except Exception as exc:
            raise RunPodApiError(f'RunPod API {method} {suffix or "/"} failed: {type(exc).__name__}') from exc
        if not raw:
            return {}
        try:
            return json.loads(raw.decode('utf-8'))
        except Exception as exc:
            raise RunPodApiError('RunPod API returned invalid JSON') from exc

    @staticmethod
    def _endpoint(payload: dict) -> tuple[str, int] | None:
        host = payload.get('publicIp')
        mappings = payload.get('portMappings') or {}
        port = mappings.get('22') or mappings.get(22)
        if host and port:
            return str(host), int(port)
        return None

    def ensure_running(self, target_file: str | Path) -> WorkerStatus:
        payload = self._request('GET')
        desired = str(payload.get('desiredStatus') or '').upper()
        if desired != 'RUNNING':
            self._request('POST', '/start')
        target_file = Path(target_file)
        for _ in range(self.max_polls):
            payload = self._request('GET')
            endpoint = self._endpoint(payload)
            if str(payload.get('desiredStatus') or '').upper() == 'RUNNING' and endpoint:
                host, port = endpoint
                target_file.parent.mkdir(parents=True, exist_ok=True)
                tmp = target_file.with_suffix(target_file.suffix + '.tmp')
                tmp.write_text(json.dumps({'host': host, 'port': port}, indent=2) + '\n', encoding='utf-8')
                tmp.replace(target_file)
                return WorkerStatus(WorkerState.RUNNING, f'{host}:{port}')
            self._sleep(self.poll_seconds)
        return WorkerStatus(WorkerState.UNKNOWN)

    def stop_compute(self) -> None:
        self._request('POST', '/stop')
