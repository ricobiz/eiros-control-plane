import './style.css';
import type { AvatarFrame } from './avatar-frame';
import { BehaviorEngine } from './behavior-engine';
import { resolveAvatarClientMode } from './client-mode';
import { LamExpressionAdapter, type LamChatState } from './lam-expression-adapter';
import { LamRenderer } from './lam-renderer';
import { PerfMonitor } from './perf-monitor';
import { LocalAvatarSimulator, interruptSimulatorControls, type SimulatorControls } from './simulator';
import { AvatarStreamController, LocalTransport } from './transport';

interface ActiveBackend {
  apply(frame: AvatarFrame): void;
  render(dtSeconds: number): void;
  interrupt(): void;
  dispose(): void;
}

const mode=resolveAvatarClientMode(location.search);
const app=document.querySelector<HTMLDivElement>('#app')!;
app.innerHTML=`<div class="stage" id="stage"></div><div class="hud"><div class="card"><div class="mode">${mode.renderer.toUpperCase()} renderer</div><input class="file" id="file" type="file" accept=".vrm,model/gltf-binary"><div class="status" id="status">Starting…</div><div class="controls" id="controls"></div><div class="states" id="states"></div><button id="interrupt" type="button">Interrupt</button><div class="hint">Idle blink / gaze / head / breathing run automatically. LAM uses the same canonical AvatarFrame as VRM.</div></div><div class="badge" id="fps">-- FPS</div></div>`;
const stage=document.querySelector<HTMLElement>('#stage')!;
const status=document.querySelector<HTMLElement>('#status')!;
const controlsEl=document.querySelector<HTMLElement>('#controls')!;
const statesEl=document.querySelector<HTMLElement>('#states')!;
const fileInput=document.querySelector<HTMLInputElement>('#file')!;
const fpsEl=document.querySelector<HTMLElement>('#fps')!;
const interruptButton=document.querySelector<HTMLButtonElement>('#interrupt')!;

const behavior=new BehaviorEngine(42);
const simulator=new LocalAvatarSimulator();
const transport=new LocalTransport();
const stream=new AvatarStreamController(80);
const perf=new PerfMonitor(120);
stream.connect(transport);
let backend:ActiveBackend|null=null;
let last=performance.now();
let lastHud=0;
const controls:SimulatorControls={jawOpen:0,smile:.12,headYaw:0,headPitch:0,gazeX:0,gazeY:0};
const sliders:[keyof SimulatorControls,string,number,number][]=[['jawOpen','Mouth',0,1],['smile','Smile',0,1],['headYaw','Head Y',-.7,.7],['headPitch','Head X',-.5,.5],['gazeX','Gaze X',-1,1],['gazeY','Gaze Y',-1,1]];
const sliderInputs=new Map<keyof SimulatorControls,HTMLInputElement>();
for(const [key,label,min,max] of sliders){
  const l=document.createElement('label');l.textContent=label;
  const i=document.createElement('input');i.type='range';i.min=String(min);i.max=String(max);i.step='.01';i.value=String(controls[key]);
  i.oninput=()=>controls[key]=Number(i.value);
  sliderInputs.set(key,i);controlsEl.append(l,i);
}

function setReady(text:string):void {
  status.textContent=text;
  status.dataset.ready='1';
  status.dataset.renderer=mode.renderer;
}
function setError(error:unknown):void {
  status.textContent=`Load failed: ${error instanceof Error?error.message:String(error)}`;
  status.dataset.error='1';
}

async function startVrm():Promise<ActiveBackend> {
  const [{ AvatarRenderer },{ VrmAdapter }]=await Promise.all([import('./renderer'),import('./vrm-adapter')]);
  const renderer=new AvatarRenderer(stage);
  let adapter:InstanceType<typeof VrmAdapter>|null=null;
  const load=async(url:string)=>{status.textContent='Loading VRM…';adapter=new VrmAdapter(await renderer.load(url));setReady(`VRM Live · ${Object.keys(adapter.capabilities()).length} face channels`);};
  fileInput.hidden=false;
  fileInput.onchange=e=>{const f=(e.currentTarget as HTMLInputElement).files?.[0];if(f)void load(URL.createObjectURL(f)).catch(setError);};
  await load(mode.model);
  return {apply(frame){adapter?.apply(frame);},render(dt){renderer.render(dt);},interrupt(){},dispose(){}};
}

async function startLam():Promise<ActiveBackend> {
  fileInput.hidden=true;
  statesEl.hidden=false;
  const adapter=new LamExpressionAdapter();
  adapter.setChatState('Idle');
  const renderer=new LamRenderer(stage,adapter);
  for(const state of ['Idle','Listening','Thinking','Responding'] as LamChatState[]){
    const button=document.createElement('button');button.type='button';button.textContent=state;
    button.onclick=()=>{adapter.setChatState(state);statesEl.dataset.state=state;};
    statesEl.appendChild(button);
  }
  statesEl.dataset.state='Idle';
  status.textContent='Loading LAM…';
  await renderer.start(mode.model,(phase,value)=>{
    const percent=Math.round(value*100);
    status.textContent=`Loading LAM · ${phase} ${percent}%`;
    if(phase==='load' && value>=.999)setReady('LAM Live · ARKit face + state animation');
  });
  return {apply(frame){adapter.apply(frame);},render(){},interrupt(){adapter.interrupt();statesEl.dataset.state='Listening';},dispose(){renderer.dispose();}};
}

interruptButton.onclick=()=>{
  transport.emitCommand({type:'interrupt'});
  interruptSimulatorControls(controls);
  const mouth=sliderInputs.get('jawOpen');if(mouth)mouth.value='0';
  backend?.interrupt();
};

async function boot():Promise<void>{
  try{backend=mode.renderer==='lam'?await startLam():await startVrm();}
  catch(error){setError(error);}
}
void boot();

function loop(now:number){
  const dt=Math.min(.05,(now-last)/1000);last=now;
  const b=behavior.tick(now,dt*1000);
  const frame=simulator.next(now,controls,b);
  transport.emitFrame(frame);
  const presented=stream.sample(frame.audioPtsMs+80);
  if(presented)backend?.apply(presented);
  backend?.render(dt);
  perf.push(dt*1000,presented?presented.audioPtsMs-frame.audioPtsMs:0);
  if(now-lastHud>500){const p=perf.snapshot();fpsEl.textContent=`${p.fps.toFixed(0)} FPS · ${p.maxAbsDriftMs.toFixed(0)} ms`;fpsEl.dataset.fps=p.fps.toFixed(1);lastHud=now;}
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
window.addEventListener('beforeunload',()=>backend?.dispose(),{once:true});
