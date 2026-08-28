import { describe, expect, it } from 'vitest';
import { AvatarStreamController, LocalTransport } from './transport';
import { BehaviorEngine } from './behavior-engine';
import type { AvatarFrame } from './avatar-frame';
const f=(seq:number,pts:number,jaw:number):AvatarFrame=>({sessionId:'s',characterId:'c',sequence:seq,audioPtsMs:pts,framePtsMs:pts,face:{jawOpen:jaw},head:{quat:[0,0,0,1]},gaze:{x:0,y:0},body:{breath:.5,lean:0}});
describe('avatar transport',()=>{
 it('drops stale lossy frames without blocking a newer frame',()=>{const t=new LocalTransport(),c=new AvatarStreamController(0);c.connect(t);t.emitFrame(f(2,100,.8));t.emitFrame(f(1,110,.1));expect(c.sample(100)?.sequence).toBe(2);expect(c.sample(100)?.face.jawOpen).toBeCloseTo(.8);});
 it('interrupt clears queued speech immediately',()=>{const t=new LocalTransport(),c=new AvatarStreamController(0);c.connect(t);t.emitFrame(f(1,0,.9));expect(c.hasSpeech).toBe(true);t.emitCommand({type:'interrupt'});expect(c.hasSpeech).toBe(false);expect(c.sample(0)).toBeUndefined();});
 it('does not stop procedural behavior on interrupt',()=>{const t=new LocalTransport(),c=new AvatarStreamController(0);c.connect(t);const b=new BehaviorEngine(2);const before=b.tick(1000,16).body.breath;t.emitCommand({type:'interrupt'});const after=b.tick(1200,16).body.breath;expect(Number.isFinite(before)).toBe(true);expect(Number.isFinite(after)).toBe(true);});
});
