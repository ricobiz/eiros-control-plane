from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont

from runtime import collab, events, queue, sam

BASE = Path('/var/lib/eiros-companion')
HLS = BASE / 'hls'
WIDTH, HEIGHT, FPS = 640, 360, 2
LOCAL_TZ = ZoneInfo('Asia/Phnom_Penh')
COMPANION_VERSION = '1.3-sam-video-pip'
FONT_REG = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FONT_BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

app = FastAPI(title='EIROS Companion', docs_url=None, redoc_url=None)
app.mount('/hls', StaticFiles(directory=str(HLS)), name='hls')
_lock = threading.Lock()
_state: dict[str, Any] = {}
_stream_started = False


def _font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


F_TITLE = _font(FONT_BOLD, 34)
F_BIG = _font(FONT_BOLD, 54)
F_MED = _font(FONT_BOLD, 23)
F_TEXT = _font(FONT_REG, 20)
F_SMALL = _font(FONT_REG, 16)


def collect_state() -> dict[str, Any]:
    now = int(time.time())
    pulse = events.status(30, 'default')
    room = collab.room_snapshot('eiros-hub', 'first-contact', 30, 0)
    hub = collab.hub_status()
    qstore = queue.read_store()

    leader = pulse.get('leader') or {}
    lease_until = int(leader.get('lease_until') or 0)
    last_seen = int(leader.get('last_seen') or 0)
    pulse_live = (lease_until >= now - 5) or (last_seen >= now - 20)
    pulse_sleeping = (not pulse_live) and last_seen > 0 and (now - last_seen) <= 900
    pulse_state = 'LIVE' if pulse_live else ('SLEEP' if pulse_sleeping else 'OFF')
    evs = list(pulse.get('events') or [])
    latest = max(evs, key=lambda e: int(e.get('seq') or 0), default={})

    history = room.get('history') or {}
    messages = list(history.get('messages') or [])
    agents = list((hub or {}).get('agents') or [])
    listener_surface = sam._listener_surface_snapshot({'agents': agents}, max_age=20)
    online = sum(1 for a in agents if str(a.get('status') or '').startswith('online'))

    tasks = list((qstore or {}).get('tasks') or [])
    terminal = {'completed', 'failed', 'cancelled'}
    active_tasks = sum(1 for t in tasks if str(t.get('status') or '') not in terminal)

    # Companion presence belongs to the current ChatGPT endpoint. Do not keep it
    # ringing because another agent (for example Claude) has an old pending call.
    pending_calls = sum(
        int(a.get('pending_calls') or 0)
        for a in agents
        if str(a.get('agent_id') or '') == 'chatgpt'
    )
    active_event_states = {'pending', 'queued', 'in_flight', 'awaiting_ack', 'retry_ready'}
    addressed_events = [
        e for e in evs
        if str(e.get('status') or '') in active_event_states
        and str((e.get('payload') or {}).get('to_agent') or 'chatgpt') == 'chatgpt'
    ]
    pending_events = len(addressed_events)
    # Global Companion is alive whenever this server-rendered stream is alive.
    # ChatGPT iframe availability is a separate secondary state.
    if pending_calls:
        mode = 'RINGING'
    elif pending_events:
        mode = 'WAKE'
    else:
        mode = 'ONLINE'
    chatgpt_state = 'LIVE' if pulse_state == 'LIVE' else ('SLEEP' if pulse_state == 'SLEEP' else 'OFF')

    return {
        'ok': True,
        'version': COMPANION_VERSION,
        'updated_at': now,
        'mode': mode,
        'chatgpt_state': chatgpt_state,
        'bridge_live': bool(listener_surface.get('active')),
        'bridge_video_pip_active': bool(listener_surface.get('video_pip_active')),
        'bridge_mode': str(listener_surface.get('mode') or 'offline'),
        'bridge_session_id': listener_surface.get('session_id'),
        'bridge_age_seconds': listener_surface.get('age_seconds'),
        'pulse_live': pulse_live,
        'pulse_sleeping': pulse_sleeping,
        'pulse_state': pulse_state,
        'pulse_age_seconds': max(0, now - last_seen) if last_seen else None,
        'pulse_pending': pending_events,
        'latest_seq': int(pulse.get('latest_seq') or 0),
        'room_ready': True,
        'room_messages': len(messages),
        'queue_active': active_tasks,
        'hub_online': online,
        'hub_total': len(agents),
        'pending_calls': pending_calls,
        'latest_event': {
            'seq': int(latest.get('seq') or 0),
            'status': str(latest.get('status') or 'none'),
            'source': str(latest.get('source') or 'quiet'),
        },
    }


