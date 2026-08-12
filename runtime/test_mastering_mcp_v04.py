from __future__ import annotations

import runtime.mastering_mcp_server as s


def test_health_advertises_director_and_verification():
    h=s.mastering_health()
    assert h['director_engine_version']=='0.4.0-director'
    assert h['verification_schema_version']==1


def test_plan_create_and_get_contract(monkeypatch):
    monkeypatch.setattr(s.mastering_engine,'save_director_plan',lambda aid,plan:{'plan_id':'p1','fingerprint':'fp','intent':plan['intent']})
    monkeypatch.setattr(s.mastering_engine,'get_director_plan',lambda aid,pid:{'plan_id':pid,'fingerprint':'fp'})
    created=s.mastering_plan_create('a'*32,{'intent':'preserve'})
    assert created['plan']['plan_id']=='p1'
    got=s.mastering_plan_get('a'*32,'p1')
    assert got['plan']['plan_id']=='p1'


def test_directed_render_verify_approve_contract(monkeypatch):
    monkeypatch.setattr(s.mastering_engine,'render',lambda aid,**kw:{'ok':True,'asset_id':aid,'output':{'output_id':'o1','state':'RENDERED','plan_id':kw['director_plan_id']}})
    monkeypatch.setattr(s.mastering_engine,'verify_output',lambda aid,oid:{'ok':True,'asset_id':aid,'output_id':oid,'state':'VERIFIED','verification':{'status':'PASS'}})
    monkeypatch.setattr(s.mastering_engine,'approve_output',lambda aid,oid:{'ok':True,'asset_id':aid,'output':{'output_id':oid,'state':'APPROVED'}})
    r=s.mastering_render_directed('a'*32,'p1')
    assert r['output']['plan_id']=='p1'
    assert s.mastering_verify('a'*32,'o1')['verification']['status']=='PASS'
    assert s.mastering_approve('a'*32,'o1')['output']['state']=='APPROVED'


def test_metadata_memory_feedback_contract(monkeypatch):
    monkeypatch.setattr(s.mastering_engine,'audit_asset_metadata',lambda aid:{'ok':True,'asset_id':aid,'audit':{'optional_textual_tags':[]}})
    monkeypatch.setattr(s.mastering_engine,'experience_similar',lambda aid,tags,traits,limit:{'ok':True,'asset_id':aid,'matches':[{'score':.9}]})
    monkeypatch.setattr(s.mastering_engine,'record_feedback',lambda aid,oid,feedback,tags:{'ok':True,'asset_id':aid,'output_id':oid,'experience':{'rico_feedback':feedback}})
    assert s.mastering_metadata_audit('a'*32)['audit']['optional_textual_tags']==[]
    assert s.mastering_experience_similar('a'*32,['ritual'],['sub_mass'],5)['matches'][0]['score']==.9
    assert s.mastering_feedback_record('a'*32,'o1','approved',['ritual'])['experience']['rico_feedback']=='approved'


def test_http_handlers_exist_for_v04_panel_workflow():
    for name in ('api_plan_create','api_plan_get','api_render_directed','api_verify','api_approve','api_metadata_audit','api_experience_similar','api_feedback_record'):
        assert hasattr(s,name), name
