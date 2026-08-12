from __future__ import annotations

import html
import json
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

from runtime import mastering as mastering_engine
from runtime.config import load_config
from runtime.version import __version__

CONFIG = load_config()
PUBLIC_ORIGIN = "https://178-105-43-79.sslip.io"
PUBLIC_PREFIX = "/mastering-85949c2f6885e19e8e815fd0faa0c3e097e88c7fc84a18d3"
PUBLIC_BASE = PUBLIC_ORIGIN + PUBLIC_PREFIX
PUBLIC_SHARE_BASE = PUBLIC_ORIGIN + "/s"
PANEL_URI = "ui://eiros/mastering-panel-v17-2.html"
DIAGNOSTIC_PANEL_URI = "ui://eiros/mastering-diagnostic-v1.html"
LEGACY_PANEL_URI = "ui://eiros/mastering-panel-v16.html"
LEGACY_PANEL_URI_V2 = "ui://eiros/mastering-panel-v15.html"

mcp = FastMCP(
    "EIROS Mastering",
    instructions=(
        "Dedicated remote audio mastering connector for Rico. "
        "Use open_mastering_panel for browser file upload and download. "
        "Analyze audio before rendering, preserve the source, and use conservative "
        "mastering targets unless Rico explicitly asks otherwise."
    ),
    stateless_http=True,
    json_response=True,
    host="127.0.0.1",
    port=8792,
    transport_security=TransportSecuritySettings(
        allowed_hosts=[
            "127.0.0.1",
            "127.0.0.1:*",
            "localhost",
            "localhost:*",
            "eiros.br-be.com",
            "eiros.br-be.com:*",
        ],
        allowed_origins=[
            "http://127.0.0.1",
            "http://127.0.0.1:*",
            "http://localhost",
            "http://localhost:*",
            "http://eiros.br-be.com",
            "https://eiros.br-be.com",
            "https://chatgpt.com",
            "https://chat.openai.com",
            "https://platform.openai.com",
        ],
    ),
)

PANEL_META: dict[str, Any] = {
    "ui": {
        "prefersBorder": True,
        "domain": PUBLIC_ORIGIN,
        "csp": {
            "connectDomains": [PUBLIC_ORIGIN],
            "resourceDomains": [PUBLIC_ORIGIN],
        },
    },
    "openai/widgetDescription": "Upload, analyze, master and download audio through EIROS Mastering.",
    "openai/widgetDomain": PUBLIC_ORIGIN,
    "openai/widgetCSP": {
        "connect_domains": [PUBLIC_ORIGIN],
        "resource_domains": [PUBLIC_ORIGIN],
    },
}


def _panel_v17_html() -> str:
    path = Path(__file__).with_name("mastering_panel_v17.html")
    template = path.read_text(encoding="utf-8")
    return template.replace("__PUBLIC_BASE__", PUBLIC_BASE).replace("__PUBLIC_SHARE_BASE__", PUBLIC_SHARE_BASE)


def _panel_html() -> str:
    template = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"/>
