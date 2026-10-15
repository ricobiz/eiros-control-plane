#!/usr/bin/env python3
"""Independent Hetzner Cloud out-of-band VPS recovery. NO automatic power action."""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE='https://api.hetzner.cloud/v1'
NAME='ebridge'
IP='178.105.43.79'
HEALTH='https://vault.178-105-43-79.sslip.io/v2/health'

def api(method,path,token,payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    headers={'Authorization':'Bearer '+token,'Accept':'application/json'}
    if data is not None:headers['Content-Type']='application/json'
    req=urllib.request.Request(BASE+path,method=method,data=data,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=12) as r:return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'Hetzner API returned HTTP {e.code} for {method} {path}') from None
    except urllib.error.URLError:
        raise RuntimeError('Hetzner Cloud API is unreachable') from None

def find_target(token):
    found=[]
    for page in range(1,16):
        q=urllib.parse.urlencode({'page':page,'per_page':50})
        data=api('GET','/servers?'+q,token)
        for row in data.get('servers',[]):
            actual=((row.get('public_net') or {}).get('ipv4') or {}).get('ip')
            if row.get('name')==NAME and actual==IP:found.append(row)
        if not ((data.get('meta') or {}).get('pagination') or {}).get('next_page'):break
    else:raise RuntimeError('Safety limit on provider pagination exceeded')
    if len(found)!=1:raise RuntimeError(f'Expected exactly one server named {NAME} with IP {IP}, found {len(found)}')
    if not isinstance(found[0].get('id'),int):raise RuntimeError('Missing provider server ID')
    return found[0]

def public_health():
    try:
        with urllib.request.urlopen(HEALTH,timeout=8) as r:
            return r.status==200 and json.load(r).get('ok') is True
    except Exception:return False

def wait_for_action(token,server_id,action_id):
    for _ in range(20):
        result=api('GET',f'/servers/{server_id}/actions/{action_id}',token).get('action',{})
        state=result.get('status')
        if state=='success':return
        if state=='error':raise RuntimeError('Provider action failed; inspect Hetzner Console')
        if state!='running':raise RuntimeError('Unknown provider action status')
        time.sleep(4)
    raise RuntimeError('Provider action did not finish: inspect Hetzner Console before retrying')

def main():
    token=os.getenv('HCLOUD_TOKEN','')
    operation=os.getenv('OOB_ACTION','status')
    confirmation=os.getenv('OOB_CONFIRMATION','')
    override=os.getenv('OOB_OVERRIDE_HEALTHY','false').lower()=='true'
    if not token:raise RuntimeError('GitHub Actions secret HCLOUD_TOKEN is missing')
    if operation not in ('status','graceful_reboot','hard_reset'):raise RuntimeError('Unsupported operation')
    target=find_target(token)
    running=target.get('status')=='running'
    healthy=public_health()
    print(json.dumps({'server':NAME,'ip':IP,'provider_state':target.get('status'),
                      'public_vault_health':healthy,'operation':operation}))
    if operation=='status':
        print('DIAGNOSTIC_ONLY: server power unchanged')
        return
    if not running:raise RuntimeError('Refusing to reboot server that is not reported running')
    phrase='CONFIRM_'+operation.upper()+'_ebridge_178.105.43.79'
    if confirmation!=phrase:raise RuntimeError('Exact confirmation required: '+phrase)
    if healthy and not override:
        raise RuntimeError('VAULT public health is OK. Refusing reboot without explicit healthy override.')
    if operation=='hard_reset' and os.getenv('OOB_SECOND_APPROVAL')!='IRREVERSIBLE_POWER_CYCLE':
        raise RuntimeError('Hard reset requires additional exact approval: IRREVERSIBLE_POWER_CYCLE')
    command='reboot' if operation=='graceful_reboot' else 'reset'
    result=api('POST',f'/servers/{target["id"]}/actions/{command}',token,{})
    action_id=(result.get('action') or {}).get('id')
    if not isinstance(action_id,int):raise RuntimeError('Provider did not return an action ID; do not retry blindly')
    print(f'PROVIDER_ACTION_ACCEPTED command={command} action_id={action_id}')
    wait_for_action(token,target['id'],action_id)
    print('PROVIDER_ACTION_SUCCESS; still verify application and MCP services independently')

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('RECOVERY_FAILED: '+str(e),file=sys.stderr)
        sys.exit(1)
