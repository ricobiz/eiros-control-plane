import { describe, expect, it } from 'vitest';
import { BehaviorEngine } from './behavior-engine';
describe('BehaviorEngine',()=>{
 it('keeps idle motion bounded and deterministic',()=>{const a=new BehaviorEngine(7), b=new BehaviorEngine(7); const x=a.tick(5000,16), y=b.tick(5000,16); expect(x).toEqual(y); expect(Math.abs(x.gaze.x)).toBeLessThanOrEqual(.15); expect(Math.abs(x.gaze.y)).toBeLessThanOrEqual(.12); expect(x.body.breath).toBeGreaterThanOrEqual(0); expect(x.body.breath).toBeLessThanOrEqual(1);});
 it('produces a complete blink lifecycle',()=>{const e=new BehaviorEngine(1); let peak=0; for(let t=0;t<8000;t+=20) peak=Math.max(peak,e.tick(t,20).face.eyeBlinkLeft??0); expect(peak).toBeGreaterThan(.9); expect(e.tick(9000,20).face.eyeBlinkLeft??0).toBeLessThanOrEqual(1);});
});
