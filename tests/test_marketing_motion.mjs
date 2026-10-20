import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../static/marketing-motion.js',import.meta.url),'utf8');
const {setupMotion}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('reduced motion leaves content visible without installing animations',()=>{let enhanced=false;globalThis.window={IntersectionObserver:class{}};globalThis.matchMedia=()=>({matches:true});globalThis.document={documentElement:{classList:{add(){enhanced=true;}}}};setupMotion();assert.equal(enhanced,false);});
test('missing IntersectionObserver leaves the unenhanced page readable',()=>{globalThis.window={};globalThis.matchMedia=()=>({matches:false});globalThis.document={documentElement:{classList:{add(){throw Error('Content must stay unhidden');}}}};assert.doesNotThrow(()=>setupMotion());});
