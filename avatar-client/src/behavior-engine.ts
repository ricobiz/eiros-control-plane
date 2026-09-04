import type { BodyState, FaceState, GazeState } from './avatar-frame';
export type BehaviorSample={face:FaceState;gaze:GazeState;headEuler:[number,number,number];body:BodyState};
class Rng { constructor(private s:number){} next(){this.s=(this.s*1664525+1013904223)>>>0; return this.s/4294967296;} }
export class BehaviorEngine {
 private rng:Rng; private nextBlinkAt:number; private blinkStart:number|null=null;
 constructor(seed=1){this.rng=new Rng(seed>>>0);this.nextBlinkAt=1800+this.rng.next()*2200;}
 tick(nowMs:number,_dtMs:number):BehaviorSample {
   if(this.blinkStart===null && nowMs>=this.nextBlinkAt)this.blinkStart=nowMs;
   let blink=0;
   if(this.blinkStart!==null){const p=(nowMs-this.blinkStart)/160;if(p>=1){this.blinkStart=null;this.nextBlinkAt=nowMs+2200+this.rng.next()*2600;}else blink=p<.5?p*2:(1-p)*2;}
   const breath=.5+.5*Math.sin(nowMs/1650);
   return {face:{eyeBlinkLeft:blink,eyeBlinkRight:blink},gaze:{x:.12*Math.sin(nowMs/2300),y:.08*Math.sin(nowMs/3100+.7)},headEuler:[.035*Math.sin(nowMs/2800)+.012*Math.sin(nowMs/900),.055*Math.sin(nowMs/3600+.4)+.015*Math.sin(nowMs/1100+.9),.024*Math.sin(nowMs/4100)],body:{breath,lean:.07*Math.sin(nowMs/5000)+.02*Math.sin(nowMs/1700+.3)}};
 }
}
