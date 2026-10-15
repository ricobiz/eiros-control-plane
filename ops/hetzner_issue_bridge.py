#!/usr/bin/env python3
"""GitHub Issues -> Hetzner recovery bridge. GitHub is out of band to EBRIDGE.

Private repository only. Owner login checked twice. Hard reset is not reachable
through issues (manual GitHub workflow + second confirmation only).
"""
import contextlib
import io
import json
import os
import sys
import urllib.request
import hetzner_oob

OWNER='ricobiz'
REPO='ricobiz/eiros-control-plane'
TITLES={
    '[EIROS-OOB] status':'status',
    '[EIROS-OOB] graceful_reboot':'graceful_reboot'
}

def main():
    if os.environ.get('GITHUB_REPOSITORY')!=REPO:raise RuntimeError('Unexpected GitHub repository')
    with open(os.environ['GITHUB_EVENT_PATH'],'r',encoding='utf8') as f:event=json.load(f)
    issue=event.get('issue') or {}
    if event.get('action')!='opened':raise RuntimeError('Only newly opened issues are valid')
    if (issue.get('user') or {}).get('login')!=OWNER:raise RuntimeError('Only repository owner may request VPS actions')
    if os.environ.get('GITHUB_ACTOR')!=OWNER:raise RuntimeError('GitHub trigger actor is not the owner')
    operation=TITLES.get(issue.get('title',''))
    if not operation:raise RuntimeError('Not an OOB operation')
    body=(issue.get('body') or '').strip()
    os.environ['OOB_ACTION']=operation
    os.environ['OOB_CONFIRMATION']=''
    os.environ['OOB_OVERRIDE_HEALTHY']='false'
    if operation=='graceful_reboot':
        expected='CONFIRM_GRACEFUL_REBOOT_ebridge_178.105.43.79'
        allowed={expected,expected+'\nOVERRIDE_HEALTHY=true'}
        if body not in allowed:raise RuntimeError('Missing exact reboot confirmation')
        os.environ['OOB_CONFIRMATION']=expected
        if body.endswith('OVERRIDE_HEALTHY=true'):os.environ['OOB_OVERRIDE_HEALTHY']='true'
    return issue['number']

def comment(issue_number,message):
    # Only sanitized diagnostic output; never print provider credential or headers.
    token=os.environ.get('GITHUB_TOKEN','')
    if not token:return
    data=json.dumps({'body':message[:4000]}).encode()
    req=urllib.request.Request(
        f'https://api.github.com/repos/{REPO}/issues/{issue_number}/comments',
        data=data,method='POST',
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                 'Content-Type':'application/json','User-Agent':'eiros-oob-recovery'})
    with urllib.request.urlopen(req,timeout=12) as r:
        if r.status!=201:raise RuntimeError('Unable to record provider result')

if __name__=='__main__':
    output=io.StringIO()
    issue_number=None
    try:
        issue_number=main()
        with contextlib.redirect_stdout(output):
            hetzner_oob.main()
        detail=output.getvalue()
        status=0
        label='SUCCESS'
    except Exception as exc:
        detail=output.getvalue()+'\n'+type(exc).__name__+': '+str(exc)
        status=1
        label='FAILED — no automatic retry'
    print(label+'\n'+detail)
    if issue_number is not None:
        try:comment(issue_number,'**EIROS OOB '+label+'**\n\n```text\n'+detail[:3000]+'\n```')
        except Exception as exc:print('Could not post result as issue comment: '+type(exc).__name__,file=sys.stderr)
    sys.exit(status)
