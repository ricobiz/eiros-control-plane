from pathlib import Path
import pytest

from runtime.musetalk_jobs.artifacts import ArtifactStore, ArtifactError


def test_stage_inputs_uses_fixed_names_and_uuid_directory(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts', max_video_bytes=1000, max_audio_bytes=1000)
    video = tmp_path / 'weird name.mp4'; video.write_bytes(b'video')
    audio = tmp_path / 'voice.wav'; audio.write_bytes(b'audio')
    paths = store.stage_inputs('123e4567-e89b-12d3-a456-426614174000', video, audio)
    assert paths.video.name == 'input.mp4'
    assert paths.audio.name == 'input.wav'
    assert paths.video.parent.name == '123e4567-e89b-12d3-a456-426614174000'


def test_rejects_bad_extension_and_oversize(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts', max_video_bytes=4, max_audio_bytes=4)
    bad = tmp_path / 'x.txt'; bad.write_bytes(b'x')
    wav = tmp_path / 'x.wav'; wav.write_bytes(b'12345')
    mp4 = tmp_path / 'x.mp4'; mp4.write_bytes(b'1')
    with pytest.raises(ArtifactError): store.stage_inputs('123e4567-e89b-12d3-a456-426614174000', bad, mp4)
    with pytest.raises(ArtifactError): store.stage_inputs('123e4567-e89b-12d3-a456-426614174000', mp4, wav)


def test_commit_output_is_atomic_and_nonempty(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    job_id = '123e4567-e89b-12d3-a456-426614174000'
    temp = tmp_path / 'render.mp4'; temp.write_bytes(b'mp4data')
    final = store.commit_output(job_id, temp)
    assert final.name == 'result.mp4'
    assert final.read_bytes() == b'mp4data'
    empty = tmp_path / 'empty.mp4'; empty.write_bytes(b'')
    with pytest.raises(ArtifactError): store.commit_output(job_id, empty)


def test_rejects_non_uuid_job_id(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    src = tmp_path / 'x.mp4'; src.write_bytes(b'1')
    wav = tmp_path / 'x.wav'; wav.write_bytes(b'1')
    with pytest.raises(ArtifactError): store.stage_inputs('../../escape', src, wav)
