import { clampAvatarFrame, type AvatarFrame } from './avatar-frame';

const lerp=(a:number,b:number,t:number)=>a+(b-a)*t;
const lerpMap=(a:Record<string,number>, b:Record<string,number>, t:number) => {
  const keys=new Set([...Object.keys(a),...Object.keys(b)]); const out:Record<string,number>={};
  for(const key of keys) out[key]=lerp(a[key]??0,b[key]??0,t);
  return out;
};
function nlerpQuat(a:[number,number,number,number], b:[number,number,number,number], t:number):[number,number,number,number] {
  const dot=a[0]*b[0]+a[1]*b[1]+a[2]*b[2]+a[3]*b[3]; const sign=dot<0?-1:1;
  const q:[number,number,number,number]=[lerp(a[0],b[0]*sign,t),lerp(a[1],b[1]*sign,t),lerp(a[2],b[2]*sign,t),lerp(a[3],b[3]*sign,t)];
  const n=Math.hypot(...q) || 1; return q.map(v=>v/n) as typeof q;
}
function interpolate(a:AvatarFrame,b:AvatarFrame,target:number):AvatarFrame {
  const span=b.audioPtsMs-a.audioPtsMs; const t=span<=0?1:Math.max(0,Math.min(1,(target-a.audioPtsMs)/span));
  return clampAvatarFrame({
    ...b, audioPtsMs:target, framePtsMs:lerp(a.framePtsMs,b.framePtsMs,t),
    face:lerpMap(a.face,b.face,t), head:{quat:nlerpQuat(a.head.quat,b.head.quat,t)},
    gaze:{x:lerp(a.gaze.x,b.gaze.x,t),y:lerp(a.gaze.y,b.gaze.y,t)},
    body:{breath:lerp(a.body.breath,b.body.breath,t),lean:lerp(a.body.lean,b.body.lean,t)},
  });
}
export class TimelineBuffer {
  private frames:AvatarFrame[]=[];
  constructor(private readonly presentationDelayMs=80, private readonly maxFrames=240) {}
  get size(){return this.frames.length;}
  push(frame:AvatarFrame):boolean {
    const last=this.frames.at(-1); if(last && frame.sequence<=last.sequence) return false;
    this.frames.push(clampAvatarFrame(frame)); while(this.frames.length>this.maxFrames)this.frames.shift(); return true;
  }
  clear(){this.frames=[];}
  sample(audioPtsMs:number):AvatarFrame|undefined {
    if(!this.frames.length)return undefined; const target=audioPtsMs-this.presentationDelayMs;
    if(target<=this.frames[0].audioPtsMs)return this.frames[0]; const last=this.frames.at(-1)!; if(target>=last.audioPtsMs)return last;
    for(let i=1;i<this.frames.length;i++) if(this.frames[i].audioPtsMs>=target)return interpolate(this.frames[i-1],this.frames[i],target);
    return last;
  }
}
