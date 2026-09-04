import { describe, expect, it } from 'vitest';
import { mixFace } from './facial-mixer';
describe('mixFace',()=>{
 it('gives speech ownership of mouth and behavior ownership of blink',()=>{const m=mixFace({jawOpen:.7,mouthFunnel:.4,eyeBlinkLeft:.9},{jawOpen:.9,eyeBlinkLeft:.8},{jawOpen:.8,mouthSmileLeft:.5}); expect(m.jawOpen).toBeCloseTo(.9); expect(m.mouthFunnel).toBeCloseTo(.4); expect(m.eyeBlinkLeft).toBeCloseTo(.8); expect(m.mouthSmileLeft).toBeCloseTo(.5);});
 it('clamps additive expression channels',()=>{expect(mixFace({}, {browInnerUp:.8},{browInnerUp:.7}).browInnerUp).toBe(1);});
});
