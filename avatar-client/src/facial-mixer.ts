import type { FaceState } from './avatar-frame';
const clamp01=(n:number)=>Math.max(0,Math.min(1,n));
const isSpeechArticulation=(k:string)=>k.startsWith('jaw')||['mouthFunnel','mouthPucker','mouthClose','mouthPressLeft','mouthPressRight'].includes(k);
const isBlink=(k:string)=>k.startsWith('eyeBlink');
export function mixFace(speech:FaceState,behavior:FaceState,emotion:FaceState):FaceState {
 const keys=new Set([...Object.keys(speech),...Object.keys(behavior),...Object.keys(emotion)]); const out:FaceState={};
 for(const key of keys){
   if(isBlink(key)) out[key]=clamp01(behavior[key]??0);
   else if(isSpeechArticulation(key)) out[key]=clamp01((speech[key]??0)+(emotion[key]??0)*.25);
   else out[key]=clamp01((speech[key]??0)+(behavior[key]??0)+(emotion[key]??0));
 }
 return out;
}
