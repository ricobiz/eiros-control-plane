import { Euler, Quaternion } from 'three';
import type { AvatarFrame } from './avatar-frame';
import type { BehaviorSample } from './behavior-engine';
import { mixFace } from './facial-mixer';
export type SimulatorControls={jawOpen:number;smile:number;headYaw:number;headPitch:number;gazeX:number;gazeY:number};
export class LocalAvatarSimulator {
 private sequence=0; private origin:number|null=null;
 constructor(private sessionId='local',private characterId='avatar'){}
 next(nowMs:number,c:SimulatorControls,b:BehaviorSample):AvatarFrame {
  if(this.origin===null)this.origin=nowMs; const pts=nowMs-this.origin; const q=new Quaternion().setFromEuler(new Euler(c.headPitch+b.headEuler[0],c.headYaw+b.headEuler[1],b.headEuler[2],'YXZ'));
  return {sessionId:this.sessionId,characterId:this.characterId,sequence:++this.sequence,audioPtsMs:pts,framePtsMs:pts,face:mixFace({jawOpen:c.jawOpen},b.face,{mouthSmileLeft:c.smile,mouthSmileRight:c.smile}),head:{quat:[q.x,q.y,q.z,q.w]},gaze:{x:Math.max(-1,Math.min(1,c.gazeX+b.gaze.x)),y:Math.max(-1,Math.min(1,c.gazeY+b.gaze.y))},body:b.body};
 }
}

export function interruptSimulatorControls(controls:SimulatorControls):void {
  controls.jawOpen=0;
}
