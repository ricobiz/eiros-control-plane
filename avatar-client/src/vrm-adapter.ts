import type { AvatarFrame } from './avatar-frame';
export interface VrmRigFacade {
 expressionNames():readonly string[];
 setExpression(name:string,value:number):void;
 setHeadQuaternion(q:[number,number,number,number]):void;
 setGaze(x:number,y:number):void;
 setBreath(value:number):void;
}
const aliases:Record<string,string[]>={
 jawOpen:['jawOpen','aa','A'], eyeBlinkLeft:['eyeBlinkLeft','blinkLeft','blink_l','blink'], eyeBlinkRight:['eyeBlinkRight','blinkRight','blink_r','blink'],
 mouthSmileLeft:['mouthSmileLeft','happy'], mouthSmileRight:['mouthSmileRight','happy'], browInnerUp:['browInnerUp','surprised'],
};
export class VrmAdapter {
 private map:Record<string,string>={};
 constructor(private readonly rig:VrmRigFacade){
  const available=new Set(rig.expressionNames());
  for(const [canonical,names] of Object.entries(aliases)){const hit=names.find(n=>available.has(n));if(hit)this.map[canonical]=hit;}
  for(const n of available)if(!(n in this.map))this.map[n]=n;
 }
 capabilities(){return {...this.map};}
 apply(frame:AvatarFrame){
  for(const [key,value] of Object.entries(frame.face)){const target=this.map[key];if(target)this.rig.setExpression(target,value);}
  this.rig.setHeadQuaternion(frame.head.quat); this.rig.setGaze(frame.gaze.x,frame.gaze.y); this.rig.setBreath(frame.body.breath);
 }
}
