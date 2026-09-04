#!/usr/bin/env bash
# Finish the LAM avatar pipeline: resume pod, finish install, render OAC zip, pull it back.
# Idempotent: safe to re-run. Stops the pod at the end unless KEEP_POD=1.
# See docs/LAM_AVATAR_HANDOFF.md for why each step exists.
set -uo pipefail
POD=7r4emsgegttnxp
KEY=/root/.ssh/eiros_runpod
IMG=${IMG:-/workspace/ref_frontal_v1.jpg}
BLENDER=/workspace/software/blender-4.0.2-linux-x64/blender
set -a; . /etc/eiros/musetalk-jobs.env; set +a
gql(){ curl -s -X POST "https://api.runpod.io/graphql?api_key=$RUNPOD_API_KEY" -H 'Content-Type: application/json' -d "{\"query\":\"$1\"}"; }

echo "== balance =="; gql 'query { myself { clientBalance } }'

echo "== resume =="
gql "mutation { podResume(input:{podId:\\\"$POD\\\", gpuCount:1}) { id desiredStatus } }"

echo "== wait for ssh port (changes on every resume) =="
for i in $(seq 1 25); do
  P=$(gql "query { pod(input:{podId:\\\"$POD\\\"}) { runtime { ports { ip publicPort privatePort } } } }" \
      | python3 -c "import sys,json;r=json.load(sys.stdin)['data']['pod'].get('runtime');print(next((f\"{p['ip']} {p['publicPort']}\" for p in (r or {}).get('ports',[]) if p['privatePort']==22),''))")
  [ -n "$P" ] && break; sleep 10
done
[ -z "$P" ] && { echo "FATAL: no ssh port"; exit 1; }
HOST=${P% *}; PORT=${P#* }; echo "ssh $HOST:$PORT"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=20 -p $PORT root@$HOST"

echo "== finish python3.10 env (torch was interrupted mid-download) =="
$SSH bash -s <<'REMOTE'
set -x
cd /workspace/LAM
source /workspace/v310/bin/activate || { python3.10 -m venv /workspace/v310; source /workspace/v310/bin/activate; }
pip install -q -U pip wheel setuptools Cython
python -c "import torch" 2>/dev/null || pip install torch==2.3.0 torchvision==0.18.0 torchaudio==2.3.0 --index-url https://download.pytorch.org/whl/cu121 2>&1 | tail -2
python -c "import xformers" 2>/dev/null || pip install -U xformers==0.0.26.post1 --index-url https://download.pytorch.org/whl/cu121 2>&1 | tail -2
python -c "import pandas" 2>/dev/null || pip install -r requirements.txt 2>&1 | tail -4
python -c "import fbx" 2>/dev/null || pip install /workspace/LAM/fbx-2020.3.4-cp310-cp310-manylinux1_x86_64.whl 2>&1 | tail -2
pip install -q patool pathlib
[ -f external/landmark_detection/FaceBoxesV2/utils/nms/cpu_nms*.so ] || (cd external/landmark_detection/FaceBoxesV2/utils/ && sh make.sh 2>&1 | tail -3)
python -c "import torch,fbx,pandas;print('READY torch',torch.__version__,'cuda',torch.cuda.is_available())"
REMOTE

echo "== render OAC bundle =="
echo "NOTE: app_lam.py is a gradio app. Drive core_fn headlessly or launch it with"
echo "      --blender_path $BLENDER and enable_oac_file=True."
echo "      Output: /workspace/LAM/output/open_avatar_chat/<id>.zip"
$SSH "ls -la /workspace/LAM/output/open_avatar_chat/*.zip 2>/dev/null || echo 'no zip yet — run the render step'"

echo "== pull any zip back to the VPS + publish via vault =="
mkdir -p /var/lib/eiros/avatar-lam/output/oac
scp -i $KEY -o StrictHostKeyChecking=no -P $PORT "root@$HOST:/workspace/LAM/output/open_avatar_chat/*.zip" /var/lib/eiros/avatar-lam/output/oac/ 2>/dev/null \
  && for z in /var/lib/eiros/avatar-lam/output/oac/*.zip; do
       curl -s -X POST "http://127.0.0.1:8797/ui/api/upload" -F "file=@$z" | head -c 400; echo;
     done \
  || echo "nothing to pull yet"

if [ "${KEEP_POD:-0}" != "1" ]; then
  echo "== stop pod =="
  gql "mutation { podStop(input:{podId:\\\"$POD\\\"}) { id desiredStatus } }"
fi
echo "== balance after =="; gql 'query { myself { clientBalance } }'
