import { describe, expect, it } from 'vitest';
import { LamExpressionAdapter } from './lam-expression-adapter';
import type { AvatarFrame } from './avatar-frame';
const frame=(face:Record<string,number>):AvatarFrame=>({sessionId:'s',characterId:'c',sequence:1,audioPtsMs:0,framePtsMs:0,face,head:{quat:[0,0,0,1]},gaze:{x:0,y:0},body:{breath:.5,lean:0}});
describe('LamExpressionAdapter',()=>{
  it('maps canonical channels to LAM ARKit names',()=>{const a=new LamExpressionAdapter();a.apply(frame({jawOpen:.8,eyeBlinkLeft:.3,eyeBlinkRight:.4,mouthSmileLeft:.2,mouthSmileRight:.25}));expect(a.getExpressionData()).toMatchObject({jawOpen:.8,eyeBlinkLeft:.3,eyeBlinkRight:.4,mouthSmileLeft:.2,mouthSmileRight:.25});});
  it('interrupt zeros speech mouth but preserves reflex eyes and switches to Listening',()=>{const a=new LamExpressionAdapter();a.apply(frame({jawOpen:.9,mouthFunnel:.5,eyeBlinkLeft:.6,eyeBlinkRight:.6}));a.setChatState('Responding');a.interrupt();expect(a.getExpressionData().jawOpen).toBe(0);expect(a.getExpressionData().mouthFunnel).toBe(0);expect(a.getExpressionData().eyeBlinkLeft).toBe(.6);expect(a.getChatState()).toBe('Listening');});
  it('passes through valid ARKit weights and clamps values',()=>{const a=new LamExpressionAdapter();a.apply(frame({browInnerUp:2,noseSneerLeft:-1,unknownThing:.7}));const data=a.getExpressionData();expect(data.browInnerUp).toBe(1);expect(data.noseSneerLeft).toBe(0);expect(data).not.toHaveProperty('unknownThing');});
});
