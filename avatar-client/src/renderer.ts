import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, type VRM } from '@pixiv/three-vrm';
import type { VrmRigFacade } from './vrm-adapter';

type QuaternionLike={set(x:number,y:number,z:number,w:number):unknown};
type ScaleLike={y:number};
type BoneLike={quaternion?:QuaternionLike;scale?:ScaleLike};
export type VrmLike={
 expressionManager?:{expressionMap:Record<string,unknown>;setValue(name:string,value:number):void};
 humanoid?:{getNormalizedBoneNode(name:string):BoneLike|null};
 lookAt?:{lookAt(position:THREE.Vector3):void};
};
export function createVrmRigFacade(vrm:VrmLike):VrmRigFacade {
 const chest=vrm.humanoid?.getNormalizedBoneNode('upperChest')??vrm.humanoid?.getNormalizedBoneNode('chest'); const baseChestY=chest?.scale?.y??1;
 return {
  expressionNames:()=>Object.keys(vrm.expressionManager?.expressionMap??{}),
  setExpression:(name,value)=>vrm.expressionManager?.setValue(name,value),
  setHeadQuaternion:(q)=>vrm.humanoid?.getNormalizedBoneNode('head')?.quaternion?.set(...q),
  setGaze:(x,y)=>vrm.lookAt?.lookAt(new THREE.Vector3(x*1.2,1.45+y*.8,2.4)),
  setBreath:(value)=>{if(chest?.scale)chest.scale.y=baseChestY*(1+value*.006);},
 };
}
export class AvatarRenderer {
 readonly canvas=document.createElement('canvas'); private renderer:THREE.WebGLRenderer; private scene=new THREE.Scene(); private camera=new THREE.PerspectiveCamera(28,1,.1,100); private vrm:VRM|null=null;
 constructor(private host:HTMLElement){this.renderer=new THREE.WebGLRenderer({canvas:this.canvas,antialias:true,alpha:false,powerPreference:'high-performance'});this.renderer.setPixelRatio(Math.min(devicePixelRatio,2));this.renderer.outputColorSpace=THREE.SRGBColorSpace;this.scene.background=new THREE.Color(0x151515);this.camera.position.set(0,1.45,3.3);this.host.appendChild(this.canvas);this.scene.add(new THREE.HemisphereLight(0xffffff,0x222233,2.2));const key=new THREE.DirectionalLight(0xffffff,3.5);key.position.set(1.5,2.5,2);this.scene.add(key);this.resize();window.addEventListener('resize',()=>this.resize());}
 async load(url:string):Promise<VrmRigFacade>{if(this.vrm)this.scene.remove(this.vrm.scene);const loader=new GLTFLoader();loader.register(parser=>new VRMLoaderPlugin(parser));const gltf=await loader.loadAsync(url);const vrm=gltf.userData.vrm as VRM;if(!vrm)throw new Error('File is not a VRM avatar');VRMUtils.removeUnnecessaryVertices(gltf.scene);VRMUtils.combineSkeletons(gltf.scene);VRMUtils.combineMorphs(vrm);vrm.scene.traverse(o=>o.frustumCulled=false);this.scene.add(vrm.scene);this.vrm=vrm;const box=new THREE.Box3().setFromObject(vrm.scene);const center=box.getCenter(new THREE.Vector3());const size=box.getSize(new THREE.Vector3());this.camera.position.set(center.x,center.y+size.y*.05,Math.max(2.4,size.y*1.45));this.camera.lookAt(center.x,center.y+size.y*.08,center.z);return createVrmRigFacade(vrm);}
 render(deltaSeconds:number){this.vrm?.update(deltaSeconds);this.renderer.render(this.scene,this.camera);}
 private resize(){const w=Math.max(1,this.host.clientWidth),h=Math.max(1,this.host.clientHeight);this.renderer.setSize(w,h,false);this.camera.aspect=w/h;this.camera.updateProjectionMatrix();}
}
