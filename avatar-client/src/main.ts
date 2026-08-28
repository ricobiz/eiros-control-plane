import './style.css';
import { AvatarRenderer } from './renderer';
import { VrmAdapter } from './vrm-adapter';
import { BehaviorEngine } from './behavior-engine';
import { LocalAvatarSimulator, type SimulatorControls } from './simulator';
import { AvatarStreamController, LocalTransport } from './transport';
import { PerfMonitor } from './perf-monitor';

const app=document.querySelector<HTMLDivElement>('#app')!;
app.innerHTML=`<div class="stage" id="stage"></div><div class="hud"><div class="card"><input class="file" id="file" type="file" accept=".vrm,model/gltf-binary"><div class="status" id="status">Load a VRM model</div><div class="controls" id="controls"></div><button id="interrupt" type="button">Interrupt</button><div class="hint">Idle blink / gaze / head / breathing run automatically.</div></div><div class="badge" id="fps">-- FPS</div></div>`;
const stage=document.querySelector<HTMLElement>('#stage')!, status=document.querySelector<HTMLElement>('#status')!, controlsEl=document.querySelector<HTMLElement>('#controls')!;
const renderer=new AvatarRenderer(stage); const behavior=new BehaviorEngine(42); const simulator=new LocalAvatarSimulator(); const transport=new LocalTransport(); const stream=new AvatarStreamController(80); stream.connect(transport); let adapter:VrmAdapter|null=null; let last=performance.now(); const perf=new PerfMonitor(120); let lastHud=0;
const controls:SimulatorControls={jawOpen:0,smile:.12,headYaw:0,headPitch:0,gazeX:0,gazeY:0};
const sliders:[keyof SimulatorControls,string,number,number][]=[['jawOpen','Mouth',0,1],['smile','Smile',0,1],['headYaw','Head Y',-.7,.7],['headPitch','Head X',-.5,.5],['gazeX','Gaze X',-1,1],['gazeY','Gaze Y',-1,1]];
for(const [key,label,min,max] of sliders){const l=document.createElement('label');l.textContent=label;const i=document.createElement('input');i.type='range';i.min=String(min);i.max=String(max);i.step='.01';i.value=String(controls[key]);i.oninput=()=>controls[key]=Number(i.value);controlsEl.append(l,i);}
async function load(url:string){status.textContent='Loading…';try{adapter=new VrmAdapter(await renderer.load(url));status.textContent=`Live · ${Object.keys(adapter.capabilities()).length} face channels`; }catch(e){status.textContent=`Load failed: ${e instanceof Error?e.message:String(e)}`;}}
document.querySelector<HTMLButtonElement>('#interrupt')!.onclick=()=>transport.emitCommand({type:'interrupt'});
document.querySelector<HTMLInputElement>('#file')!.onchange=e=>{const f=(e.currentTarget as HTMLInputElement).files?.[0];if(f)void load(URL.createObjectURL(f));};
const model=new URLSearchParams(location.search).get('model'); if(model)void load(model); else void load('/models/avatar.vrm');
function loop(now:number){const dt=Math.min(.05,(now-last)/1000);last=now;const b=behavior.tick(now,dt*1000);const frame=simulator.next(now,controls,b);transport.emitFrame(frame);const presented=stream.sample(frame.audioPtsMs+80);if(presented)adapter?.apply(presented);renderer.render(dt);perf.push(dt*1000,presented?presented.audioPtsMs-frame.audioPtsMs:0);if(now-lastHud>500){const p=perf.snapshot();document.querySelector<HTMLElement>('#fps')!.textContent=`${p.fps.toFixed(0)} FPS · ${p.maxAbsDriftMs.toFixed(0)} ms`;lastHud=now;}requestAnimationFrame(loop);}requestAnimationFrame(loop);