<style>
:root{
  color-scheme:dark;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif;
  --bg:#07080a;--panel:#0d0f12;--raised:#12151a;--line:#252931;--line2:#313640;
  --text:#eef0f4;--muted:#858d99;--dim:#626a75;--accent:#dfe3e8;--green:#3dd6aa;--red:#ef6a78
}
*{box-sizing:border-box}
html,body{margin:0;background:transparent;color:var(--text)}
body{-webkit-font-smoothing:antialiased}
button,input,select{font:inherit}
button,a,input,select{-webkit-tap-highlight-color:transparent}
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #8c96a5;outline-offset:2px}
.shell{
  min-height:520px;overflow:hidden;border:1px solid #252932;border-radius:20px;
  background:linear-gradient(180deg,#0e1014 0,#08090b 100%);
  box-shadow:0 18px 48px rgba(0,0,0,.28)
}
.head{
  min-height:68px;padding:14px 16px;border-bottom:1px solid #22262d;
  display:flex;align-items:center;justify-content:space-between;gap:12px;background:#0b0d10
}
.brand{display:flex;align-items:center;min-width:0;gap:11px}
.mark{
  width:35px;height:35px;display:grid;place-items:center;border:1px solid #3a3f48;border-radius:10px;
  background:#eef0f3;color:#090a0c;font-size:11px;font-weight:900;letter-spacing:-.04em
}
.title{font-size:14px;font-weight:800;letter-spacing:.02em}
.title span{color:#7f8793;font-weight:600}
.sub{margin-top:3px;color:#666e79;font-size:9px;letter-spacing:.08em;text-transform:uppercase}
.live{
  display:inline-flex;align-items:center;gap:6px;padding:5px 8px;border:1px solid #2a2f37;border-radius:999px;
  color:#9199a5;font-size:8px;font-weight:800;letter-spacing:.12em
}
.dot{width:6px;height:6px;border-radius:50%;background:var(--green);box-shadow:0 0 10px rgba(61,214,170,.45)}
.body{padding:11px;display:grid;gap:10px}
.card{border:1px solid var(--line);border-radius:15px;background:rgba(14,16,20,.94);padding:13px}
.sectionhead{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:11px}
.eyebrow{color:#656d79;font-size:8px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}
h2{margin:3px 0 0;font-size:14px;line-height:1.2;letter-spacing:-.01em}
.sectionhint{max-width:330px;margin-top:4px;color:#707885;font-size:10px;line-height:1.35}
.cap{
  flex:none;padding:4px 7px;border:1px solid #2a2f37;border-radius:7px;
  color:#737b87;font-size:8px;font-weight:700;letter-spacing:.06em;text-transform:uppercase
}
label{display:block;margin-bottom:6px;color:#8c94a0;font-size:10px;font-weight:650}
input[type=file],input[type=number],input[type=text],select{
  width:100%;height:38px;border:1px solid #303640;border-radius:9px;background:#090b0e;color:#e8ebef;padding:0 10px
}
input[type=file]{height:auto;min-height:42px;padding:5px 6px;color:#8a929e;font-size:11px}
input[type=file]::file-selector-button{
  min-height:30px;margin-right:9px;padding:0 10px;border:1px solid #333943;border-radius:7px;
  background:#171a1f;color:#dce0e6;font-size:10px;font-weight:700
}
select{appearance:auto}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.row{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}
button,.download{
  min-height:33px;display:inline-flex;align-items:center;justify-content:center;padding:0 11px;
  border:1px solid #dfe3e8;border-radius:8px;background:#e7eaee;color:#090a0c;
  font-size:10px;font-weight:800;line-height:1;text-decoration:none;cursor:pointer;transition:background .15s,border-color .15s,transform .15s
}
button:active,.download:active{transform:translateY(1px)}
button.secondary{border-color:#353b45;background:#171a1f;color:#d8dce2}
button.danger,.danger{border-color:#5a3037!important;background:#211216!important;color:#ef7a87!important}
button:disabled{opacity:.42;cursor:not-allowed;transform:none}
.status{margin-top:8px;color:#8a929e;font-size:10px;line-height:1.45;white-space:pre-wrap;word-break:break-word}
.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:10px}
.metric{min-height:58px;padding:9px;border:1px solid #272c34;border-radius:10px;background:#0a0c0f}
.metric b{display:block;color:#e5e8ed;font-size:14px;font-variant-numeric:tabular-nums}
.metric span{display:block;margin-top:4px;color:#68717d;font-size:8px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
.sourceDeck{margin-top:10px;padding:10px;border:1px solid #2b313a;border-radius:11px;background:#090b0e}
.sourceTransport{display:flex;align-items:center;gap:10px}
.sourcePlay{flex:0 0 38px;width:38px;height:38px;min-height:38px;padding:0;border-color:#3c434e;border-radius:50%;background:#171b20;color:#f0f2f5;font-size:14px}
.sourceTrack{min-width:0;flex:1}
.sourceSeek{--progress:0%;display:block;width:100%;height:18px;margin:0;appearance:none;background:transparent}
.sourceSeek::-webkit-slider-runnable-track{height:3px;border-radius:99px;background:linear-gradient(90deg,#dfe3e9 0 var(--progress),#30343b var(--progress) 100%)}
.sourceSeek::-webkit-slider-thumb{width:13px;height:13px;margin-top:-5px;appearance:none;border:2px solid #0d0f12;border-radius:50%;background:#f1f3f6;box-shadow:0 0 0 1px #5b626e}
.sourceClock{display:grid;grid-template-columns:42px 1fr 42px;margin-top:2px;color:#737c88;font-size:8px;font-variant-numeric:tabular-nums}
.sourceClock span:nth-child(2){text-align:center;font-weight:800;letter-spacing:.11em}
.sourceClock span:last-child{text-align:right}
.sourceDeck audio{display:none}
.signature{margin-top:10px;padding:10px;border:1px solid #293139;border-radius:11px;background:#090b0e}
.sigHead{display:flex;align-items:center;justify-content:space-between;gap:8px;color:#68717d;font-size:8px;font-weight:800;letter-spacing:.13em;text-transform:uppercase}
.sigHead span:last-child{overflow:hidden;text-align:right;text-overflow:ellipsis;white-space:nowrap}
.sigStats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:8px}
.sigStat{padding:7px;border:1px solid #252b33;border-radius:8px;background:#0c0f12}
.sigStat b{display:block;color:#dfe3e8;font-size:11px;font-variant-numeric:tabular-nums}
.sigStat span{display:block;margin-top:3px;color:#626b77;font-size:7px;font-weight:750;letter-spacing:.08em;text-transform:uppercase}
.sigSpectrum{margin-top:8px;padding:7px;border:1px solid #252b33;border-radius:9px;background:#080a0c}
.sigSpectrum svg{display:block;width:100%;height:92px}
.sigGrid{stroke:#252a31;stroke-width:1;vector-effect:non-scaling-stroke}
.sigCurve{fill:none;stroke:#4bd0ac;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke}
.sigDot{fill:#4bd0ac}
.sigBands{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:3px;margin-top:5px}
.sigBand{min-width:0;text-align:center}
.sigBand span{display:block;overflow:hidden;color:#5f6874;font-size:6px;font-weight:750;text-overflow:ellipsis;white-space:nowrap}
.sigBand b{display:block;margin-top:2px;color:#aab2bd;font-size:7px;font-variant-numeric:tabular-nums}
.sigTimeline{margin-top:8px;padding:7px;border:1px solid #252b33;border-radius:9px;background:#080a0c}
.sigTimeline canvas{display:block;width:100%;height:120px}
.sigLegend{margin-top:4px;color:#626b76;font-size:8px;line-height:1.35}
.sortbar{display:flex;align-items:end;justify-content:space-between;gap:10px;margin:15px 0 9px}
.sortbar label{margin:0;color:#727a86;font-size:9px;font-weight:800;letter-spacing:.11em;text-transform:uppercase}
.sortbar select{width:auto;min-width:140px;height:32px;padding:0 8px;color:#9ea5af;font-size:9px}
.outputs{display:grid;gap:8px}
.out{padding:11px;border:1px solid #262b33;border-radius:12px;background:#0a0c0f}
.outhead{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
.filename{overflow:hidden;color:#e8eaee;font-size:12px;font-weight:760;line-height:1.3;word-break:break-word}
.badge{
  display:inline-block;margin:6px 4px 0 0;padding:3px 6px;border:1px solid #2d333c;border-radius:999px;
  color:#777f8b;font-size:8px;font-weight:650;letter-spacing:.02em
}
.small{margin-top:4px;color:#626a76;font-size:9px;line-height:1.35}
.actions{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;margin-top:10px}
.actions>*{min-width:0;min-height:31px;padding:0 6px;text-align:center;font-size:9px}
.actions .download,.actions button.secondary{border-color:#303640;background:#14171b;color:#cdd1d7}
.actions .danger{border-color:#4c2b31!important;background:#171013!important}
button.armed{border-color:#d87a36!important;background:#24170e!important;color:#f0a05d!important}
.actionStatus,.shareStatus{min-height:0;margin-top:7px;color:#7e8793;font-size:9px}
.actionStatus:empty,.shareStatus:empty{display:none}
.preview{width:100%;height:446px;margin-top:9px;border:0;border-radius:12px;background:#090a0c}
.libraryitem{cursor:pointer;transition:border-color .15s,background .15s}
.libraryitem.active{border-color:#5e6673;background:#12161b}
.libraryitem+.libraryitem{margin-top:7px}
.sharebox{margin-top:9px;padding:9px;border:1px solid #2c323b;border-radius:10px;background:#0c0f13}
.sharebox input{height:34px;color:#939ba6;font-size:9px}
.sharebox .row{margin-top:7px}
.hidden{display:none!important}
@media(max-width:480px){
  .head{padding:12px}.body{padding:8px}.card{padding:11px}
  .grid{grid-template-columns:1fr 1fr}.metrics{grid-template-columns:1fr 1fr}
  .actions{grid-template-columns:repeat(3,minmax(0,1fr))}
  .sortbar{align-items:stretch;flex-direction:column}.sortbar select{width:100%}
  .sectionhint{max-width:230px}.live{padding:5px 7px}
}
</style>
</head>
<body>
<div class="shell">
  <header class="head">
    <div class="brand">
      <div class="mark">EM</div>
      <div>
        <div class="title">EIROS <span>MASTERING</span></div>
        <div class="sub">Section-aware audio workstation · panel 2.8.0</div>
      </div>
    </div>
    <div class="live"><span class="dot"></span>ENGINE 0.3</div>
  </header>

  <main class="body">
    <section class="card">
      <div class="sectionhead">
        <div>
          <div class="eyebrow">Source input</div>
          <h2>Импорт аудио</h2>
          <div class="sectionhint">WAV, FLAC, MP3 и другие аудиоформаты. Исходник сохраняется без изменений.</div>
        </div>
        <span class="cap">MAX 300 MB</span>
      </div>
      <label for="file">Файл</label>
      <input id="file" type="file" accept="audio/*,.wav,.wave,.flac,.mp3,.m4a,.aac,.aif,.aiff,.ogg,.opus"/>
      <div class="row">
        <button id="upload">Загрузить</button>
        <button id="refresh" class="secondary">Обновить</button>
      </div>
      <div id="uploadStatus" class="status">Выбери аудиофайл для загрузки.</div>
    </section>

    <section id="assetCard" class="card hidden">
      <div class="sectionhead">
        <div>
          <div class="eyebrow">Selected source</div>
          <h2 id="assetName"></h2>
          <div id="assetMeta" class="small"></div>
        </div>
        <span class="cap">ORIGINAL</span>
      </div>
      <div class="row">
        <button id="analyze">Анализировать</button>
        <button id="sourceToggle" class="secondary">Слушать исходник</button>
        <button id="delete" class="danger">Удалить всё</button>
      </div>
      <div id="sourceDeck" class="sourceDeck hidden">
        <div class="sourceTransport">
          <button id="sourcePlay" class="sourcePlay" type="button" aria-label="Воспроизвести исходник">▶</button>
          <div class="sourceTrack">
            <input id="sourceSeek" class="sourceSeek" type="range" min="0" max="1000" value="0" step="1" aria-label="Позиция исходника"/>
            <div class="sourceClock"><span id="sourceCurrent">0:00</span><span id="sourceState">ORIGINAL</span><span id="sourceDuration">0:00</span></div>
          </div>
        </div>
        <audio id="sourceAudio" preload="metadata" playsinline></audio>
      </div>
      <div id="analysisStatus" class="status"></div>
      <div id="metrics" class="metrics"></div>
      <div id="sourceSignature" class="signature hidden">
        <div class="sigHead"><span>Source signature</span><span id="sigMeta">ORIGINAL ANALYSIS</span></div>
        <div class="sigStats">
          <div class="sigStat"><b id="sigDominant">—</b><span>Dominant Hz</span></div>
          <div class="sigStat"><b id="sigCentroid">—</b><span>Centroid Hz</span></div>
          <div class="sigStat"><b id="sigSpread">—</b><span>Dynamic spread</span></div>
        </div>
        <div class="sigSpectrum">
          <div class="sigHead"><span>Spectral fingerprint</span><span>whole source</span></div>
          <svg viewBox="0 0 600 92" preserveAspectRatio="none" role="img" aria-label="Спектральная сигнатура исходника">
            <line class="sigGrid" x1="16" y1="15" x2="584" y2="15"></line>
            <line class="sigGrid" x1="16" y1="39" x2="584" y2="39"></line>
            <line class="sigGrid" x1="16" y1="63" x2="584" y2="63"></line>
            <line class="sigGrid" x1="16" y1="84" x2="584" y2="84"></line>
            <polyline id="sourceSpectrumLine" class="sigCurve" points=""></polyline>
            <g id="sourceSpectrumDots"></g>
          </svg>
          <div id="sourceBandValues" class="sigBands"></div>
        </div>
        <div class="sigTimeline">
          <div class="sigHead"><span>Dynamics map</span><span>source over time</span></div>
          <canvas id="sourceTimelineCanvas" width="900" height="132" aria-label="Динамика и секции исходника"></canvas>
          <div id="sourceTimelineLegend" class="sigLegend"></div>
        </div>
      </div>
    </section>

    <section id="renderCard" class="card hidden">
      <div class="sectionhead">
        <div>
          <div class="eyebrow">Mastering chain</div>
          <h2>Параметры мастера</h2>
          <div class="sectionhint">Adaptive обрабатывает секции отдельно и сохраняет намеренную динамику трека.</div>
        </div>
        <span class="cap">48 kHz / 24 bit</span>
      </div>
      <div class="grid">
        <div>
          <label for="profile">Профиль</label>
          <select id="profile">
            <option value="adaptive" selected>Adaptive · section aware</option>
            <option value="transparent">Transparent · global</option>
            <option value="dynamic">Dynamic · legacy glue</option>
            <option value="dark_ambient">Dark ambient · legacy</option>
            <option value="none">Loudness only</option>
          </select>
        </div>
        <div>
          <label for="lufs">Target LUFS</label>
          <input id="lufs" type="number" min="-18" max="-7" step="0.1" value="-14"/>
        </div>
        <div>
          <label for="peak">True peak dBTP</label>
          <input id="peak" type="number" min="-3" max="-0.1" step="0.1" value="-1"/>
        </div>
        <div>
          <label for="label">Метка экспорта</label>
          <input id="label" type="text" value="spotify"/>
        </div>
      </div>
      <div class="row"><button id="render">Создать мастер</button></div>
      <div id="renderStatus" class="status"></div>

      <div class="sortbar">
        <label>Outputs</label>
        <select id="outputSort" aria-label="Сортировка мастеров">
          <option value="newest">Сначала новые</option>
          <option value="oldest">Сначала старые</option>
          <option value="name">По названию</option>
          <option value="profile">По профилю</option>
        </select>
      </div>
      <div id="outputs" class="outputs"></div>
    </section>

    <section class="card">
      <div class="sectionhead">
        <div>
          <div class="eyebrow">Archive</div>
          <h2>Исходники</h2>
          <div class="sectionhint">Загруженные треки, анализы и связанные мастера.</div>
        </div>
      </div>
      <div class="sortbar">
        <label>Library</label>
        <select id="assetSort" aria-label="Сортировка исходников">
          <option value="newest">Сначала новые</option>
          <option value="oldest">Сначала старые</option>
          <option value="name">По названию</option>
          <option value="outputs">Больше мастеров</option>
        </select>
      </div>
      <div id="library" class="status">Загружаю хранилище…</div>
    </section>
  </main>
</div>
<script>
(() => {
  const BASE = "__PUBLIC_BASE__";
  const SHARE_BASE = "__PUBLIC_SHARE_BASE__";
  let current = null;
  let assetsCache = [];
  let sourceAudioAssetId = null;
  const sourceAnalysisCache = {};
  const SOURCE_BANDS = [
    ['sub_20_60','SUB'],['bass_60_120','BASS'],['low_mid_120_500','LOW MID'],
    ['mid_500_2000','MID'],['presence_2000_6000','PRESENCE'],['high_6000_12000','AIR']
  ];
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function request(path, options={}) {
    const r = await fetch(BASE + path, options);
    const type = r.headers.get('content-type') || '';
    const data = type.includes('json') ? await r.json() : await r.text();
    if (!r.ok) throw new Error((data && data.error) || String(data) || ('HTTP '+r.status));
    return data;
  }
  function reportAudioError(kind,error,audio) {
    const payload={
      panel:'2.8.0',
      kind,
      name:String(error?.name||''),
      message:String(error?.message||error||'').slice(0,300),
      media_code:Number(audio?.error?.code||0),
      network_state:Number(audio?.networkState||0),
      ready_state:Number(audio?.readyState||0)
    };
    fetch(BASE+'/api/client-log',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    }).catch(()=>{});
  }
  function setBusy(button,busy,text) {
    button.disabled=busy;
    if (text) { if (busy) button.dataset.old=button.textContent; button.textContent=busy?text:(button.dataset.old||button.textContent); }
  }
  function inlineConfirm(button,status,message) {
    const now=Date.now();
    const armedUntil=Number(button.dataset.armedUntil||0);
    if(armedUntil>now) {
      button.classList.remove('armed');
      delete button.dataset.armedUntil;
      if(status)status.textContent='';
      return true;
    }
    const original=button.dataset.originalText||button.textContent;
    button.dataset.originalText=original;
    button.dataset.armedUntil=String(now+6000);
    button.classList.add('armed');
    button.textContent='Подтвердить';
    if(status)status.textContent=message+' Нажми кнопку ещё раз.';
    setTimeout(()=>{
      if(Number(button.dataset.armedUntil||0)<=Date.now()) {
        button.classList.remove('armed');
        delete button.dataset.armedUntil;
        button.textContent=button.dataset.originalText||original;
        if(status&&status.textContent.includes('Нажми кнопку ещё раз'))status.textContent='';
      }
    },6100);
    return false;
  }
  function resetInlineConfirm(button) {
    button.classList.remove('armed');
    delete button.dataset.armedUntil;
    if(button.dataset.originalText)button.textContent=button.dataset.originalText;
  }
  const formatBytes = n => {
    const value=Number(n||0); if(!value)return '—';
    if(value>=1024*1024)return (value/1024/1024).toFixed(value>=100*1024*1024?0:1)+' MB';
    return Math.round(value/1024)+' KB';
  };
  const formatDate = ts => ts ? new Date(Number(ts)*1000).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
  function sortedOutputs(outputs) {
    const mode=$('outputSort').value;
    return [...(outputs||[])].sort((a,b)=>{
      if(mode==='oldest')return Number(a.created_at||0)-Number(b.created_at||0);
      if(mode==='name')return String(a.filename||'').localeCompare(String(b.filename||''));
      if(mode==='profile')return String(a.profile||'').localeCompare(String(b.profile||''))||Number(b.created_at||0)-Number(a.created_at||0);
      return Number(b.created_at||0)-Number(a.created_at||0);
    });
  }
  function sortedAssets() {
    const mode=$('assetSort').value;
    return [...assetsCache].sort((a,b)=>{
      if(mode==='oldest')return Number(a.created_at||0)-Number(b.created_at||0);
      if(mode==='name')return String(a.filename||'').localeCompare(String(b.filename||''));
      if(mode==='outputs')return Number(b.outputs?.length||0)-Number(a.outputs?.length||0);
      return Number(b.created_at||0)-Number(a.created_at||0);
    });
  }
  const clock = value => {
    const seconds=Math.max(0,Math.floor(Number(value)||0));
    return Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');
  };
  function setupSourceAsset(asset) {
    const audio=$('sourceAudio');
    const changed=sourceAudioAssetId!==asset.asset_id;
    if(changed) {
      audio.pause();
      sourceAudioAssetId=asset.asset_id;
      audio.src=BASE+'/api/source?asset_id='+encodeURIComponent(asset.asset_id)+'&format=preview&inline=1&v='+encodeURIComponent(asset.created_at||Date.now());
      audio.load();
      $('sourceDeck').classList.add('hidden');
      $('sourceToggle').textContent='Слушать исходник';
      $('sourcePlay').textContent='▶';
      $('sourceSeek').value='0';
      $('sourceSeek').style.setProperty('--progress','0%');
      $('sourceCurrent').textContent='0:00';
      $('sourceDuration').textContent=clock(asset.probe?.duration_seconds);
    }
    const cached=sourceAnalysisCache[asset.asset_id];
    if(cached) {
      renderSourceSignature(cached);
    } else if(changed) {
      $('sourceSignature').classList.add('hidden');
      $('metrics').innerHTML='';
      $('analysisStatus').textContent=asset.analyzed
        ?'Анализ сохранён. Нажми «Анализировать» — сигнатура откроется из кэша без повторного FFmpeg.'
        :'';
    }
  }
  function renderSourceSignature(analysis) {
    if(!analysis||!current)return;
    sourceAnalysisCache[current.asset_id]=analysis;
    const technical=analysis.technical||{};
    const spectrum=technical.spectrum||{};
    const energy=spectrum.energy_percent||{};
    const timeline=analysis.timeline||{};
    const summary=timeline.summary||{};
    const values=SOURCE_BANDS.map(([key,label])=>({key,label,value:Number(energy[key]||0)}));
    const dbValues=values.map(item=>10*Math.log10(Math.max(item.value,1e-6)));
    const ceiling=Math.max.apply(null,dbValues);
    const floor=ceiling-30;
    const points=dbValues.map((value,index)=>{
      const x=16+568*index/Math.max(1,dbValues.length-1);
      const y=15+(ceiling-Math.max(floor,Math.min(ceiling,value)))/30*69;
      return {x,y};
    });
    $('sourceSpectrumLine').setAttribute('points',points.map(point=>point.x+','+point.y).join(' '));
    $('sourceSpectrumDots').innerHTML=points.map(point=>'<circle class="sigDot" cx="'+point.x+'" cy="'+point.y+'" r="3"></circle>').join('');
    $('sourceBandValues').innerHTML=values.map(item=>'<div class="sigBand"><span>'+esc(item.label)+'</span><b>'+item.value.toFixed(1)+'%</b></div>').join('');
    $('sigDominant').textContent=Number(spectrum.dominant_frequency_hz||0).toFixed(1);
    $('sigCentroid').textContent=Number(spectrum.spectral_centroid_hz||0).toFixed(1);
    $('sigSpread').textContent=Number(summary.short_term_spread_db||0).toFixed(1)+' dB';
    $('sigMeta').textContent=(summary.section_count||0)+' SECTIONS · '+Number(spectrum.analysis_seconds||timeline.duration_seconds||0).toFixed(0)+' S';
    $('sourceTimelineLegend').textContent='Секции: '+(summary.section_count||0)+' · rising '+(summary.rising_sections||0)+' · falling '+(summary.falling_sections||0)+' · stable '+(summary.stable_sections||0)+' · вертикальная линия следует за плеером.';
    $('sourceSignature').classList.remove('hidden');
    drawSourceTimeline($('sourceAudio').currentTime||0);
  }
  function drawSourceTimeline(playhead=0) {
    if(!current)return;
    const analysis=sourceAnalysisCache[current.asset_id];
    const canvas=$('sourceTimelineCanvas');
    const ctx=canvas?.getContext?.('2d');
    const timeline=analysis?.timeline||{};
    const points=Array.isArray(timeline.points)?timeline.points:[];
    if(!ctx||!points.length)return;
    const sections=Array.isArray(timeline.sections)?timeline.sections:[];
    const width=canvas.width, height=canvas.height;
    const left=42, right=8, top=8, bottom=20;
    const plotWidth=width-left-right, plotHeight=height-top-bottom;
    const duration=Math.max(1,Number(timeline.duration_seconds||$('sourceAudio').duration||points[points.length-1]?.t||1));
    const rmsValues=points.map(point=>Number(point.short_rms_dbfs||-60));
    let floor=Math.min.apply(null,rmsValues)-2;
    let ceiling=Math.max.apply(null,rmsValues)+2;
    if(ceiling-floor<8){const middle=(ceiling+floor)/2;floor=middle-4;ceiling=middle+4}
    const xFor=t=>left+plotWidth*Math.max(0,Math.min(1,Number(t||0)/duration));
    const yFor=db=>top+(ceiling-Number(db||floor))/(ceiling-floor)*plotHeight;
    ctx.clearRect(0,0,width,height);
    ctx.fillStyle='#080a0c';
    ctx.fillRect(0,0,width,height);
    sections.forEach(section=>{
      const trajectory=String(section.trajectory||'stable');
      ctx.fillStyle=trajectory==='rising'?'rgba(61,214,170,.09)':trajectory==='falling'?'rgba(239,106,120,.09)':'rgba(119,132,151,.045)';
      ctx.fillRect(xFor(section.start_seconds),top,Math.max(1,xFor(section.end_seconds)-xFor(section.start_seconds)),plotHeight);
    });
    ctx.font='8px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
    ctx.textBaseline='middle';
    for(let row=0;row<=4;row++){
      const ratio=row/4;
      const y=top+plotHeight*ratio;
      const db=ceiling-(ceiling-floor)*ratio;
      ctx.strokeStyle='#252a31';
      ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(width-right,y);ctx.stroke();
      ctx.fillStyle='#59626e';ctx.textAlign='right';ctx.fillText(db.toFixed(0),left-6,y);
    }
    ctx.strokeStyle='#4bd0ac';
    ctx.lineWidth=2;
    ctx.beginPath();
    points.forEach((point,index)=>{
      const x=xFor(point.t), y=yFor(point.short_rms_dbfs);
      if(index===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
    });
    ctx.stroke();
    sections.forEach(section=>{
      const x=xFor(section.start_seconds);
      ctx.strokeStyle='#353b44';ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,top+plotHeight);ctx.stroke();
    });
    [0,.5,1].forEach((ratio,index)=>{
      const x=left+plotWidth*ratio;
      ctx.fillStyle='#626b76';
      ctx.textAlign=index===0?'left':index===2?'right':'center';
      ctx.fillText(clock(duration*ratio),x,height-7);
    });
    const cursor=xFor(playhead);
    ctx.strokeStyle='#f0f2f5';ctx.lineWidth=1.4;
    ctx.beginPath();ctx.moveTo(cursor,top);ctx.lineTo(cursor,top+plotHeight);ctx.stroke();
  }
  function showAsset(asset) {
    current=asset;
    $('assetCard').classList.remove('hidden');
    $('renderCard').classList.remove('hidden');
    $('assetName').textContent=asset.filename || asset.asset_id;
    const p=asset.probe||{}, s=asset.analysis_summary||{};
    $('assetMeta').textContent=[p.format,p.codec,p.sample_rate?p.sample_rate+' Hz':'',p.channels?p.channels+' ch':'',p.duration_seconds?p.duration_seconds+'s':'',s.section_count?s.section_count+' sections':''].filter(Boolean).join(' · ');
    setupSourceAsset(asset);
    renderOutputs(asset.outputs||[]);
    renderLibrary();
  }
  function shareMarkup(token) {
    const url=SHARE_BASE+'/'+encodeURIComponent(token);
    return '<div class="sharebox" data-token="'+esc(token)+'"><label>Публичная ссылка</label><input type="text" readonly value="'+esc(url)+'"/><div class="row"><button class="secondary" data-copy-share>Копировать</button><button class="secondary" data-native-share>Поделиться</button><a class="download" href="'+esc(url)+'" target="_blank" rel="noopener">Открыть</a><button class="danger" data-revoke-share>Отключить</button></div><div class="shareStatus" data-share-status></div></div>';
  }
  function renderOutputs(outputs) {
    const rows=sortedOutputs(outputs);
    $('outputs').innerHTML=rows.map(o=>{
      const l=o.report?.loudness||{}, p=o.report?.probe||{}, adaptive=o.adaptive||{};
      const q='asset_id='+encodeURIComponent(current.asset_id)+'&output_id='+encodeURIComponent(o.output_id);
      const wav=BASE+'/api/download?'+q+'&format=wav';
      const mp3=BASE+'/api/download?'+q+'&format=mp3';
      const player=BASE+'/api/player?'+q;
      const activeShares=(o.shares||[]).filter(s=>Number(s.expires_at||0)>Date.now()/1000).sort((a,b)=>Number(b.created_at||0)-Number(a.created_at||0));
      const profileTag=o.profile==='adaptive'
        ?'ADAPTIVE · SECTION AWARE'
        :(o.profile==='transparent'?'TRANSPARENT · LEVEL ONLY':String(o.profile||'master').toUpperCase());
      const tags=[
        profileTag,
        adaptive.section_count!=null?adaptive.section_count+' sections':'',
        l.integrated_lufs!=null?l.integrated_lufs+' LUFS':'',
        l.true_peak_dbtp!=null?l.true_peak_dbtp+' dBTP':'',
        o.clean_export?.version?'clean v'+o.clean_export.version:''
      ].filter(Boolean).map(x=>'<span class="badge">'+esc(x)+'</span>').join('');
      return '<article class="out" data-output-id="'+esc(o.output_id)+'">'+
        '<div class="outhead"><div><div class="filename">'+esc(o.filename)+'</div><div>'+tags+'</div></div></div>'+
        '<div class="small">'+esc(formatDate(o.created_at))+' · WAV '+esc(formatBytes(p.size_bytes))+'</div>'+
        '<div class="actions">'+
          '<a class="download" href="'+wav+'" target="_blank" rel="noopener">WAV</a>'+
          '<a class="download" href="'+mp3+'" target="_blank" rel="noopener">MP3</a>'+
          '<button class="secondary" data-preview>A/B</button>'+
          '<button class="secondary" data-share>Ссылка</button>'+
          '<button class="danger" data-delete-output>Удалить</button>'+
        '</div>'+
        '<div class="actionStatus" data-action-status></div>'+
        '<iframe class="preview hidden" loading="lazy" allow="autoplay" title="A/B: оригинал и мастер" data-src="'+player+'"></iframe>'+
        '<div data-share-zone>'+(activeShares[0]?shareMarkup(activeShares[0].token):'')+'</div>'+
      '</article>';
    }).join('') || '<div class="small">Готовых мастеров пока нет.</div>';
    bindOutputEvents();
  }
  function renderLibrary() {
    const rows=sortedAssets();
    $('library').innerHTML=rows.length ? rows.map(a=>{
      const p=a.probe||{}, active=current&&current.asset_id===a.asset_id?' active':'';
      return '<div class="out libraryitem'+active+'" data-id="'+esc(a.asset_id)+'"><div class="filename">'+esc(a.filename)+'</div><div class="small">'+esc(formatDate(a.created_at))+' · '+esc(p.format||p.codec||'audio')+' · мастеров: '+esc(a.outputs?.length||0)+'</div></div>';
    }).join('') : 'Хранилище пустое.';
    $('library').querySelectorAll('[data-id]').forEach(el=>el.onclick=()=>{
      const asset=assetsCache.find(a=>a.asset_id===el.dataset.id);
      if(asset)showAsset(asset);
    });
  }
  async function copyText(textValue,input) {
    if(navigator.clipboard?.writeText) {
      try {await navigator.clipboard.writeText(textValue);return true}catch(ignore){}
    }
    try {
      input.focus();
      input.select();
      return Boolean(document.execCommand('copy'));
    } catch(ignore) {
      input.focus();
      input.select();
      return false;
    }
  }
  function bindShareBox(box,outputId) {
    if(!box)return;
    const token=box.dataset.token, input=box.querySelector('input'), url=input?.value||'';
    const status=box.querySelector('[data-share-status]');
    box.querySelector('[data-copy-share]')?.addEventListener('click',async e=>{
      const copied=await copyText(url,input);
      e.currentTarget.textContent=copied?'Скопировано':'Выделено';
      if(status)status.textContent=copied?'Ссылка в буфере обмена.':'Ссылка выделена — выбери «Копировать» в меню iOS.';
      setTimeout(()=>e.currentTarget.textContent='Копировать',1400);
    });
    box.querySelector('[data-native-share]')?.addEventListener('click',async()=>{
      try {
        if(navigator.share) {
          await navigator.share({title:current?.filename||'EIROS master',url});
          if(status)status.textContent='Меню «Поделиться» открыто.';
        } else {
          const copied=await copyText(url,input);
          if(status)status.textContent=copied?'Ссылка скопирована.':'Ссылка выделена — выбери «Копировать».';
        }
      } catch(err) {
        if(status)status.textContent=err?.name==='AbortError'?'Отменено.':'Не удалось поделиться: '+err.message;
      }
    });
    box.querySelector('[data-revoke-share]')?.addEventListener('click',async e=>{
      const button=e.currentTarget;
      if(!inlineConfirm(button,status,'Ссылка сразу перестанет работать.'))return;
      resetInlineConfirm(button);
      setBusy(button,true,'Отключаю…');
      try {
        await request('/api/share/revoke',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});
        const output=current.outputs.find(o=>o.output_id===outputId);
        if(output)output.shares=(output.shares||[]).filter(s=>s.token!==token);
        renderOutputs(current.outputs);
      } catch(err) {
        if(status)status.textContent='Ошибка отключения: '+err.message;
      } finally {
        setBusy(button,false,'Отключить');
      }
    });
  }
  function bindOutputEvents() {
    $('outputs').querySelectorAll('[data-output-id]').forEach(card=>{
      const outputId=card.dataset.outputId;
      card.querySelector('[data-preview]')?.addEventListener('click',e=>{
        const button=e.currentTarget;
        const frame=card.querySelector('iframe.preview');
        if(!frame.classList.contains('hidden')) {
          frame.src='about:blank';
          frame.removeAttribute('src');
          frame.classList.add('hidden');
          button.textContent='A/B';
          return;
        }
        $('outputs').querySelectorAll('iframe.preview:not(.hidden)').forEach(openFrame=>{
          openFrame.src='about:blank';
          openFrame.removeAttribute('src');
          openFrame.classList.add('hidden');
          openFrame.closest('[data-output-id]')?.querySelector('[data-preview]')?.replaceChildren('A/B');
        });
        frame.src=frame.dataset.src+'&fresh='+Date.now();
        frame.classList.remove('hidden');
        button.textContent='Скрыть';
      });
      card.querySelector('[data-share]')?.addEventListener('click',async e=>{
        const button=e.currentTarget;
        const zone=card.querySelector('[data-share-zone]');
        const status=card.querySelector('[data-action-status]');
        const existing=zone.querySelector('.sharebox');
        if(existing) {
          if(status)status.textContent='Действующая ссылка уже готова — она ниже.';
          existing.scrollIntoView({behavior:'smooth',block:'nearest'});
          return;
        }
        setBusy(button,true,'Создаю…');
        if(status)status.textContent='Создаю публичную ссылку…';
        try{
          const data=await request('/api/share',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:current.asset_id,output_id:outputId,expires_days:30})});
          const output=current.outputs.find(o=>o.output_id===outputId);
          if(output)output.shares=[...(output.shares||[]),{token:data.token,created_at:data.created_at,expires_at:data.expires_at}];
          zone.innerHTML=shareMarkup(data.token);
          bindShareBox(zone.querySelector('.sharebox'),outputId);
          if(status)status.textContent='Ссылка готова — блок появился ниже.';
          zone.scrollIntoView({behavior:'smooth',block:'nearest'});
        }catch(err){
          if(status)status.textContent='Ошибка ссылки: '+err.message;
        } finally {
          setBusy(button,false,'Ссылка');
        }
      });
      card.querySelector('[data-delete-output]')?.addEventListener('click',async e=>{
        const button=e.currentTarget;
        const status=card.querySelector('[data-action-status]');
        if(!inlineConfirm(button,status,'Будут удалены мастер, MP3 и активные ссылки; исходник останется.'))return;
        resetInlineConfirm(button);
        setBusy(button,true,'Удаляю…');
        try{
          await request('/api/output/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:current.asset_id,output_id:outputId})});
          current.outputs=(current.outputs||[]).filter(o=>o.output_id!==outputId);
          renderOutputs(current.outputs);
          await loadList(true);
        }catch(err){
          if(status)status.textContent='Ошибка удаления: '+err.message;
        } finally {
          setBusy(button,false,'Удалить');
        }
      });
      bindShareBox(card.querySelector('.sharebox'),outputId);
    });
  }
  async function loadList(preserve=true) {
    try {
      const currentId=preserve?current?.asset_id:null;
      const data=await request('/api/list');
      assetsCache=data.assets||[];
      const updated=currentId?assetsCache.find(a=>a.asset_id===currentId):null;
      if(updated)showAsset(updated);
      else if(!current&&assetsCache.length)showAsset(sortedAssets()[0]);
      else renderLibrary();
    } catch(e) {$('library').textContent='Ошибка списка: '+e.message}
  }
  $('upload').onclick=async()=>{
    const f=$('file').files[0]; if(!f){$('uploadStatus').textContent='Сначала выбери файл.';return}
    const b=$('upload'); setBusy(b,true,'Загрузка…'); $('uploadStatus').textContent=`Отправляю ${f.name} (${Math.round(f.size/1024/1024*10)/10} МБ)…`;
    try {
      const form=new FormData(); form.append('file',f,f.name);
      const data=await request('/api/upload',{method:'POST',body:form});
      $('uploadStatus').textContent='Загружено. asset_id: '+data.asset_id;
      showAsset(data); await loadList();
    } catch(e) {$('uploadStatus').textContent='Ошибка: '+e.message}
    finally {setBusy(b,false,'Загрузить')}
  };
  const sourceAudio=$('sourceAudio');
  function paintSourceTransport() {
    const total=Number(sourceAudio.duration)||Number(current?.probe?.duration_seconds)||0;
    const at=Number(sourceAudio.currentTime)||0;
    const progress=total>0?Math.max(0,Math.min(100,at/total*100)):0;
    $('sourceSeek').value=String(Math.round(progress*10));
    $('sourceSeek').style.setProperty('--progress',progress+'%');
    $('sourceCurrent').textContent=clock(at);
    $('sourceDuration').textContent=clock(total);
    $('sourcePlay').textContent=!sourceAudio.paused&&!sourceAudio.ended?'Ⅱ':'▶';
    $('sourcePlay').setAttribute('aria-label',sourceAudio.paused?'Воспроизвести исходник':'Пауза');
    if(!sourceAudio.error)$('sourceState').textContent=!sourceAudio.paused&&!sourceAudio.ended?'PLAYING ORIGINAL':'ORIGINAL';
    drawSourceTimeline(at);
  }
  $('sourceToggle').onclick=async()=>{
    if(!current)return;
    const deck=$('sourceDeck');
    if(!deck.classList.contains('hidden')) {
      sourceAudio.pause();
      deck.classList.add('hidden');
      $('sourceToggle').textContent='Слушать исходник';
      paintSourceTransport();
      return;
    }
    deck.classList.remove('hidden');
    $('sourceToggle').textContent='Скрыть плеер';
    try {
      await sourceAudio.play();
    } catch(err) {
      $('sourceState').textContent='TAP PLAY';
      reportAudioError('source_play',err,sourceAudio);
    }
    paintSourceTransport();
  };
  $('sourcePlay').onclick=async()=>{
    try {
      if(sourceAudio.paused)await sourceAudio.play();
      else sourceAudio.pause();
    } catch(err) {
      $('sourceState').textContent='UNAVAILABLE';
      reportAudioError('source_play',err,sourceAudio);
    }
    paintSourceTransport();
  };
  $('sourceSeek').oninput=()=>{
    const total=Number(sourceAudio.duration)||Number(current?.probe?.duration_seconds)||0;
    const ratio=Number($('sourceSeek').value)/1000;
    $('sourceSeek').style.setProperty('--progress',(ratio*100)+'%');
    $('sourceCurrent').textContent=clock(total*ratio);
  };
  $('sourceSeek').onchange=()=>{
    const total=Number(sourceAudio.duration)||0;
    if(total>0)sourceAudio.currentTime=total*(Number($('sourceSeek').value)/1000);
    paintSourceTransport();
  };
  ['loadedmetadata','durationchange','timeupdate','play','pause','ended','canplay'].forEach(eventName=>{
    sourceAudio.addEventListener(eventName,paintSourceTransport);
  });
  sourceAudio.addEventListener('waiting',()=>{$('sourceState').textContent='BUFFERING'});
  sourceAudio.addEventListener('error',()=>{
    $('sourceState').textContent='UNAVAILABLE';
    reportAudioError('source_media_error',sourceAudio.error,sourceAudio);
  });
  $('analyze').onclick=async()=>{
    if(!current)return; const b=$('analyze'); setBusy(b,true,'Анализ…'); $('analysisStatus').textContent='FFmpeg измеряет громкость, пики, динамику и спектр…';
    try {
      const data=await request('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:current.asset_id})});
      const a=data.analysis||{}, l=a.loudness||{}, t=a.technical||{};
      const timeline=a.timeline||{}, summary=timeline.summary||{};
      $('analysisStatus').textContent='Анализ готов · секций: '+(summary.section_count||0)+' · rising: '+(summary.rising_sections||0)+' · falling: '+(summary.falling_sections||0)+' · spread: '+(summary.short_term_spread_db??'—')+' dB';
      $('metrics').innerHTML=[
        ['LUFS',l.integrated_lufs],['True peak',l.true_peak_dbtp+' dBTP'],['LRA',l.loudness_range_lu+' LU'],['Crest',t.crest_factor_db+' dB'],
        ['Stereo corr',t.stereo_correlation],['RMS',t.rms_dbfs+' dBFS']
      ].map(x=>`<div class="metric"><b>${esc(x[1])}</b><span>${esc(x[0])}</span></div>`).join('');
      renderSourceSignature(a);
    } catch(e) {$('analysisStatus').textContent='Ошибка: '+e.message}
    finally {setBusy(b,false,'Анализ')}
  };
  $('render').onclick=async()=>{
    if(!current)return; const b=$('render'); setBusy(b,true,'Рендер…'); $('renderStatus').textContent='Двухпроходный EBU R128 мастеринг…';
    try {
      const body={asset_id:current.asset_id,profile:$('profile').value,target_lufs:Number($('lufs').value),true_peak_dbtp:Number($('peak').value),label:$('label').value};
      const data=await request('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const adaptive=data.output?.adaptive||{};
      const ride=adaptive.gain_ride||{};
      $('renderStatus').textContent='Мастер готов · '+(adaptive.engine_version||data.output?.profile||'')+(adaptive.section_count!=null?' · секций: '+adaptive.section_count:'')+(ride.max_cut_db!=null?' · max local cut: '+ride.max_cut_db+' dB':'');
      current.outputs=[...(current.outputs||[]),data.output]; renderOutputs(current.outputs); await loadList();
    } catch(e) {$('renderStatus').textContent='Ошибка: '+e.message}
    finally {setBusy(b,false,'Сделать мастер')}
  };
  $('delete').onclick=async e=>{
    if(!current)return;
    const button=e.currentTarget;
    const status=$('analysisStatus');
    if(!inlineConfirm(button,status,'Будут удалены исходник, анализ и все его мастера.'))return;
    resetInlineConfirm(button);
    setBusy(button,true,'Удаляю всё…');
    try {
      await request('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:current.asset_id})});
      const deletedAssetId=current.asset_id;
      sourceAudio.pause();
      sourceAudio.removeAttribute('src');
      sourceAudio.load();
      sourceAudioAssetId=null;
      delete sourceAnalysisCache[deletedAssetId];
      current=null;
      $('assetCard').classList.add('hidden');
      $('renderCard').classList.add('hidden');
      await loadList();
    } catch(err) {
      status.textContent='Ошибка удаления: '+err.message;
    } finally {
      setBusy(button,false,'Удалить всё');
    }
  };
  $('refresh').onclick=()=>loadList(true);
  $('outputSort').onchange=()=>current&&renderOutputs(current.outputs||[]);
  $('assetSort').onchange=renderLibrary;
  loadList(false);
})();
</script>
</body>
</html>"""
    return template.replace("__PUBLIC_BASE__", PUBLIC_BASE).replace("__PUBLIC_SHARE_BASE__", PUBLIC_SHARE_BASE)


_legacy_panel_html = _panel_html

def _panel_html() -> str:
    template = (Path(__file__).with_name("mastering_panel_v17.html")).read_text(encoding="utf-8")
    return template.replace("__PUBLIC_BASE__", PUBLIC_BASE).replace("__PUBLIC_SHARE_BASE__", PUBLIC_SHARE_BASE)



def _diagnostic_panel_html() -> str:
    return """<!doctype html>
<html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">
<style>html,body{margin:0;background:#0b0e12;color:#eef1f4;font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif}#box{padding:18px;border:1px solid #2e3740;border-radius:14px;background:#11161b}b{color:#67d7bc}small{display:block;margin-top:8px;color:#89929d}</style></head>
<body><div id=\"box\"><b>EIROS WIDGET OK</b><small id=\"status\">static HTML mounted</small></div>
<script>
(function(){
  const status=document.getElementById('status');
  function reportHeight(){
    try{ window.openai?.notifyIntrinsicHeight?.({height:document.documentElement.scrollHeight}); }catch(e){}
  }
  window.addEventListener('message',function(event){
    if(event.source!==window.parent)return;
    const m=event.data;
    if(!m||m.jsonrpc!=='2.0')return;
    if(m.method==='ui/notifications/tool-result') status.textContent='MCP Apps bridge + tool-result received';
    if(m.method==='ui/notifications/tool-input') status.textContent='MCP Apps bridge + tool-input received';
    reportHeight();
  },{passive:true});
  window.addEventListener('openai:set_globals',reportHeight,{passive:true});
  requestAnimationFrame(reportHeight);
  setTimeout(reportHeight,50);
})();
</script></body></html>"""

# Headless preview: UI resources/templates are intentionally not registered with MCP.
def mastering_diagnostic_resource() -> str:
    return _diagnostic_panel_html()


def mastering_panel_resource() -> str:
    return """<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><style>html,body{margin:0;background:#0b0e12;color:#89929d;font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif}.box{padding:12px;font-size:13px}</style></head><body><div class=\"box\">EIROS Mastering in-chat panel is temporarily disabled.</div></body></html>"""


def mastering_panel_resource_legacy() -> str:
    return _legacy_panel_html()


def mastering_panel_resource_legacy_v2() -> str:
    return _legacy_panel_html()


def open_mastering_diagnostic() -> dict[str, Any]:
    return {"ok": True, "resource_uri": DIAGNOSTIC_PANEL_URI, "diagnostic": "minimal-static-widget"}


@mcp.tool(
    name="open_mastering_panel",
    title="EIROS Mastering status",
    description="Return EIROS Mastering status without opening an in-chat UI. The visual panel is temporarily disabled for client stability.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def open_mastering_panel() -> dict[str, Any]:
    return {
        "ok": True,
        "panel_enabled": False,
        "reason": "in-chat mastering panel temporarily disabled for client stability",
        "panel_version": "2.8.0",
        "upload_mode": "connector_binary_or_external_browser",
        "max_upload_mb": mastering_engine.MAX_UPLOAD_BYTES // (1024 * 1024),
    }


# ChatGPT's connector gateway currently invokes the qualified tool name.
# Keep this alias alongside the canonical MCP tool so reconnects remain compatible.
@mcp.tool(
    name="eirosmaster.open_mastering_panel",
    title="EIROS Mastering status",
    description="Compatibility alias. Returns status only; the in-chat UI is temporarily disabled.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def open_mastering_panel_connector_alias() -> dict[str, Any]:
    return open_mastering_panel()


@mcp.tool(
    name="mastering_health",
    title="Check EIROS Mastering",
    description="Check whether the dedicated EIROS remote mastering service is alive.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "eiros-mastering-mcp",
        "server_version": __version__,
        "engine_version": mastering_engine.ADAPTIVE_ENGINE_VERSION,
        "director_engine_version": mastering_engine.DIRECTOR_ENGINE_VERSION,
        "verification_schema_version": 1,
        "analysis_version": mastering_engine.ANALYSIS_VERSION,
        "clean_export_version": mastering_engine.CLEAN_EXPORT_VERSION,
        "preview_export_version": mastering_engine.PREVIEW_EXPORT_VERSION,
        "ab_preview": True,
        "ab_spectrum": True,
        "time": int(time.time()),
        "instance_id": CONFIG.get("instance_id"),
        "panel": PANEL_URI,
    }


@mcp.tool(
    name="mastering_upload",
    title="Upload audio for mastering",
    description="Binary upload compatibility tool. In ChatGPT use open_mastering_panel for reliable browser file upload.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def mastering_upload(filename: str, audio_file: bytes) -> dict[str, Any]:
    return mastering_engine.store_upload(filename, audio_file)


@mcp.tool(
    name="mastering_analyze",
    title="Analyze audio for mastering",
    description="Measure format, integrated LUFS, true peak, loudness range, crest factor, stereo correlation and spectral energy without changing the audio.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_analyze(asset_id: str, force: bool = False) -> dict[str, Any]:
    return mastering_engine.analyze(asset_id, force)


@mcp.tool(
    name="mastering_render",
    title="Render a remote master",
    description="Render a section-aware adaptive 48 kHz/24-bit WAV master. Intentional crescendos and section-level macro dynamics are preserved; only local residuals are corrected before final loudness and true-peak control.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def mastering_render(
    asset_id: str,
    profile: str = "adaptive",
    target_lufs: float = -14.0,
    true_peak_dbtp: float = -1.0,
    label: str = "spotify",
) -> dict[str, Any]:
    return mastering_engine.render(asset_id, profile, target_lufs, true_peak_dbtp, label)


@mcp.tool(
    name="mastering_plan_create",
    title="Create Director mastering plan",
    description="Persist a Director-authored mastering plan. The plan is authoritative; the DSP engine may not invent artistic corrections.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def mastering_plan_create(asset_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "asset_id": asset_id, "plan": mastering_engine.save_director_plan(asset_id, plan)}


@mcp.tool(
    name="mastering_plan_get",
    title="Get Director mastering plan",
    description="Read one persisted Director mastering plan without changing audio.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_plan_get(asset_id: str, plan_id: str) -> dict[str, Any]:
    return {"ok": True, "asset_id": asset_id, "plan": mastering_engine.get_director_plan(asset_id, plan_id)}


@mcp.tool(
    name="mastering_render_directed",
    title="Render Director master",
    description="Execute only the supplied Director plan using deterministic DSP. Verification is mandatory before approval.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def mastering_render_directed(asset_id: str, plan_id: str, label: str = "master") -> dict[str, Any]:
    return mastering_engine.render(asset_id, profile="director", label=label, director_plan_id=plan_id)


@mcp.tool(
    name="mastering_verify",
    title="Verify rendered master",
    description="Run mandatory source/master delta analysis and post-master QA before approval.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_verify(asset_id: str, output_id: str) -> dict[str, Any]:
    return mastering_engine.verify_output(asset_id, output_id)


@mcp.tool(
    name="mastering_approve",
    title="Approve verified master",
    description="Mark a master APPROVED only when its latest verification status is PASS.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_approve(asset_id: str, output_id: str) -> dict[str, Any]:
    return mastering_engine.approve_output(asset_id, output_id)


@mcp.tool(
    name="mastering_metadata_audit",
    title="Audit audio metadata",
    description="Inspect structural metadata, optional tags, embedded art, chapters and encoder-identifying fields without changing audio.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_metadata_audit(asset_id: str) -> dict[str, Any]:
    return mastering_engine.audit_asset_metadata(asset_id)


@mcp.tool(
    name="mastering_experience_similar",
    title="Find similar mastering experience",
    description="Return advisory prior mastering experiences. Memory never executes DSP or mutates the Director plan.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_experience_similar(asset_id: str, intent_tags: list[str] | None = None, protected_traits: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
    return mastering_engine.experience_similar(asset_id, intent_tags, protected_traits, limit)


@mcp.tool(
    name="mastering_feedback_record",
    title="Record mastering feedback",
    description="Persist Rico feedback together with source features, Director decisions and verification outcome for future advisory retrieval.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def mastering_feedback_record(asset_id: str, output_id: str, feedback: str, intent_tags: list[str] | None = None) -> dict[str, Any]:
    return mastering_engine.record_feedback(asset_id, output_id, feedback, intent_tags)


@mcp.tool(
    name="mastering_list",
    title="List mastering assets",
    description="List uploaded source assets, analyses and rendered masters stored on the EIROS VPS.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_list(limit: int = 30) -> dict[str, Any]:
    return mastering_engine.list_assets(limit)


@mcp.tool(
    name="mastering_download",
    title="Download a rendered master",
    description="Download one rendered master as 48 kHz/24-bit WAV or 320 kbps MP3.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
)
def mastering_download(asset_id: str, output_id: str, file_format: str = "wav") -> bytes:
    return mastering_engine.output_bytes(asset_id, output_id, file_format)


@mcp.tool(
    name="mastering_delete",
    title="Delete one mastering asset",
    description="Permanently delete one uploaded source, its analysis and every rendered output belonging to it.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True, idempotentHint=True),
    structured_output=True,
)
def mastering_delete(asset_id: str) -> dict[str, Any]:
    return mastering_engine.delete_asset(asset_id)



@mcp.tool(
    name="mastering_prepare_mp3",
    title="Prepare MP3 export",
    description="Create or reuse a 320 kbps MP3 derivative of one rendered master and return its metadata.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_prepare_mp3(asset_id: str, output_id: str) -> dict[str, Any]:
    result = dict(mastering_engine.ensure_mp3(asset_id, output_id))
    result.pop("path", None)
    return {"ok": True, "asset_id": asset_id, "output_id": output_id, "mp3": result}


@mcp.tool(
    name="mastering_delete_output",
    title="Delete one rendered master",
    description="Permanently delete one rendered master and its MP3 derivative without deleting the uploaded source or other masters.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True, idempotentHint=True),
    structured_output=True,
)
def mastering_delete_output(asset_id: str, output_id: str) -> dict[str, Any]:
    return mastering_engine.delete_output(asset_id, output_id)


@mcp.tool(
    name="mastering_share_create",
    title="Create a private share link",
    description="Create an unguessable, expiring public page for one master with streaming and WAV/MP3 downloads.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def mastering_share_create(asset_id: str, output_id: str, expires_days: int = 30) -> dict[str, Any]:
    result = mastering_engine.create_share(asset_id, output_id, expires_days)
    result["public_url"] = f"{PUBLIC_SHARE_BASE}/{result['token']}"
    return result


@mcp.tool(
    name="mastering_share_revoke",
    title="Revoke a mastering share link",
    description="Immediately disable one previously created public mastering link.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True, idempotentHint=True),
    structured_output=True,
)
def mastering_share_revoke(token: str) -> dict[str, Any]:
    return mastering_engine.revoke_share(token)


# The ChatGPT connector broker qualifies calls as "eirosmaster.<tool>".
# Expose matching aliases for every operation while retaining canonical MCP names.
@mcp.tool(
    name="eirosmaster.mastering_health",
    title="Check EIROS Mastering",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_health_connector_alias() -> dict[str, Any]:
    return mastering_health()


@mcp.tool(
    name="eirosmaster.mastering_upload",
    title="Upload audio for mastering",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def mastering_upload_connector_alias(filename: str, audio_file: bytes) -> dict[str, Any]:
    return mastering_upload(filename, audio_file)


@mcp.tool(
    name="eirosmaster.mastering_analyze",
    title="Analyze audio for mastering",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_analyze_connector_alias(asset_id: str, force: bool = False) -> dict[str, Any]:
    return mastering_analyze(asset_id, force)


@mcp.tool(
    name="eirosmaster.mastering_render",
    title="Render a remote master",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def mastering_render_connector_alias(
    asset_id: str,
    profile: str = "adaptive",
    target_lufs: float = -14.0,
    true_peak_dbtp: float = -1.0,
    label: str = "spotify",
) -> dict[str, Any]:
    return mastering_render(asset_id, profile, target_lufs, true_peak_dbtp, label)


@mcp.tool(
    name="eirosmaster.mastering_list",
    title="List mastering assets",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_list_connector_alias(limit: int = 30) -> dict[str, Any]:
    return mastering_list(limit)


@mcp.tool(
    name="eirosmaster.mastering_download",
    title="Download a rendered master",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
)
def mastering_download_connector_alias(asset_id: str, output_id: str, file_format: str = "wav") -> bytes:
    return mastering_download(asset_id, output_id, file_format)


@mcp.tool(
    name="eirosmaster.mastering_delete",
    title="Delete one mastering asset",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True, idempotentHint=True),
    structured_output=True,
)
def mastering_delete_connector_alias(asset_id: str) -> dict[str, Any]:
    return mastering_delete(asset_id)


@mcp.tool(
    name="eirosmaster.mastering_prepare_mp3",
    title="Prepare MP3 export",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_prepare_mp3_connector_alias(asset_id: str, output_id: str) -> dict[str, Any]:
    return mastering_prepare_mp3(asset_id, output_id)


@mcp.tool(
    name="eirosmaster.mastering_delete_output",
    title="Delete one rendered master",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True, idempotentHint=True),
    structured_output=True,
)
def mastering_delete_output_connector_alias(asset_id: str, output_id: str) -> dict[str, Any]:
    return mastering_delete_output(asset_id, output_id)


@mcp.tool(
    name="eirosmaster.mastering_share_create",
    title="Create a private share link",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def mastering_share_create_connector_alias(
    asset_id: str, output_id: str, expires_days: int = 30
) -> dict[str, Any]:
    return mastering_share_create(asset_id, output_id, expires_days)


@mcp.tool(
    name="eirosmaster.mastering_share_revoke",
    title="Revoke a mastering share link",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True, idempotentHint=True),
    structured_output=True,
)
def mastering_share_revoke_connector_alias(token: str) -> dict[str, Any]:
    return mastering_share_revoke(token)


@mcp.tool(
    name="eirosmaster.mastering_plan_create", title="Create Director mastering plan",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False), structured_output=True,
)
def mastering_plan_create_connector_alias(asset_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    return mastering_plan_create(asset_id, plan)


@mcp.tool(
    name="eirosmaster.mastering_plan_get", title="Get Director mastering plan",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True), structured_output=True,
)
def mastering_plan_get_connector_alias(asset_id: str, plan_id: str) -> dict[str, Any]:
    return mastering_plan_get(asset_id, plan_id)


@mcp.tool(
    name="eirosmaster.mastering_render_directed", title="Render Director master",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False), structured_output=True,
)
def mastering_render_directed_connector_alias(asset_id: str, plan_id: str, label: str = "master") -> dict[str, Any]:
    return mastering_render_directed(asset_id, plan_id, label)


@mcp.tool(
    name="eirosmaster.mastering_verify", title="Verify rendered master",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True), structured_output=True,
)
def mastering_verify_connector_alias(asset_id: str, output_id: str) -> dict[str, Any]:
    return mastering_verify(asset_id, output_id)


@mcp.tool(
    name="eirosmaster.mastering_approve", title="Approve verified master",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True), structured_output=True,
)
def mastering_approve_connector_alias(asset_id: str, output_id: str) -> dict[str, Any]:
    return mastering_approve(asset_id, output_id)


@mcp.tool(
    name="eirosmaster.mastering_metadata_audit", title="Audit audio metadata",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True), structured_output=True,
)
def mastering_metadata_audit_connector_alias(asset_id: str) -> dict[str, Any]:
    return mastering_metadata_audit(asset_id)


@mcp.tool(
    name="eirosmaster.mastering_experience_similar", title="Find similar mastering experience",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True), structured_output=True,
)
def mastering_experience_similar_connector_alias(asset_id: str, intent_tags: list[str] | None = None, protected_traits: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
    return mastering_experience_similar(asset_id, intent_tags, protected_traits, limit)


@mcp.tool(
    name="eirosmaster.mastering_feedback_record", title="Record mastering feedback",
    description="Compatibility alias for the ChatGPT connector namespace.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False), structured_output=True,
)
def mastering_feedback_record_connector_alias(asset_id: str, output_id: str, feedback: str, intent_tags: list[str] | None = None) -> dict[str, Any]:
    return mastering_feedback_record(asset_id, output_id, feedback, intent_tags)


def _download_response(resolved: dict[str, Any], inline: bool = False) -> FileResponse:
    response = FileResponse(
        path=str(resolved["path"]),
        media_type=str(resolved["media_type"]),
        filename=str(resolved["filename"]),
        content_disposition_type="inline" if inline else "attachment",
    )
    response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    response.headers["Accept-Ranges"] = "bytes"
    return response


def _share_error_page(message: str, status_code: int = 404) -> HTMLResponse:
    safe = html.escape(message)
    return HTMLResponse(
        f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>EIROS Mastering</title><style>:root{{color-scheme:dark}}body{{margin:0;background:#090c12;color:#eef3ff;font:16px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;display:grid;place-items:center;min-height:100vh}}main{{max-width:520px;padding:28px;text-align:center}}p{{color:#aeb9cd}}</style></head>
        <body><main><h1>Ссылка недоступна</h1><p>{safe}</p></main></body></html>""",
        status_code=status_code,
    )


def _share_page(token: str, resolved: dict[str, Any]) -> HTMLResponse:
    share = resolved["share"]
    output = resolved["output"]
    filename = html.escape(str(output.get("filename") or "EIROS master"))
    profile = html.escape(str(output.get("profile") or "adaptive"))
    loudness = (output.get("report") or {}).get("loudness") or {}
    lufs = html.escape(str(loudness.get("integrated_lufs", "—")))
    peak = html.escape(str(loudness.get("true_peak_dbtp", "—")))
    expires = time.strftime("%Y-%m-%d", time.gmtime(int(share.get("expires_at") or 0)))
    safe_token = html.escape(token, quote=True)
    return HTMLResponse(f"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<meta name="theme-color" content="#0b0f18"><meta property="og:title" content="{filename}">
<meta property="og:description" content="EIROS adaptive master · {lufs} LUFS · {peak} dBTP">
<title>{filename}</title>
<style>
:root{{color-scheme:dark;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:radial-gradient(circle at 20% 0,#17264a 0,#0a0e16 42%,#06080d 100%);color:#edf3ff;display:grid;place-items:center;padding:20px}}
.card{{width:min(620px,100%);border:1px solid #35415b;border-radius:24px;background:#101624dd;box-shadow:0 24px 80px #0009;overflow:hidden}}
.head{{padding:22px;border-bottom:1px solid #2d374b}}.brand{{color:#76a8ff;font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}}
h1{{font-size:22px;line-height:1.25;word-break:break-word;margin:10px 0 7px}}.meta,.expiry{{color:#9eabc1;font-size:13px}}
.body{{padding:22px;display:grid;gap:18px}}audio{{width:100%}}.actions{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
a{{display:block;text-align:center;text-decoration:none;color:white;background:#1e579d;border:1px solid #568de0;border-radius:12px;padding:13px;font-weight:800}}
a.secondary{{background:#1a202d;border-color:#46536c}}.expiry{{text-align:center;font-size:11px}}
</style></head>
<body><main class="card"><div class="head"><div class="brand">EIROS MASTERING</div><h1>{filename}</h1><div class="meta">{profile} · {lufs} LUFS · {peak} dBTP</div></div>
<div class="body"><audio controls preload="metadata" src="/s/{safe_token}/audio.mp3"></audio>
<div class="actions"><a href="/s/{safe_token}/download.mp3">Скачать MP3</a><a class="secondary" href="/s/{safe_token}/download.wav">Скачать WAV</a></div>
<div class="expiry">Ссылка действует до {expires} UTC</div></div></main></body></html>""")


def _cors(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Cache-Control"] = "no-store"
    return response


def _json_error(exc: Exception, status_code: int = 400) -> Response:
    return _cors(JSONResponse({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=status_code))


def _options() -> Response:
    return _cors(Response(status_code=204))


@mcp.custom_route("/api/calibration", methods=["GET"])
async def api_calibration(request: Request) -> Response:
    html_text = Path(__file__).with_name("mastering_calibration.html").read_text(encoding="utf-8")
    return HTMLResponse(
        html_text,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@mcp.custom_route("/api/calibration/profile/save", methods=["POST", "OPTIONS"])
async def api_calibration_profile_save(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        raw = await request.json()
        if not isinstance(raw, dict):
            raise ValueError("JSON object required")
        name = str(raw.get("name") or "Calibration profile")
        profile = raw.get("profile")
        code = str(raw.get("code") or "")
        return _cors(JSONResponse(mastering_engine.save_calibration_profile(name, profile, code)))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/calibration/profile/load", methods=["POST", "OPTIONS"])
async def api_calibration_profile_load(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        raw = await request.json()
        if not isinstance(raw, dict):
            raise ValueError("JSON object required")
        code = str(raw.get("code") or "")
        return _cors(JSONResponse(mastering_engine.load_calibration_profile(code)))
    except FileNotFoundError as exc:
        return _json_error(exc, 404)
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/calibration/mic-loop", methods=["GET"])
async def api_calibration_mic_loop(request: Request) -> Response:
    html_text = Path(__file__).with_name("mastering_mic_loop.html").read_text(encoding="utf-8")
    return HTMLResponse(
        html_text,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@mcp.custom_route("/api/calibration/mic-loop/analyze", methods=["POST", "OPTIONS"])
async def api_calibration_mic_loop_analyze(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        recordings: dict[str, tuple[str, bytes]] = {}
        expected_gain_db: float | None = None
        async with request.form(max_files=4, max_fields=8, max_part_size=32 * 1024 * 1024) as form:
            for key in ("background", "baseline_a", "baseline_b", "stress"):
                upload = form.get(key)
                if upload is None:
                    continue
                if not hasattr(upload, "read"):
                    raise ValueError(f"multipart field '{key}' must be a file")
                data = await upload.read()
                filename = str(getattr(upload, "filename", "") or f"{key}.bin")
                recordings[key] = (filename, data)
            baseline_db_raw = form.get("baseline_db")
            stress_db_raw = form.get("stress_db")
            if baseline_db_raw is not None and stress_db_raw is not None:
                expected_gain_db = float(str(stress_db_raw)) - float(str(baseline_db_raw))
        return _cors(JSONResponse(mastering_engine.analyze_mic_loop_recordings(
            recordings, expected_gain_db=expected_gain_db
        )))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/health", methods=["GET", "OPTIONS"])
async def api_health(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    return _cors(JSONResponse(mastering_health()))


@mcp.custom_route("/api/upload", methods=["POST", "OPTIONS"])
async def api_upload(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        async with request.form(max_files=1, max_fields=8, max_part_size=mastering_engine.MAX_UPLOAD_BYTES) as form:
            upload = form.get("file")
            if upload is None or not hasattr(upload, "read"):
                raise ValueError("multipart field 'file' is required")
            data = await upload.read()
            filename = str(getattr(upload, "filename", "") or "audio.wav")
        return _cors(JSONResponse(mastering_engine.store_upload(filename, data)))
    except Exception as exc:
        return _json_error(exc)


async def _read_json(request: Request) -> dict[str, Any]:
    raw = await request.json()
    if not isinstance(raw, dict):
        raise ValueError("JSON object required")
    return raw


@mcp.custom_route("/api/analyze", methods=["POST", "OPTIONS"])
async def api_analyze(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(mastering_engine.analyze(str(body.get("asset_id") or ""), bool(body.get("force", False)))))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/render", methods=["POST", "OPTIONS"])
async def api_render(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        result = mastering_engine.render(
            str(body.get("asset_id") or ""),
            str(body.get("profile") or "adaptive"),
            float(body.get("target_lufs", -14.0)),
            float(body.get("true_peak_dbtp", -1.0)),
            str(body.get("label") or "spotify"),
        )
        return _cors(JSONResponse(result))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/plan/create", methods=["POST", "OPTIONS"])
async def api_plan_create(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(mastering_plan_create(str(body.get("asset_id") or ""), dict(body.get("plan") or {}))))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/plan/get", methods=["POST", "OPTIONS"])
async def api_plan_get(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(mastering_plan_get(str(body.get("asset_id") or ""), str(body.get("plan_id") or ""))))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/render-directed", methods=["POST", "OPTIONS"])
async def api_render_directed(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(mastering_render_directed(str(body.get("asset_id") or ""), str(body.get("plan_id") or ""), str(body.get("label") or "master"))))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/verify", methods=["POST", "OPTIONS"])
async def api_verify(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(mastering_verify(str(body.get("asset_id") or ""), str(body.get("output_id") or ""))))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/approve", methods=["POST", "OPTIONS"])
async def api_approve(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(mastering_approve(str(body.get("asset_id") or ""), str(body.get("output_id") or ""))))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/metadata-audit", methods=["POST", "OPTIONS"])
async def api_metadata_audit(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(mastering_metadata_audit(str(body.get("asset_id") or ""))))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/experience-similar", methods=["POST", "OPTIONS"])
async def api_experience_similar(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(mastering_experience_similar(
            str(body.get("asset_id") or ""), list(body.get("intent_tags") or []),
            list(body.get("protected_traits") or []), int(body.get("limit", 5)),
        )))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/feedback", methods=["POST", "OPTIONS"])
async def api_feedback_record(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(mastering_feedback_record(
            str(body.get("asset_id") or ""), str(body.get("output_id") or ""),
            str(body.get("feedback") or ""), list(body.get("intent_tags") or []),
        )))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/list", methods=["GET", "OPTIONS"])
async def api_list(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        limit = max(1, min(int(request.query_params.get("limit", "30")), 100))
        return _cors(JSONResponse(mastering_engine.list_assets(limit)))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/delete", methods=["POST", "OPTIONS"])
async def api_delete(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(mastering_engine.delete_asset(str(body.get("asset_id") or ""))))
    except Exception as exc:
        return _json_error(exc)



@mcp.custom_route("/api/output/delete", methods=["POST", "OPTIONS"])
async def api_output_delete(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        result = mastering_engine.delete_output(
            str(body.get("asset_id") or ""),
            str(body.get("output_id") or ""),
        )
        return _cors(JSONResponse(result))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/mp3", methods=["POST", "OPTIONS"])
async def api_mp3(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        asset_id = str(body.get("asset_id") or "")
        output_id = str(body.get("output_id") or "")
        result = dict(mastering_engine.ensure_mp3(asset_id, output_id))
        result.pop("path", None)
        return _cors(JSONResponse({"ok": True, "asset_id": asset_id, "output_id": output_id, "mp3": result}))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/share", methods=["POST", "OPTIONS"])
async def api_share_create(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        result = mastering_engine.create_share(
            str(body.get("asset_id") or ""),
            str(body.get("output_id") or ""),
            int(body.get("expires_days", 30)),
        )
        result["public_url"] = f"{PUBLIC_SHARE_BASE}/{result['token']}"
        return _cors(JSONResponse(result))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/client-log", methods=["POST", "OPTIONS"])
async def api_client_log(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        allowed = {
            key: str(body.get(key, ""))[:300]
            for key in ("panel", "kind", "name", "message", "media_code", "network_state", "ready_state")
        }
        print("EIROS_WIDGET_AUDIO " + json.dumps(allowed, ensure_ascii=False), flush=True)
        return _cors(JSONResponse({"ok": True}))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/api/share/revoke", methods=["POST", "OPTIONS"])
async def api_share_revoke(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        body = await _read_json(request)
        return _cors(JSONResponse(mastering_engine.revoke_share(str(body.get("token") or ""))))
    except Exception as exc:
        return _json_error(exc)


@mcp.custom_route("/s/{token}", methods=["GET"])
async def public_share_page(request: Request) -> Response:
    token = str(request.path_params.get("token") or "")
    try:
        resolved = mastering_engine.resolve_share(token)
        return _share_page(token, resolved)
    except Exception as exc:
        return _share_error_page(str(exc), 404)


@mcp.custom_route("/s/{token}/{action}", methods=["GET"])
async def public_share_file(request: Request) -> Response:
    token = str(request.path_params.get("token") or "")
    action = str(request.path_params.get("action") or "")
    try:
        resolved = mastering_engine.resolve_share(token)
        share = resolved["share"]
        if action == "audio.mp3":
            fmt, inline = "mp3", True
        elif action == "download.mp3":
            fmt, inline = "mp3", False
        elif action == "download.wav":
            fmt, inline = "wav", False
        else:
            return _share_error_page("Unknown shared file", 404)
        file_info = mastering_engine.resolve_output_file(
            str(share.get("asset_id") or ""),
            str(share.get("output_id") or ""),
            fmt,
        )
        response = _download_response(file_info, inline)
        response.headers["Cache-Control"] = "public, max-age=3600" if inline else "no-store"
        return response
    except Exception as exc:
        return _share_error_page(str(exc), 404)


@mcp.custom_route("/api/timeline", methods=["GET", "OPTIONS"])
async def api_timeline(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        asset_id = str(request.query_params.get("asset_id") or "")
        output_id = str(request.query_params.get("output_id") or "").strip() or None
        points = int(request.query_params.get("points") or 384)
        return _cors(JSONResponse(mastering_engine.timeline_payload(asset_id, output_id, points)))
    except Exception as exc:
        return _json_error(exc, 404)


@mcp.custom_route("/api/analysis-view", methods=["GET", "OPTIONS"])
async def api_analysis_view(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        asset_id = str(request.query_params.get("asset_id") or "")
        output_id = str(request.query_params.get("output_id") or "")
        return _cors(JSONResponse(mastering_engine.analysis_payload(asset_id, output_id)))
    except Exception as exc:
        return _json_error(exc, 404)


@mcp.custom_route("/api/ab", methods=["GET", "OPTIONS"])
async def api_ab(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        asset_id = str(request.query_params.get("asset_id") or "")
        output_id = str(request.query_params.get("output_id") or "")
        return _cors(JSONResponse(mastering_engine.ab_comparison(asset_id, output_id)))
    except Exception as exc:
        return _json_error(exc, 404)


@mcp.custom_route("/api/delta", methods=["GET", "OPTIONS"])
async def api_delta(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        asset_id = str(request.query_params.get("asset_id") or "")
        output_id = str(request.query_params.get("output_id") or "")
        inline = str(request.query_params.get("inline") or "").lower() in {"1", "true", "yes"}
        info = mastering_engine.ensure_delta_preview(asset_id, output_id)
        resolved = {"path": info["path"], "media_type": "audio/mpeg", "filename": info["filename"]}
        return _cors(_download_response(resolved, inline))
    except Exception as exc:
        return _json_error(exc, 404)


@mcp.custom_route("/api/player", methods=["GET"])
async def api_player(request: Request) -> Response:
    try:
        asset_id = str(request.query_params.get("asset_id") or "")
        output_id = str(request.query_params.get("output_id") or "")
        resolved = mastering_engine.resolve_output_file(asset_id, output_id, "preview")
        source_resolved = mastering_engine.resolve_source_file(asset_id, "preview")
        master_stat = Path(str(resolved["path"])).stat()
        source_stat = Path(str(source_resolved["path"])).stat()
        master_version = f"{master_stat.st_size:x}-{master_stat.st_mtime_ns:x}"
        source_version = f"{source_stat.st_size:x}-{source_stat.st_mtime_ns:x}"
        comparison = mastering_engine.ab_comparison(asset_id, output_id)
        comparison_json = (
            json.dumps(comparison, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
        )
        safe_title = html.escape(
            str(resolved.get("filename") or "EIROS master preview")
            .lstrip(".")
            .replace(".preview.mp3", ".mp3")
        )
        master_url = html.escape(
            f"{PUBLIC_BASE}/api/download?"
            f"asset_id={asset_id}&output_id={output_id}&format=preview&inline=1&v={master_version}",
            quote=True,
        )
        source_url = html.escape(
            f"{PUBLIC_BASE}/api/source?"
            f"asset_id={asset_id}&format=preview&inline=1&v={source_version}",
            quote=True,
        )
        page = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>__TITLE__</title>
<style>
:root{color-scheme:dark;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
*{box-sizing:border-box}
html,body{margin:0;background:#090a0c;color:#eef0f4}
body{padding:0}
.player{min-height:408px;border:1px solid #262a31;border-radius:12px;background:#0d0f12;padding:11px;overflow:hidden}
.top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:9px}
.identity{min-width:0}
.kicker{color:#737b88;font-size:8px;font-weight:750;letter-spacing:.16em}
.name{max-width:260px;margin-top:3px;overflow:hidden;color:#c7cbd3;font-size:10px;text-overflow:ellipsis;white-space:nowrap}
.ab{display:grid;grid-template-columns:1fr 1fr;flex:0 0 206px;padding:3px;border:1px solid #2a2e35;border-radius:9px;background:#08090b}
.ab button{height:28px;border:0;border-radius:6px;background:transparent;color:#737b88;font:750 8px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;letter-spacing:.08em}
.ab button.active{background:#e9ecf1;color:#0a0b0d}
.transport{display:flex;align-items:center;gap:10px}
.play{position:relative;flex:0 0 36px;width:36px;height:36px;border:1px solid #353a43;border-radius:50%;background:#171a1f;color:#fff}
.play:active{transform:scale(.97)}
.playMark{position:absolute;left:14px;top:11px;width:0;height:0;border-top:7px solid transparent;border-bottom:7px solid transparent;border-left:10px solid #eef0f4}
.pauseMark{display:none;position:absolute;left:12px;top:11px;width:12px;height:14px;border-left:4px solid #eef0f4;border-right:4px solid #eef0f4}
.play.playing .playMark{display:none}
.play.playing .pauseMark{display:block}
.timeline{min-width:0;flex:1}
.seek{--progress:0%;display:block;width:100%;height:18px;margin:0;appearance:none;background:transparent}
.seek::-webkit-slider-runnable-track{height:3px;border-radius:99px;background:linear-gradient(90deg,#dfe3e9 0 var(--progress),#30343b var(--progress) 100%)}
.seek::-webkit-slider-thumb{width:13px;height:13px;margin-top:-5px;appearance:none;border:2px solid #0d0f12;border-radius:50%;background:#f1f3f6;box-shadow:0 0 0 1px #5b626e}
.seek::-moz-range-track{height:3px;border-radius:99px;background:#30343b}
.seek::-moz-range-progress{height:3px;border-radius:99px;background:#dfe3e9}
.seek::-moz-range-thumb{width:11px;height:11px;border:2px solid #0d0f12;border-radius:50%;background:#f1f3f6}
.readout{display:grid;grid-template-columns:46px 1fr 46px;align-items:center;margin-top:3px;color:#777f8b;font-size:8px;font-variant-numeric:tabular-nums}
.readout span:nth-child(2){overflow:hidden;text-align:center;text-overflow:ellipsis;white-space:nowrap;font-weight:800;letter-spacing:.11em}
.readout span:last-child{text-align:right}
.measures{display:grid;grid-template-columns:1.35fr repeat(3,minmax(0,1fr));gap:5px;margin-top:9px}
.measure{min-width:0;padding:7px 8px;border:1px solid #252a31;border-radius:8px;background:#0a0c0f;transition:border-color .16s,background .16s}
.measure span{display:block;color:#636b76;font-size:7px;font-weight:750;letter-spacing:.09em}
.measure b{display:block;overflow:hidden;margin-top:3px;color:#e3e6eb;font-size:11px;font-weight:800;text-overflow:ellipsis;white-space:nowrap;font-variant-numeric:tabular-nums}
.player[data-mode="source"] .measure{border-color:#29384d;background:#0b1018}
.player[data-mode="master"] .measure{border-color:#244139;background:#09120f}
.player[data-mode="source"] .measure.current b{color:#83aff4}
.player[data-mode="master"] .measure.current b{color:#55d4b0}
.modeSummary{margin-top:5px;padding:5px 8px;border:1px solid #252a31;border-radius:7px;color:#747d89;font-size:7px;font-weight:750;letter-spacing:.055em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.player[data-mode="source"] .modeSummary{border-color:#29384d;color:#83aff4}
.player[data-mode="master"] .modeSummary{border-color:#244139;color:#55d4b0}
.chart{margin-top:7px;padding:7px 7px 5px;border:1px solid #252a31;border-radius:9px;background:#090b0e}
.chartHead{display:flex;justify-content:space-between;color:#626a75;font-size:7px;font-weight:750;letter-spacing:.12em}
.chart svg{display:block;width:100%;height:89px;margin-top:2px;overflow:visible}
.gridline{stroke:#252a31;stroke-width:1;vector-effect:non-scaling-stroke}
.curve{fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke;transition:opacity .15s,stroke-width .15s}
.sourceCurve{stroke:#aeb6c2}.masterCurve{stroke:#45d1aa}
.player[data-mode="source"] .sourceCurve{opacity:1;stroke-width:3}.player[data-mode="source"] .masterCurve{opacity:.04}
.player[data-mode="master"] .sourceCurve{opacity:.08}.player[data-mode="master"] .masterCurve{opacity:1;stroke-width:3}
.player[data-mode="source"] .chart{border-color:#29384d}.player[data-mode="master"] .chart{border-color:#244139}
.chartLabel{fill:#5e6671;font-size:7px;font-weight:700;text-anchor:middle}
.sourceDot{fill:#aeb6c2}.masterDot{fill:#45d1aa}
.deltaRow{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:3px;margin-top:1px}
.delta{min-width:0;text-align:center}
.delta span{display:block;overflow:hidden;color:#555d68;font-size:6px;font-weight:750;text-overflow:ellipsis;white-space:nowrap}
.delta b{display:block;margin-top:2px;color:#8d96a2;font-size:7px;font-variant-numeric:tabular-nums}
.delta b.up{color:#55c8a9}.delta b.down{color:#c38c95}
.legend{display:flex;gap:12px;margin-top:4px;color:#646c77;font-size:7px;font-weight:700;letter-spacing:.08em}
.legend span:before{content:"";display:inline-block;width:13px;height:2px;margin:0 5px 2px 0;border-radius:2px;background:#aeb6c2}
.legend span:last-child:before{background:#45d1aa}
.processMap{margin-top:7px;padding:7px;border:1px solid #252a31;border-radius:9px;background:#090b0e;transition:border-color .15s}
.player[data-mode="source"] .processMap{border-color:#29384d}.player[data-mode="master"] .processMap{border-color:#3e292f}
.processHead{display:flex;align-items:center;justify-content:space-between;gap:8px;color:#626a75;font-size:7px;font-weight:750;letter-spacing:.11em}
.processHead span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:right}
.processMap canvas{display:block;width:100%;height:84px;margin-top:3px}
.processNote{margin-top:2px;color:#59616c;font-size:7px;line-height:1.25}
audio{display:none}
@media(max-width:410px){
  .player{padding:9px}.ab{flex-basis:176px}.name{max-width:130px}
  .measure{padding:5px}.measure b{font-size:9px}.chart{padding-left:4px;padding-right:4px}
}
</style>
</head>
<body>
<div id="player" class="player" data-mode="master">
  <div class="top">
    <div class="identity">
      <div class="kicker">EIROS A/B MONITOR</div>
      <div class="name">__TITLE__</div>
    </div>
    <div class="ab" role="group" aria-label="Источник воспроизведения">
      <button type="button" data-mode="source">A · UPLOAD</button>
      <button type="button" class="active" data-mode="master">B · MASTER</button>
    </div>
  </div>
  <div class="transport">
    <button id="play" class="play" type="button" aria-label="Воспроизвести">
      <span class="playMark"></span><span class="pauseMark"></span>
    </button>
    <div class="timeline">
      <input id="seek" class="seek" type="range" min="0" max="1000" value="0" step="1" aria-label="Позиция">
      <div class="readout">
        <span id="current">0:00</span>
        <span id="state">B · MASTER</span>
        <span id="duration">0:00</span>
      </div>
    </div>
  </div>
  <div class="measures">
    <div class="measure current"><span>NOW PLAYING</span><b id="nowTrack">B · MASTER</b></div>
    <div class="measure"><span>INTEGRATED</span><b id="nowLufs">— LUFS</b></div>
    <div class="measure"><span>TRUE PEAK</span><b id="nowPeak">— dBTP</b></div>
    <div class="measure"><span>DYNAMICS · LRA</span><b id="nowLra">— LU</b></div>
  </div>
  <div id="modeSummary" class="modeSummary">B · MASTER DATA</div>
  <div class="chart">
    <div class="chartHead"><span id="chartMode">B · MASTER SPECTRUM</span><span id="chartScope">MASTER RESPONSE</span></div>
    <svg id="spectrum" viewBox="0 0 600 104" preserveAspectRatio="none" role="img" aria-label="Сравнение спектра оригинала и мастера">
      <line class="gridline" x1="16" y1="18" x2="584" y2="18"></line>
      <line class="gridline" x1="16" y1="39" x2="584" y2="39"></line>
      <line class="gridline" x1="16" y1="60" x2="584" y2="60"></line>
      <line class="gridline" x1="16" y1="81" x2="584" y2="81"></line>
      <polyline id="sourceLine" class="curve sourceCurve" points=""></polyline>
      <polyline id="masterLine" class="curve masterCurve" points=""></polyline>
      <g id="sourceDots"></g>
      <g id="masterDots"></g>
      <g id="chartLabels"></g>
    </svg>
    <div id="deltaRow" class="deltaRow"></div>
    <div class="legend"><span>A · UPLOAD</span><span>B · MASTER</span></div>
  </div>
  <div class="processMap">
    <div class="processHead">
      <span>B · PROCESSING MAP</span>
      <span id="processMeta">ANALYSIS</span>
    </div>
    <canvas id="processCanvas" width="600" height="92" aria-label="Карта адаптивной обработки по времени и частотам"></canvas>
    <div id="processNote" class="processNote">Цвет показывает фактическое ослабление диапазона мастером; вертикальная линия — текущая позиция.</div>
  </div>
  <audio id="source" preload="metadata" playsinline src="__SOURCE_URL__"></audio>
  <audio id="master" preload="metadata" playsinline src="__MASTER_URL__"></audio>
</div>
<script>
(function(){
  var comparison=__COMPARISON_JSON__;
  var root=document.getElementById('player');
  var tracks={source:document.getElementById('source'),master:document.getElementById('master')};
  var mode='master';
  var seeking=false;
  var play=document.getElementById('play');
  var seek=document.getElementById('seek');
  var current=document.getElementById('current');
  var duration=document.getElementById('duration');
  var state=document.getElementById('state');
  var buttons=[].slice.call(document.querySelectorAll('.ab button[data-mode]'));
  function active(){return tracks[mode]}
  function finite(value){var number=Number(value);return Number.isFinite(number)?number:0}
  function clock(value){
    var seconds=Math.max(0,Math.floor(finite(value)));
    var minutes=Math.floor(seconds/60);
    return minutes+':'+String(seconds%60).padStart(2,'0');
  }
  function textNumber(value,digits){
    var number=Number(value);
    return Number.isFinite(number)?number.toFixed(digits):'—';
  }
  function signed(value,digits){
    var number=Number(value);
    if(!Number.isFinite(number))return '—';
    return (number>0?'+':'')+number.toFixed(digits);
  }
  function paintModeMetrics(){
    var sourceLoud=comparison.source&&comparison.source.loudness?comparison.source.loudness:{};
    var masterLoud=comparison.master&&comparison.master.loudness?comparison.master.loudness:{};
    var loud=mode==='master'?masterLoud:sourceLoud;
    var isMaster=mode==='master';
    document.getElementById('nowTrack').textContent=isMaster?'B · MASTER':'A · UPLOAD';
    document.getElementById('nowLufs').textContent=textNumber(loud.integrated_lufs,1)+' LUFS';
    document.getElementById('nowPeak').textContent=textNumber(loud.true_peak_dbtp,2)+' dBTP';
    document.getElementById('nowLra').textContent=textNumber(loud.loudness_range_lu,1)+' LU';
    document.getElementById('chartMode').textContent=isMaster?'B · MASTER SPECTRUM':'A · UPLOAD SPECTRUM';
    document.getElementById('chartScope').textContent=isMaster?'MASTER RESPONSE':'ORIGINAL RESPONSE';
    if(isMaster){
      var profile=String(comparison.profile||'master').toUpperCase();
      var loudDelta=finite(masterLoud.integrated_lufs)-finite(sourceLoud.integrated_lufs);
      var peakDelta=finite(masterLoud.true_peak_dbtp)-finite(sourceLoud.true_peak_dbtp);
      var lraDelta=finite(masterLoud.loudness_range_lu)-finite(sourceLoud.loudness_range_lu);
      document.getElementById('modeSummary').textContent='Δ FROM UPLOAD · LUFS '+signed(loudDelta,1)+' · TP '+signed(peakDelta,2)+' dB · LRA '+signed(lraDelta,1)+' LU · '+profile;
    }else{
      document.getElementById('modeSummary').textContent='BYTE-EXACT UPLOADED MP3 · NO MASTER PROCESSING';
    }
    [].slice.call(document.querySelectorAll('.bandDelta')).forEach(function(node){
      var value=finite(node.getAttribute('data-delta'));
      node.className='bandDelta '+(isMaster?(value>.05?'up':(value<-.05?'down':'')):'');
      node.textContent=isMaster?((value>0?'+':'')+value.toFixed(2)+' dB'):'0.00 dB';
    });
  }
  function paint(){
    var audio=active();
    var total=finite(audio.duration);
    var at=finite(audio.currentTime);
    var progress=total>0?Math.min(100,Math.max(0,at/total*100)):0;
    if(!seeking)seek.value=String(Math.round(progress*10));
    seek.style.setProperty('--progress',progress+'%');
    current.textContent=clock(at);
    duration.textContent=clock(total);
    play.classList.toggle('playing',!audio.paused&&!audio.ended);
    play.setAttribute('aria-label',audio.paused?'Воспроизвести':'Пауза');
    state.textContent=mode==='master'?'B · MASTER':'A · UPLOAD';
    root.setAttribute('data-mode',mode);
    buttons.forEach(function(button){
      button.classList.toggle('active',button.getAttribute('data-mode')===mode);
      button.setAttribute('aria-pressed',button.getAttribute('data-mode')===mode?'true':'false');
    });
    paintModeMetrics();
    drawProcessingMap(at);
  }
  function place(audio,at){
    if(audio.readyState>=1){
      var max=finite(audio.duration)>0?Math.max(0,audio.duration-.02):at;
      try{audio.currentTime=Math.min(at,max)}catch(ignore){}
      paint();
      return;
    }
    audio.addEventListener('loadedmetadata',function(){place(audio,at)},{once:true});
  }
  async function select(next){
    if(!tracks[next]||next===mode)return;
    var before=active();
    var at=finite(before.currentTime);
    var wasPlaying=!before.paused&&!before.ended;
    before.pause();
    mode=next;
    var after=active();
    place(after,at);
    paint();
    if(wasPlaying){
      try{await after.play()}catch(error){state.textContent=(mode==='master'?'B':'A')+' · TAP PLAY'}
    }
  }
  function drawComparison(){
    var bands=Array.isArray(comparison.bands)?comparison.bands:[];
    if(!bands.length)return;
    var sourceDb=bands.map(function(band){return 10*Math.log10(Math.max(finite(band.source_percent),1e-9))});
    var masterDb=bands.map(function(band){return 10*Math.log10(Math.max(finite(band.master_percent),1e-9))});
    var ceiling=Math.max.apply(null,sourceDb.concat(masterDb));
    var floor=ceiling-24;
    function point(value,index){
      var x=16+(568*index/Math.max(1,bands.length-1));
      var clamped=Math.max(floor,Math.min(ceiling,value));
      var y=18+((ceiling-clamped)/24)*63;
      return {x:x,y:y};
    }
    var sourcePoints=sourceDb.map(point);
    var masterPoints=masterDb.map(point);
    document.getElementById('sourceLine').setAttribute('points',sourcePoints.map(function(p){return p.x+','+p.y}).join(' '));
    document.getElementById('masterLine').setAttribute('points',masterPoints.map(function(p){return p.x+','+p.y}).join(' '));
    var ns='http://www.w3.org/2000/svg';
    bands.forEach(function(band,index){
      var sourceCircle=document.createElementNS(ns,'circle');
      sourceCircle.setAttribute('class','sourceDot sourceCurve');
      sourceCircle.setAttribute('cx',sourcePoints[index].x);
      sourceCircle.setAttribute('cy',sourcePoints[index].y);
      sourceCircle.setAttribute('r','2.6');
      document.getElementById('sourceDots').appendChild(sourceCircle);
      var masterCircle=document.createElementNS(ns,'circle');
      masterCircle.setAttribute('class','masterDot masterCurve');
      masterCircle.setAttribute('cx',masterPoints[index].x);
      masterCircle.setAttribute('cy',masterPoints[index].y);
      masterCircle.setAttribute('r','2.6');
      document.getElementById('masterDots').appendChild(masterCircle);
      var label=document.createElementNS(ns,'text');
      label.setAttribute('class','chartLabel');
      label.setAttribute('x',sourcePoints[index].x);
      label.setAttribute('y','101');
      label.textContent=band.label;
      document.getElementById('chartLabels').appendChild(label);
      var delta=document.createElement('div');
      delta.className='delta';
      var deltaLabel=document.createElement('span');
      deltaLabel.textContent=band.label;
      var deltaValue=document.createElement('b');
      var value=finite(band.tonal_delta_db);
      deltaValue.className='bandDelta '+(value>.05?'up':(value<-.05?'down':''));
      deltaValue.setAttribute('data-delta',String(value));
      deltaValue.textContent=(value>0?'+':'')+value.toFixed(2)+' dB';
      delta.appendChild(deltaLabel);
      delta.appendChild(deltaValue);
      document.getElementById('deltaRow').appendChild(delta);
    });
    paintModeMetrics();
  }
  function drawProcessingMap(playhead){
    var canvas=document.getElementById('processCanvas');
    var ctx=canvas&&canvas.getContext?canvas.getContext('2d'):null;
    if(!ctx)return;
    var map=comparison.processing_map||{};
    var points=Array.isArray(map.points)?map.points:[];
    var bands=Array.isArray(comparison.bands)?comparison.bands:[];
    var width=canvas.width;
    var height=canvas.height;
    var left=64;
    var right=8;
    var top=5;
    var bottom=17;
    var plotWidth=width-left-right;
    var plotHeight=height-top-bottom;
    var rows=Math.max(1,bands.length);
    var rowHeight=plotHeight/rows;
    ctx.clearRect(0,0,width,height);
    ctx.fillStyle='#090b0e';
    ctx.fillRect(0,0,width,height);
    ctx.font='7px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
    ctx.textBaseline='middle';
    bands.forEach(function(band,index){
      var y=top+index*rowHeight;
      ctx.fillStyle=index%2?'#0c0e11':'#0a0c0f';
      ctx.fillRect(left,y,plotWidth,rowHeight);
      ctx.strokeStyle='#24282f';
      ctx.lineWidth=1;
      ctx.beginPath();
      ctx.moveTo(left,y+rowHeight);
      ctx.lineTo(width-right,y+rowHeight);
      ctx.stroke();
      ctx.fillStyle='#68717d';
      ctx.textAlign='right';
      ctx.fillText(String(band.label||''),left-7,y+rowHeight/2);
    });
    var meta=document.getElementById('processMeta');
    var note=document.getElementById('processNote');
    if(mode==='source'){
      meta.textContent='A · UPLOAD · ORIGINAL';
      note.textContent='Исходный загруженный файл. Обработка мастера здесь не применяется.';
      ctx.fillStyle='#83aff4';
      ctx.textAlign='center';
      ctx.font='700 9px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
      ctx.fillText('ORIGINAL UPLOAD · NO PROCESSING',left+plotWidth/2,top+plotHeight/2);
      return;
    }
    if(map.mode!=='adaptive'||!points.length||!bands.length){
      meta.textContent=String(comparison.profile||'GLOBAL').toUpperCase()+' · LEVEL ONLY';
      note.textContent='Секционной частотной обработки нет: изменены только общий уровень и true peak.';
      ctx.fillStyle='#666e79';
      ctx.textAlign='center';
      ctx.font='700 9px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
      ctx.fillText('NO SECTION EQ · GLOBAL LOUDNESS ONLY',left+plotWidth/2,top+plotHeight/2);
      return;
    }
    var maxCut=.25;
    points.forEach(function(point){
      bands.forEach(function(band){
        maxCut=Math.max(maxCut,Math.abs(finite((point.bands||{})[band.key])));
      });
    });
    var cellWidth=plotWidth/points.length;
    points.forEach(function(point,column){
      bands.forEach(function(band,row){
        var cut=finite((point.bands||{})[band.key]);
        var intensity=Math.min(1,Math.abs(cut)/maxCut);
        var alpha=.035+intensity*.84;
        ctx.fillStyle='rgba(221,105,123,'+alpha.toFixed(3)+')';
        ctx.fillRect(left+column*cellWidth,top+row*rowHeight,Math.max(1,cellWidth+.25),rowHeight);
      });
    });
    var mapDuration=finite(map.duration_seconds)||finite(active().duration);
    ctx.strokeStyle='#30353d';
    ctx.fillStyle='#5f6772';
    ctx.lineWidth=1;
    ctx.font='7px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
    for(var tick=0;tick<=4;tick++){
      var ratio=tick/4;
      var x=left+plotWidth*ratio;
      ctx.beginPath();
      ctx.moveTo(x,top);
      ctx.lineTo(x,top+plotHeight);
      ctx.stroke();
      ctx.textAlign=tick===0?'left':(tick===4?'right':'center');
      ctx.fillText(clock(mapDuration*ratio),x,height-6);
    }
    if(mapDuration>0){
      var cursorX=left+plotWidth*Math.max(0,Math.min(1,finite(playhead)/mapDuration));
      ctx.strokeStyle='#f0f2f5';
      ctx.lineWidth=1.4;
      ctx.beginPath();
      ctx.moveTo(cursorX,top-1);
      ctx.lineTo(cursorX,top+plotHeight+1);
      ctx.stroke();
    }
    meta.textContent='ADAPTIVE · MAX CUT '+(-maxCut).toFixed(2)+' dB';
    var gain=map.gain_ride_summary||{};
    note.textContent='Фактические локальные EQ-срезы по времени · gain ride до '+textNumber(gain.max_cut_db,2)+' dB · секций: '+String(comparison.section_count||0)+'.';
  }
  play.addEventListener('click',async function(){
    var audio=active();
    try{
      if(audio.paused)await audio.play();
      else audio.pause();
    }catch(error){state.textContent=(mode==='master'?'B':'A')+' · UNAVAILABLE'}
    paint();
  });
  buttons.forEach(function(button){
    button.addEventListener('click',function(){select(button.getAttribute('data-mode'))});
  });
  seek.addEventListener('input',function(){
    seeking=true;
    var total=finite(active().duration);
    var progress=Number(seek.value)/1000;
    seek.style.setProperty('--progress',(progress*100)+'%');
    current.textContent=clock(total*progress);
  });
  seek.addEventListener('change',function(){
    var audio=active();
    var total=finite(audio.duration);
    if(total>0)audio.currentTime=total*(Number(seek.value)/1000);
    seeking=false;
    paint();
  });
  Object.keys(tracks).forEach(function(key){
    var audio=tracks[key];
    ['timeupdate','durationchange','loadedmetadata','play','pause','ended','canplay'].forEach(function(eventName){
      audio.addEventListener(eventName,function(){if(key===mode)paint()});
    });
    audio.addEventListener('waiting',function(){if(key===mode)state.textContent=(mode==='master'?'B':'A')+' · BUFFERING'});
    audio.addEventListener('error',function(){if(key===mode)state.textContent=(mode==='master'?'B':'A')+' · UNAVAILABLE'});
  });
  drawComparison();
  paint();
})();
</script>
</body>
</html>"""
        page = (
            page.replace("__TITLE__", safe_title)
            .replace("__SOURCE_URL__", source_url)
            .replace("__MASTER_URL__", master_url)
            .replace("__COMPARISON_JSON__", comparison_json)
        )
        return HTMLResponse(
            page,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'none'; media-src 'self'; "
                    "style-src 'unsafe-inline'; script-src 'unsafe-inline'"
                ),
                "Referrer-Policy": "no-referrer",
            },
        )
    except Exception as exc:
        return _share_error_page(str(exc), 404)


@mcp.custom_route("/api/source", methods=["GET", "OPTIONS"])
async def api_source(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        asset_id = str(request.query_params.get("asset_id") or "")
        inline = str(request.query_params.get("inline") or "").lower() in {"1", "true", "yes"}
        resolved = mastering_engine.resolve_source_file(asset_id, "preview")
        return _cors(_download_response(resolved, inline))
    except Exception as exc:
        return _json_error(exc, 404)


@mcp.custom_route("/api/download", methods=["GET", "OPTIONS"])
async def api_download(request: Request) -> Response:
    if request.method == "OPTIONS":
        return _options()
    try:
        asset_id = str(request.query_params.get("asset_id") or "")
        output_id = str(request.query_params.get("output_id") or "")
        file_format = str(request.query_params.get("format") or "wav").lower()
        inline = str(request.query_params.get("inline") or "").lower() in {"1", "true", "yes"}
        resolved = mastering_engine.resolve_output_file(asset_id, output_id, file_format)
        return _cors(_download_response(resolved, inline))
    except Exception as exc:
        return _json_error(exc, 404)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