def _rounded(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def render_frame(st: dict[str, Any]) -> Image.Image:
    im = Image.new('RGB', (WIDTH, HEIGHT), '#02060b')
    d = ImageDraw.Draw(im)
    _rounded(d, (14, 14, 626, 346), 28, '#07111c', '#173a56', 2)

    pstate = str(st.get('pulse_state') or ('LIVE' if st.get('pulse_live') else 'OFF'))
    status_color = '#35dc8c' if pstate == 'LIVE' else ('#f5b849' if pstate == 'SLEEP' else '#ff657a')
    mode = str(st.get('mode') or 'LISTENING')
    mode_color = '#ff657a' if mode == 'RINGING' else ('#f5b849' if mode == 'WAKE' else '#5ee49a')

    # Top band is the safest readable area under iOS PiP controls.
    _rounded(d, (34, 28, 606, 108), 20, '#0a1a2b', '#245978', 2)
    d.ellipse((52, 52, 74, 74), fill=mode_color)
    d.text((88, 37), 'EIROS', font=F_TITLE, fill='#eef7ff')
    d.text((91, 76), 'GLOBAL ' + mode, font=F_SMALL, fill='#7ea5c7')
    d.text((478, 47), f"#{st.get('latest_seq', 0)}", font=F_MED, fill='#75d9ff')

    # The central system button may cover this area. Keep the label explicit:
    # EIROS remains online; only the ChatGPT iframe may be asleep.
    label = 'CHATGPT'
    label_w = d.textlength(label, font=F_SMALL)
    d.text(((WIDTH-label_w)/2, 112), label, font=F_SMALL, fill='#648bac')
    state_w = d.textlength(pstate, font=F_BIG)
    d.text(((WIDTH - state_w) / 2, 133), pstate, font=F_BIG, fill=status_color)
    if pstate == 'SLEEP':
        age = int(st.get('pulse_age_seconds') or 0)
        sleep_hint = f'CHATGPT IFRAME ASLEEP · {max(1, age//60)}m'
        hint_w = d.textlength(sleep_hint, font=F_SMALL)
        d.text(((WIDTH - hint_w) / 2, 175), sleep_hint, font=F_SMALL, fill='#b9923e')
    elif pstate == 'OFF':
        off_hint = 'LISTENER OFFLINE'
        hint_w = d.textlength(off_hint, font=F_SMALL)
        d.text(((WIDTH - hint_w) / 2, 175), off_hint, font=F_SMALL, fill='#b94f60')
    elif st.get('bridge_video_pip_active'):
        bridge_hint = 'WAKE BRIDGE · VIDEO PIP ACTIVE'
        hint_w = d.textlength(bridge_hint, font=F_SMALL)
        d.text(((WIDTH - hint_w) / 2, 175), bridge_hint, font=F_SMALL, fill='#35dc8c')
    elif st.get('bridge_live'):
        bridge_hint = 'WAKE BRIDGE · INLINE ONLY'
        hint_w = d.textlength(bridge_hint, font=F_SMALL)
        d.text(((WIDTH - hint_w) / 2, 175), bridge_hint, font=F_SMALL, fill='#f5b849')

    # Secondary details remain useful in expanded PiP; no critical data depends on them.
    cards = [
        ('ROOM', 'READY', f"msg {st.get('room_messages',0)}"),
        ('QUEUE', str(st.get('queue_active',0)), 'tasks'),
        ('HUB', f"{st.get('hub_online',0)}/{st.get('hub_total',0)}", 'online'),
    ]
    boxes = [(34, 202, 188, 282), (243, 202, 397, 282), (452, 202, 606, 282)]
    for box, (k, v, sub) in zip(boxes, cards):
        _rounded(d, box, 17, '#081523', '#183b58', 2)
        x1,y1,_,_=box
        d.text((x1+14, y1+9), k, font=F_SMALL, fill='#648bac')
        d.text((x1+14, y1+33), v, font=F_MED, fill='#5ee49a')
        d.text((x1+14, y1+59), sub, font=F_SMALL, fill='#7899b8')

    # Scrubber-safe footer: useful after controls fade, disposable while they are visible.
    ev = st.get('latest_event') or {}
    _rounded(d, (34, 294, 606, 330), 14, '#06101a', '#183b58', 2)
    d.text((50, 302), f"LATEST #{ev.get('seq',0)} · {ev.get('status','none')}", font=F_SMALL, fill='#dcecff')
    d.text((414, 302), str(ev.get('source','quiet'))[:22], font=F_SMALL, fill='#7ea5c7')
    age = st.get('pulse_age_seconds')
    if age is None:
        age_text = ''
    elif int(age) < 60:
        age_text = f" · {int(age)}s"
    else:
        age_text = f" · {max(1, int(age)//60)}m"
    local_clock = datetime.fromtimestamp(float(st.get('updated_at', time.time())), LOCAL_TZ).strftime('%H:%M:%S')
    d.text((42, 334), local_clock + ' · UTC+7' + age_text, font=F_SMALL, fill='#466b8b')
    d.text((498, 334), 'EIROS 1.3', font=F_SMALL, fill='#466b8b')
    return im

def stream_loop() -> None:
    HLS.mkdir(parents=True, exist_ok=True)
    for p in HLS.glob('*'):
        try: p.unlink()
        except OSError: pass

    cmd = [
        '/usr/bin/ffmpeg', '-hide_banner', '-loglevel', 'warning',
        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', 'pipe:0',
        '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency',
        '-pix_fmt', 'yuv420p', '-profile:v', 'main', '-level', '3.1',
        '-g', str(FPS * 2), '-keyint_min', str(FPS * 2), '-sc_threshold', '0',
        '-b:v', '650k', '-maxrate', '800k', '-bufsize', '1200k',
        '-f', 'hls', '-hls_time', '2', '-hls_list_size', '6',
        '-hls_flags', 'delete_segments+append_list+omit_endlist+independent_segments',
        '-hls_segment_filename', str(HLS / 'segment-%06d.ts'), str(HLS / 'live.m3u8')
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        while True:
            try:
                st = collect_state()
            except Exception as exc:
                st = {'ok': False, 'mode': 'DEGRADED', 'pulse_live': False, 'updated_at': int(time.time()), 'error': str(exc)}
            with _lock:
                _state.clear(); _state.update(st)
            frame = render_frame(st).tobytes()
            for _ in range(FPS):
                if proc.stdin is None: return
                proc.stdin.write(frame)
            if proc.stdin:
                proc.stdin.flush()
            time.sleep(1)
    finally:
        if proc.stdin:
            try: proc.stdin.close()
            except OSError: pass
        proc.terminate()


PAGE = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover"><meta name="theme-color" content="#02060b"><title>EIROS Companion</title><style>
:root{color-scheme:dark;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:#02060b;color:#eef7ff;padding:calc(env(safe-area-inset-top) + 18px) 18px calc(env(safe-area-inset-bottom) + 24px)}main{max-width:780px;margin:auto}.head{display:flex;align-items:center;gap:12px;margin:8px 0 18px}.dot{width:12px;height:12px;border-radius:50%;background:#35dc8c;box-shadow:0 0 16px #35dc8c}.title{font-size:28px;font-weight:800}.sub{color:#7899b8;margin-top:3px}.panel{border:1px solid #173a56;border-radius:24px;background:#07111c;padding:14px;box-shadow:0 24px 80px #0008}video{width:100%;display:block;border-radius:18px;background:#000;aspect-ratio:16/9}.actions{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}button{min-height:58px;border-radius:17px;border:1px solid #245978;background:#0a1a2b;color:#dcecff;font-size:17px;font-weight:750}.primary{background:#48dff1;color:#00141a;border-color:#48dff1}.status{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:14px}.card{padding:14px;border:1px solid #173a56;border-radius:17px;background:#06101a}.k{font-size:11px;letter-spacing:.14em;color:#648bac}.v{font-size:22px;font-weight:800;margin-top:7px}.note{color:#7899b8;line-height:1.5;margin:16px 4px 0;font-size:14px}@media(max-width:520px){.actions{grid-template-columns:1fr}.title{font-size:24px}}</style></head><body><main><div class="head"><span class="dot"></span><div><div class="title">EIROS Companion</div><div class="sub">Global iOS presence · server HLS</div></div></div><div class="panel"><video id="v" autoplay muted playsinline controls preload="auto" src="hls/live.m3u8"></video><div class="actions"><button id="pip" class="primary">Launch Global PiP</button><button id="reload">Reload stream</button></div><div class="status"><div class="card"><div class="k">MODE</div><div id="mode" class="v">CONNECTING</div></div><div class="card"><div class="k">UPDATED</div><div id="updated" class="v">—</div></div></div><div class="note">Оставь PiP активным и переходи в ChatGPT, Telegram, карты или любое другое приложение. Видеопоток формируется на VPS, поэтому статусы продолжают обновляться независимо от фонового JavaScript браузера.</div></div></main><script>
const v=document.getElementById('v'), pip=document.getElementById('pip');
function arm(){try{v.muted=true;v.play().catch(()=>{})}catch(e){}}
['pointerdown','touchstart'].forEach(x=>pip.addEventListener(x,arm,{passive:true}));
pip.addEventListener('click',()=>{arm();try{if(typeof v.webkitSetPresentationMode==='function'){v.webkitSetPresentationMode('picture-in-picture')}else if(v.requestPictureInPicture){v.requestPictureInPicture()}}catch(e){pip.textContent='Tap again for PiP'}});
document.getElementById('reload').onclick=()=>{v.src='hls/live.m3u8?t='+Date.now();arm()};
async function tick(){try{const s=await fetch('state',{cache:'no-store'}).then(r=>r.json());document.getElementById('mode').textContent=s.mode||'—';document.getElementById('updated').textContent=new Date((s.updated_at||0)*1000).toLocaleTimeString()}catch(e){document.getElementById('mode').textContent='OFFLINE'}}
setInterval(tick,2000);tick();arm();
</script></body></html>'''


@app.on_event('startup')
def startup() -> None:
    global _stream_started
    if not _stream_started:
        _stream_started = True
        threading.Thread(target=stream_loop, daemon=True, name='eiros-hls').start()


@app.get('/', response_class=HTMLResponse)
def index() -> str:
    return PAGE


@app.get('/state')
def state() -> JSONResponse:
    with _lock:
        data = dict(_state) if _state else collect_state()
    return JSONResponse(data, headers={'Cache-Control': 'no-store'})


@app.get('/health')
def health() -> dict[str, Any]:
    return {'ok': True, 'stream': (HLS / 'live.m3u8').exists(), 'updated_at': int(time.time())}
