import { describe, expect, it } from 'vitest';
import { createVrmRigFacade, type VrmLike } from './renderer';
describe('createVrmRigFacade',()=>{
 it('bridges expressions, head, gaze and breath to a VRM-like object',()=>{const values:Record<string,number>={}; const head={quaternion:{set:(x:number,y:number,z:number,w:number)=>{values.q=x+y+z+w;}}}; const chest={scale:{y:1}}; let looked=false; const vrm:VrmLike={expressionManager:{expressionMap:{aa:{},happy:{}},setValue:(n,v)=>{values[n]=v;}},humanoid:{getNormalizedBoneNode:(n)=>n==='head'?head:n==='upperChest'?chest:null},lookAt:{lookAt:()=>{looked=true;}}}; const rig=createVrmRigFacade(vrm); expect(rig.expressionNames()).toEqual(expect.arrayContaining(['aa','happy'])); rig.setExpression('aa',.7); rig.setHeadQuaternion([0,0,0,1]); rig.setGaze(.2,.1); rig.setBreath(.8); expect(values.aa).toBeCloseTo(.7); expect(values.q).toBe(1); expect(looked).toBe(true); expect(chest.scale.y).toBeGreaterThan(1);});
});
