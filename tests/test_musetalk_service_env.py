import os
from runtime.musetalk_jobs import service


def test_runtime_env_accepts_operator_names(monkeypatch):
    monkeypatch.setenv('RUNPOD_API_KEY','secret')
    monkeypatch.setenv('RUNPOD_POD_ID','pod-x')
    monkeypatch.setenv('MUSETALK_RUNPOD_TARGET','/tmp/target.json')
    monkeypatch.setenv('MUSETALK_RUNPOD_KEY','/tmp/key')
    monkeypatch.setenv('MUSETALK_IDLE_GRACE_SECONDS','77')
    cfg=service.runtime_config_from_env()
    assert cfg['api_key']=='secret'
    assert cfg['pod_id']=='pod-x'
    assert cfg['target_file']=='/tmp/target.json'
    assert cfg['key_file']=='/tmp/key'
    assert cfg['idle_grace']==77
