import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const renderer=await readFile(new URL('../static/card-renderer.js',import.meta.url),'utf8');
const {renderCard,escapeHTML,cardPath}=await import('data:text/javascript;base64,'+Buffer.from(renderer).toString('base64'));
const source=(await readFile(new URL('../static/public-card.js',import.meta.url),'utf8')).replace(/^import .*;$/m,'');
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
async function recipient(path){
 const requests=[],links=[],handlers={},root={innerHTML:''};
 const profile={profile:{name:'Mohanraaj G',email:'mohan@example.com'},company:{name:'HUDDLE'},template:{},slug:path,lead_capture:true};
 const document={querySelector:()=>root,createElement:()=>({}),head:{append:link=>links.push(link)},addEventListener:(kind,fn)=>handlers[kind]=fn};
 const fetch=async(url,options={})=>{requests.push({url,options});const ok=!/%2f/i.test(url);return {ok,json:async()=>ok?profile:{error:'This card is unavailable.'}};};
 class FormData extends Map{constructor(){super([['name','Visitor'],['email','visitor@example.com']]);}}
 await new AsyncFunction('document','location','navigator','fetch','setInterval','matchMedia','renderCard','e','cardPath','FormData',source)(document,{pathname:'/c/'+path,search:'',origin:'https://www.huddleapp.in'},{},fetch,()=>0,()=>({matches:false}),renderCard,escapeHTML,cardPath,FormData);
 return {requests,links,root,handlers};
}
test('namespaced recipient loads through an edge that rejects encoded slash separators',async()=>{
 const r=await recipient('huddle-op/mohanraajg');
 assert.equal(r.requests[0].url,'/api/card/huddle-op/mohanraajg');
 assert.match(r.root.innerHTML,/Mohanraaj G/);assert.doesNotMatch(r.root.innerHTML,/This card is unavailable/);
 assert.equal(r.links.find(x=>x.rel==='manifest').href,'/manifest/huddle-op/mohanraajg.webmanifest');
 assert.equal(r.links.find(x=>x.rel==='canonical').href,'https://www.huddleapp.in/c/huddle-op/mohanraajg');
});
test('contact exchange preserves the same tenant and card path',async()=>{
 const r=await recipient('huddle-op/mohanraajg');const button={disabled:false};
 const form={id:'exchange',elements:{consent:{checked:true}},querySelector:()=>button,innerHTML:''};
 await r.handlers.submit({target:form,preventDefault(){}});
 const request=r.requests.find(x=>x.url.startsWith('/api/exchange/'));
 assert.equal(request.url,'/api/exchange/huddle-op/mohanraajg');assert.equal(JSON.parse(request.options.body).consent,true);
 assert.match(form.innerHTML,/Your details have been shared/);
});
test('legacy short links still load and path segments encode data independently',async()=>{
 const r=await recipient('platform-owner-e0a04eda06');assert.equal(r.requests[0].url,'/api/card/platform-owner-e0a04eda06');
 assert.equal(cardPath('org/name?x=1'),'org/name%3Fx%3D1');
});
