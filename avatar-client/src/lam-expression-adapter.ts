import type { AvatarFrame } from './avatar-frame';
export type LamChatState='Idle'|'Listening'|'Thinking'|'Responding';
const ARKIT=new Set(['browDownLeft','browDownRight','browInnerUp','browOuterUpLeft','browOuterUpRight','cheekPuff','cheekSquintLeft','cheekSquintRight','eyeBlinkLeft','eyeBlinkRight','eyeLookDownLeft','eyeLookDownRight','eyeLookInLeft','eyeLookInRight','eyeLookOutLeft','eyeLookOutRight','eyeLookUpLeft','eyeLookUpRight','eyeSquintLeft','eyeSquintRight','eyeWideLeft','eyeWideRight','jawForward','jawLeft','jawOpen','jawRight','mouthClose','mouthDimpleLeft','mouthDimpleRight','mouthFrownLeft','mouthFrownRight','mouthFunnel','mouthLeft','mouthLowerDownLeft','mouthLowerDownRight','mouthPressLeft','mouthPressRight','mouthPucker','mouthRight','mouthRollLower','mouthRollUpper','mouthShrugLower','mouthShrugUpper','mouthSmileLeft','mouthSmileRight','mouthStretchLeft','mouthStretchRight','mouthUpperUpLeft','mouthUpperUpRight','noseSneerLeft','noseSneerRight','tongueOut']);
const SPEECH_MOUTH=new Set(['jawForward','jawLeft','jawOpen','jawRight','mouthClose','mouthFunnel','mouthLeft','mouthLowerDownLeft','mouthLowerDownRight','mouthPucker','mouthRight','mouthRollLower','mouthRollUpper','mouthShrugLower','mouthShrugUpper','mouthStretchLeft','mouthStretchRight','mouthUpperUpLeft','mouthUpperUpRight','tongueOut']);
const clamp=(v:number)=>Math.max(0,Math.min(1,Number.isFinite(v)?v:0));
export class LamExpressionAdapter {
  private weights:Record<string,number>={}; private state:LamChatState='Idle';
  apply(frame:AvatarFrame){
    for(const [name,value] of Object.entries(frame.face))if(ARKIT.has(name))this.weights[name]=clamp(value);
    const x=Math.max(-1,Math.min(1,frame.gaze.x));
    const y=Math.max(-1,Math.min(1,frame.gaze.y));
    Object.assign(this.weights,{eyeLookInLeft:0,eyeLookOutLeft:0,eyeLookInRight:0,eyeLookOutRight:0,eyeLookUpLeft:0,eyeLookUpRight:0,eyeLookDownLeft:0,eyeLookDownRight:0});
    if(x>=0){this.weights.eyeLookInLeft=x;this.weights.eyeLookOutRight=x;}else{this.weights.eyeLookOutLeft=-x;this.weights.eyeLookInRight=-x;}
    if(y>=0){this.weights.eyeLookUpLeft=y;this.weights.eyeLookUpRight=y;}else{this.weights.eyeLookDownLeft=-y;this.weights.eyeLookDownRight=-y;}
  }
  getExpressionData(){return {...this.weights};}
  setChatState(state:LamChatState){this.state=state;}
  getChatState(){return this.state;}
  interrupt(){for(const name of SPEECH_MOUTH)this.weights[name]=0;this.state='Listening';}
}
