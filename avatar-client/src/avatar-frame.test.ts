import { describe, expect, it } from 'vitest';
import { clampAvatarFrame, type AvatarFrame } from './avatar-frame';
const frame: AvatarFrame={sessionId:'s',characterId:'c',sequence:1,audioPtsMs:10,framePtsMs:10,face:{jawOpen:2,blinkLeft:-1},head:{quat:[0,0,0,0]},gaze:{x:2,y:-2},body:{breath:2,lean:2}};
describe('clampAvatarFrame',()=>{it('clamps channels and repairs zero quaternion',()=>{const v=clampAvatarFrame(frame);expect(v.face.jawOpen).toBe(1);expect(v.face.blinkLeft).toBe(0);expect(v.gaze).toEqual({x:1,y:-1});expect(v.body.breath).toBe(1);expect(v.head.quat).toEqual([0,0,0,1]);});});
