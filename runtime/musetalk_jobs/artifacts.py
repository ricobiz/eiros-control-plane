from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path


class ArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class InputPaths:
    video: Path
    audio: Path


class ArtifactStore:
    VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.avi', '.webm'}
    AUDIO_EXTS = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg'}

    def __init__(self, root: str | Path, *, max_video_bytes: int = 2_000_000_000, max_audio_bytes: int = 500_000_000):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_video_bytes = int(max_video_bytes)
        self.max_audio_bytes = int(max_audio_bytes)

    def _job_dir(self, job_id: str) -> Path:
        try:
            normalized = str(uuid.UUID(str(job_id)))
        except Exception as exc:
            raise ArtifactError('invalid job id') from exc
        path = self.root / normalized
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _validate_file(path: Path, allowed_exts: set[str], max_bytes: int, label: str) -> None:
        if not path.is_file():
            raise ArtifactError(f'{label} file missing')
        if path.suffix.lower() not in allowed_exts:
            raise ArtifactError(f'unsupported {label} extension: {path.suffix}')
        size = path.stat().st_size
        if size <= 0:
            raise ArtifactError(f'{label} file is empty')
        if size > max_bytes:
            raise ArtifactError(f'{label} file exceeds size limit')

    @staticmethod
    def _copy_atomic(src: Path, dst: Path) -> None:
        tmp = dst.with_name(dst.name + '.tmp')
        with src.open('rb') as rf, tmp.open('wb') as wf:
            shutil.copyfileobj(rf, wf, length=1024 * 1024)
            wf.flush()
            os.fsync(wf.fileno())
        os.replace(tmp, dst)

    def stage_inputs(self, job_id: str, video: str | Path, audio: str | Path) -> InputPaths:
        video = Path(video)
        audio = Path(audio)
        self._validate_file(video, self.VIDEO_EXTS, self.max_video_bytes, 'video')
        self._validate_file(audio, self.AUDIO_EXTS, self.max_audio_bytes, 'audio')
        job_dir = self._job_dir(job_id)
        video_dst = job_dir / ('input' + video.suffix.lower())
        audio_dst = job_dir / ('input' + audio.suffix.lower())
        self._copy_atomic(video, video_dst)
        self._copy_atomic(audio, audio_dst)
        return InputPaths(video_dst, audio_dst)

    def output_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / 'result.mp4'

    def commit_output(self, job_id: str, temp_path: str | Path) -> Path:
        src = Path(temp_path)
        if not src.is_file() or src.stat().st_size <= 0:
            raise ArtifactError('rendered output missing or empty')
        if src.suffix.lower() != '.mp4':
            raise ArtifactError('rendered output must be mp4')
        dst = self.output_path(job_id)
        self._copy_atomic(src, dst)
        return dst
