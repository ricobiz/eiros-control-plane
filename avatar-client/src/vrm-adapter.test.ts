import { describe, expect, it } from 'vitest';
import { VrmAdapter, type VrmRigFacade } from './vrm-adapter';
import type { AvatarFrame } from './avatar-frame';
class Rig implements VrmRigFacade {
 values:Record<string,number>={}; head:[number,number,number,number]|null=null; gaze:[number,number]|null=null; breath=0;
 constructor(private names:string[]){} expressionNames(){return this.names;} setExpression(n:string,v:number){this.values[n]=v;} setHeadQuaternion(q:[number,number,number,number]){this.head=q;} setGaze(x:number,y:number){this.gaze=[x,y];} setBreath(v:number){this.breath=v;}
}
const frame:AvatarFrame={sessionId:'s',characterId:'c',sequence:1,audioPtsMs:0,framePtsMs:0,face:{jawOpen:.7,eyeBlinkLeft:.8,unknown:.5},head:{quat:[0,0,0,1]},gaze:{x:.2,y:-.1},body:{breath:.6,lean:0}};
describe('VrmAdapter',()=>{
 it('maps aliases and skips unsupported expressions safely',()=>{const rig=new Rig(['aa','blinkLeft']); const a=new VrmAdapter(rig); expect(()=>a.apply(frame)).not.toThrow(); expect(rig.values.aa).toBeCloseTo(.7); expect(rig.values.blinkLeft).toBeCloseTo(.8); expect(rig.values.unknown).toBeUndefined(); expect(rig.head).toEqual([0,0,0,1]); expect(rig.gaze).toEqual([.2,-.1]); expect(rig.breath).toBeCloseTo(.6);});
 it('reports mapped capabilities',()=>{const a=new VrmAdapter(new Rig(['happy','aa'])); expect(a.capabilities()).toMatchObject({jawOpen:'aa',mouthSmileLeft:'happy'});});
});
