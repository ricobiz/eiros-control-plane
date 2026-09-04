import { describe, expect, it } from 'vitest';
import { LocalAvatarSimulator, interruptSimulatorControls } from './simulator';
import type { BehaviorSample } from './behavior-engine';
const behavior:BehaviorSample={face:{eyeBlinkLeft:.4,eyeBlinkRight:.4},gaze:{x:.1,y:-.1},headEuler:[.01,.02,.03],body:{breath:.6,lean:.02}};
describe('LocalAvatarSimulator',()=>{
 it('produces monotonic canonical frames and mixes behavior',()=>{const s=new LocalAvatarSimulator('session','character'); const a=s.next(100,{jawOpen:.5,smile:.3,headYaw:0,headPitch:0,gazeX:0,gazeY:0},behavior); const b=s.next(116,{jawOpen:.2,smile:0,headYaw:.1,headPitch:.1,gazeX:.2,gazeY:.2},behavior); expect(b.sequence).toBe(a.sequence+1); expect(b.audioPtsMs).toBeGreaterThan(a.audioPtsMs); expect(a.face.jawOpen).toBeCloseTo(.5); expect(a.face.eyeBlinkLeft).toBeCloseTo(.4); expect(a.face.mouthSmileLeft).toBeCloseTo(.3); expect(Math.hypot(...b.head.quat)).toBeCloseTo(1);});
});

it('clears local speech controls on interrupt without touching expression/body controls',()=>{
  const c={jawOpen:.8,smile:.4,headYaw:.2,headPitch:-.1,gazeX:.3,gazeY:-.2};
  interruptSimulatorControls(c);
  expect(c).toEqual({jawOpen:0,smile:.4,headYaw:.2,headPitch:-.1,gazeX:.3,gazeY:-.2});
});
