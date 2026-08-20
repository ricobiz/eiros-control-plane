from __future__ import annotations

from pathlib import Path

from .artifacts import ArtifactError, ArtifactStore
from .models import RenderJob
from .runpod import AttemptState, RemoteAttempt, RunPodProvider


class MuseTalkRunner:
    def __init__(self, artifacts: ArtifactStore, provider: RunPodProvider, *, musetalk_root: str = '/workspace/MuseTalk'):
        self.artifacts = artifacts
        self.provider = provider
        self.musetalk_root = musetalk_root.rstrip('/')

    def remote_dir(self, job: RenderJob) -> str:
        return f'/workspace/eiros_jobs/{job.job_id}/{job.attempt_token}'

    def remote_config(self, job: RenderJob) -> str:
        return f'{self.remote_dir(job)}/config.yaml'

    def remote_output(self, job: RenderJob) -> str:
        return f'{self.remote_dir(job)}/result.mp4'

    def _local_inputs(self, job: RenderJob) -> tuple[Path, Path]:
        job_dir = self.artifacts.output_path(job.job_id).parent
        videos = sorted(p for p in job_dir.glob('input.*') if p.suffix.lower() in self.artifacts.VIDEO_EXTS)
        audios = sorted(p for p in job_dir.glob('input.*') if p.suffix.lower() in self.artifacts.AUDIO_EXTS)
        if len(videos) != 1 or len(audios) != 1:
            raise ArtifactError('job inputs are incomplete or ambiguous')
        return videos[0], audios[0]

    def _write_local_config(self, job: RenderJob) -> Path:
        d = self.remote_dir(job)
        cfg = self.artifacts.output_path(job.job_id).parent / 'remote-config.yaml'
        cfg.write_text(
            'task_0:\n'
            f' video_path: "{d}/input.mp4"\n'
            f' audio_path: "{d}/input.wav"\n',
            encoding='utf-8',
        )
        return cfg

    def stage(self, job: RenderJob) -> None:
        video, audio = self._local_inputs(job)
        self.provider.stage(video, f'{self.remote_dir(job)}/input.mp4')
        self.provider.stage(audio, f'{self.remote_dir(job)}/input.wav')
        self.provider.stage(self._write_local_config(job), self.remote_config(job))

    def command_for(self, job: RenderJob) -> list[str]:
        d = self.remote_dir(job)
        generated = f'{d}/render/v15/input_input.mp4'
        script = (
            f'cd {self.musetalk_root} && '
            f'/workspace/venvs/musetalk/bin/python -m scripts.inference '
            f'--inference_config {self.remote_config(job)} '
            f'--result_dir {d}/render '
            f'--unet_model_path {self.musetalk_root}/models/musetalkV15/unet.pth '
            f'--unet_config {self.musetalk_root}/models/musetalkV15/musetalk.json '
            f'--version v15 && '
            f'test -s {generated} && mv -f {generated} {self.remote_output(job)}'
        )
        return ['/bin/bash', '-lc', script]

    def inspect_or_start(self, job: RenderJob) -> RemoteAttempt:
        current = self.provider.inspect_attempt(job.job_id, job.attempt_token)
        if current.state is not AttemptState.MISSING:
            return current
        self.stage(job)
        return self.provider.launch(job.job_id, job.attempt_token, self.command_for(job))

    def collect(self, job: RenderJob) -> Path:
        remote = self.provider.inspect_attempt(job.job_id, job.attempt_token)
        if remote.state is not AttemptState.SUCCEEDED:
            raise RuntimeError(f'attempt is not complete: {remote.state.value}')
        remote_path = remote.output_path or self.remote_output(job)
        temp = self.artifacts.output_path(job.job_id).with_suffix('.download.tmp.mp4')
        self.provider.collect(remote_path, temp)
        try:
            return self.artifacts.commit_output(job.job_id, temp)
        finally:
            temp.unlink(missing_ok=True)
