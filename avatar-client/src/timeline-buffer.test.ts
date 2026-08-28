import { describe, expect, it } from 'vitest';
import type { AvatarFrame } from './avatar-frame';
import { TimelineBuffer } from './timeline-buffer';

const f = (sequence:number, pts:number, jawOpen:number, quat:[number,number,number,number]=[0,0,0,1]):AvatarFrame => ({
  sessionId:'s', characterId:'c', sequence, audioPtsMs:pts, framePtsMs:pts,
  face:{jawOpen}, head:{quat}, gaze:{x:jawOpen,y:-jawOpen}, body:{breath:jawOpen,lean:jawOpen},
});

describe('TimelineBuffer', () => {
  it('rejects stale sequence numbers', () => {
    const b = new TimelineBuffer(80, 4);
    expect(b.push(f(2,100,1))).toBe(true);
    expect(b.push(f(1,110,0))).toBe(false);
    expect(b.size).toBe(1);
  });
  it('keeps only the configured number of frames', () => {
    const b = new TimelineBuffer(80, 2);
    b.push(f(1,0,0)); b.push(f(2,50,.5)); b.push(f(3,100,1));
    expect(b.size).toBe(2);
  });
  it('samples behind audio time and interpolates state', () => {
    const b = new TimelineBuffer(80, 4);
    b.push(f(1,0,0)); b.push(f(2,100,1));
    const v = b.sample(130)!; // target=50ms
    expect(v.face.jawOpen).toBeCloseTo(.5);
    expect(v.gaze.x).toBeCloseTo(.5);
    expect(v.body.breath).toBeCloseTo(.5);
    expect(Math.hypot(...v.head.quat)).toBeCloseTo(1);
  });
  it('clears queued frames', () => {
    const b = new TimelineBuffer(); b.push(f(1,0,0)); b.clear();
    expect(b.size).toBe(0); expect(b.sample(100)).toBeUndefined();
  });
});
