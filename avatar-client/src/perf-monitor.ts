export type PerfSnapshot={fps:number;avgFrameMs:number;maxAbsDriftMs:number;healthy:boolean};
export class PerfMonitor {
 private samples:{frameMs:number;driftMs:number}[]=[];
 constructor(private readonly windowSize=120){}
 push(frameMs:number,driftMs=0){this.samples.push({frameMs,driftMs});while(this.samples.length>this.windowSize)this.samples.shift();}
 snapshot():PerfSnapshot {if(!this.samples.length)return{fps:0,avgFrameMs:0,maxAbsDriftMs:0,healthy:false};const avgFrameMs=this.samples.reduce((s,x)=>s+x.frameMs,0)/this.samples.length;const fps=1000/avgFrameMs;const maxAbsDriftMs=Math.max(...this.samples.map(x=>Math.abs(x.driftMs)));return{fps,avgFrameMs,maxAbsDriftMs,healthy:fps>=30&&maxAbsDriftMs<=40};}
}
