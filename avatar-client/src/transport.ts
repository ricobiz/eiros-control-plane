import type { AvatarFrame } from './avatar-frame';
import { TimelineBuffer } from './timeline-buffer';
export type AvatarCommand={type:'interrupt'}|{type:'reset'};
type Unsubscribe=()=>void;
export interface AvatarTransport {
 onFrame(listener:(frame:AvatarFrame)=>void):Unsubscribe;
 onCommand(listener:(command:AvatarCommand)=>void):Unsubscribe;
}
export class LocalTransport implements AvatarTransport {
 private frameListeners=new Set<(frame:AvatarFrame)=>void>(); private commandListeners=new Set<(command:AvatarCommand)=>void>();
 onFrame(listener:(frame:AvatarFrame)=>void){this.frameListeners.add(listener);return()=>this.frameListeners.delete(listener);}
 onCommand(listener:(command:AvatarCommand)=>void){this.commandListeners.add(listener);return()=>this.commandListeners.delete(listener);}
 emitFrame(frame:AvatarFrame){for(const listener of this.frameListeners)listener(frame);}
 emitCommand(command:AvatarCommand){for(const listener of this.commandListeners)listener(command);}
}
export class AvatarStreamController {
 private timeline:TimelineBuffer; private disconnectors:Unsubscribe[]=[]; private _hasSpeech=false;
 constructor(delayMs=80){this.timeline=new TimelineBuffer(delayMs);}
 get hasSpeech(){return this._hasSpeech;}
 connect(transport:AvatarTransport){this.disconnect();this.disconnectors=[transport.onFrame(frame=>{if(this.timeline.push(frame)){this._hasSpeech=Object.values(frame.face).some((v)=>v>0.001);}}),transport.onCommand(command=>this.handleCommand(command))];}
 disconnect(){for(const off of this.disconnectors)off();this.disconnectors=[];}
 handleCommand(command:AvatarCommand){if(command.type==='interrupt'||command.type==='reset'){this.timeline.clear();this._hasSpeech=false;}}
 sample(audioPtsMs:number){return this.timeline.sample(audioPtsMs);}
}
