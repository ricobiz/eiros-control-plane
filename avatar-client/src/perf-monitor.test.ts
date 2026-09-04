import { describe, expect, it } from 'vitest';
import { PerfMonitor } from './perf-monitor';
describe('PerfMonitor',()=>{
 it('computes rolling fps and frame time',()=>{const p=new PerfMonitor(4);[16,17,16,17].forEach(ms=>p.push(ms,10));const s=p.snapshot();expect(s.fps).toBeGreaterThan(59);expect(s.avgFrameMs).toBeCloseTo(16.5);expect(s.maxAbsDriftMs).toBe(10);expect(s.healthy).toBe(true);});
 it('flags slow fps or excessive sync drift',()=>{const p=new PerfMonitor(3);[40,40,40].forEach(ms=>p.push(ms,50));expect(p.snapshot().healthy).toBe(false);});
});
