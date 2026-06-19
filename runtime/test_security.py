from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def run(code:str,data_root:Path):
 env=dict(os.environ); env['EIROS_DATA_DIR']=str(data_root); env['PYTHONPATH']=str(ROOT)
 return subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)

def main():
 checks=[]
 with tempfile.TemporaryDirectory(prefix='eiros-policy-test-') as temp:
  data=Path(temp)
  init=run("from runtime.bootstrap import bootstrap; bootstrap()",data)
  assert init.returncode==0,init.stderr
  disabled=run("from runtime import security; import json\ntry: security.require_operator('test'); v=False\nexcept PermissionError: v=True\nprint(json.dumps({'blocked':v,'mode':security.mode()}))",data)
  assert json.loads(disabled.stdout)=={'blocked':True,'mode':'disabled'}
  checks.append('new instance commands disabled')
  path=data/'config'/'instance.json'; cfg=json.loads(path.read_text()); cfg['security']={'shell_mode':'operator','allow_local_shell_tasks':True}; path.write_text(json.dumps(cfg))
  enabled=run("from runtime import security; import json\nsecurity.require_operator('test'); security.validate_local_action({'type':'shell','command':'echo ok'}); print(json.dumps({'mode':security.mode(),'local':security.local_commands_allowed()}))",data)
  assert enabled.returncode==0,enabled.stderr
  assert json.loads(enabled.stdout)=={'mode':'operator','local':True}
  checks.append('operator mode explicit')
 print(json.dumps({'ok':True,'checks':checks,'count':len(checks)},indent=2))

if __name__=='__main__': main()
