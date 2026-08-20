import json
from pathlib import Path

from runtime.musetalk_jobs.runpod_api import RunPodRestLifecycle


class Resp:
    def __init__(self, payload=None, status=200):
        self.payload=payload; self.status=status
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def read(self): return json.dumps(self.payload).encode() if self.payload is not None else b''


def test_start_refreshes_ssh_target_without_exposing_token(tmp_path: Path):
    calls=[]
    states=[
        {'id':'pod1','desiredStatus':'EXITED','publicIp':None,'portMappings':{}},
        {'id':'pod1','desiredStatus':'RUNNING','publicIp':'1.2.3.4','portMappings':{'22':23456}},
    ]
    def opener(req, timeout=0):
        calls.append((req.full_url, req.method, req.headers.get('Authorization')))
        if req.method=='POST': return Resp({'id':'pod1','desiredStatus':'RUNNING'})
        return Resp(states.pop(0))
    target=tmp_path/'target.json'
    life=RunPodRestLifecycle('secret-token','pod1',opener=opener,sleep=lambda _:None,max_polls=3)
    status=life.ensure_running(target)
    assert status.endpoint=='1.2.3.4:23456'
    assert json.loads(target.read_text())=={'host':'1.2.3.4','port':23456}
    assert all(c[2]=='Bearer secret-token' for c in calls)
    assert 'secret-token' not in target.read_text()


def test_stop_uses_only_stop_endpoint(tmp_path: Path):
    calls=[]
    def opener(req, timeout=0):
        calls.append((req.full_url, req.method))
        return Resp({'id':'pod1','desiredStatus':'EXITED'})
    life=RunPodRestLifecycle('tok','pod1',opener=opener,sleep=lambda _:None)
    life.stop_compute()
    assert calls==[('https://rest.runpod.io/v1/pods/pod1/stop','POST')]


def test_discovers_single_nonterminated_pod_when_id_omitted(tmp_path: Path):
    calls=[]
    def opener(req, timeout=0):
        calls.append((req.full_url, req.method))
        if req.full_url.endswith('/pods'):
            return Resp([{'id':'pod-one','name':'MuseTalk','desiredStatus':'EXITED'}])
        if req.full_url.endswith('/pod-one/start'):
            return Resp({'id':'pod-one','desiredStatus':'RUNNING'})
        return Resp({'id':'pod-one','desiredStatus':'RUNNING','publicIp':'5.6.7.8','portMappings':{'22':34567}})
    target=tmp_path/'target.json'
    life=RunPodRestLifecycle('tok','',opener=opener,sleep=lambda _:None,max_polls=2)
    status=life.ensure_running(target)
    assert life.pod_id=='pod-one'
    assert status.endpoint=='5.6.7.8:34567'
