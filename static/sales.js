import {supportPlaybook} from '/static/support-playbook.js';
import {initSalesUI,salesList,salesDetail,salesTeam,staffPassword} from '/static/sales-ui.js';
const root=document.querySelector('#sales-root'),message=document.querySelector('#operator-message');let access,sequence=0;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notify(text){message.textContent=text;clearTimeout(notify.timer);notify.timer=setTimeout(()=>message.textContent='',7000);}
function navigate(url){history.pushState({},'',url);render();}
function scrollToPlaybookSection(){
 if(location.pathname!=='/sales/playbook'||!location.hash)return;
 const section=document.getElementById(decodeURIComponent(location.hash.slice(1)));
 section?.scrollIntoView({block:'start'});
}
async function render(){const token=++sequence;try{const r=await fetch('/api/sales/access');access=await r.json();if(!r.ok)throw Error('Sign in with an authorized sales account.');const id=location.pathname.split('/')[2];const body=access.must_change||id==='password'?staffPassword(access):id==='playbook'?supportPlaybook():id==='team'&&access.manager?await salesTeam('/sales'):id?await salesDetail('/sales',id,access.manager):await salesList('/sales',access.manager);if(token!==sequence)return;document.title=(id==='playbook'?'Team playbook':'Sales & support')+' · HUDDLE';root.innerHTML=`<div class="op-shell"><aside class="op-sidebar"><a class="wordmark" href="/"><span class="huddle-symbol">h*</span><span class="huddle-name">huddle.</span></a><div class="op-scope"><strong>Sales &amp; support</strong><small>Assigned enquiries only</small></div><nav class="op-nav"><a href="/sales" data-sales-link ${!id?'aria-current="page"':''}>Sales enquiries</a><a href="/sales/playbook" data-sales-link ${id==='playbook'?'aria-current="page"':''}>Team playbook</a>${access.auth_kind!=='staff'?'<a href="/app/dashboard">My workspace ↗</a>':''}${access.manager?'<a href="/super-admin/enquiries">Super Admin sales ↗</a>':''}</nav></aside><div class="op-workspace"><header class="op-topbar"><strong>HUDDLE · Sales &amp; support</strong><div class="sales-profile-actions">${access.auth_kind==='staff'?`<details class="sales-profile"><summary aria-label="Account menu"><span class="sales-profile-avatar" aria-hidden="true">${esc((access.name||access.email).slice(0,1).toUpperCase())}</span><span class="sales-profile-name">${esc(access.name||access.email)}</span></summary><div class="sales-profile-menu"><strong>${esc(access.name||access.email)}</strong><small>${esc(access.email)}</small><a href="/sales/password" data-sales-link>Change password</a><button type="button" id="staff-signout">Sign out</button></div></details>`:`<span>${esc(access.name||access.email)}</span>`}</div></header><main class="op-main" tabindex="-1">${body}</main></div></div>`;document.querySelector('main').focus({preventScroll:true});window.scrollTo(0,0);initSalesUI({base:'/sales',navigate,refresh:render,notify});requestAnimationFrame(scrollToPlaybookSection);}catch(e){root.innerHTML=`<main class="op-main"><h1>Sales workspace</h1><p>${esc(e.message)}</p><a class="btn" href="/sales/login">Sign in</a><a class="btn" href="/app/dashboard">My workspace</a></main>`;}}
window.addEventListener('popstate',render);render();

document.addEventListener('click',event=>{
 const link=event.target.closest('.playbook-nav a[href^="#"]');
 if(!link||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
 event.preventDefault();
 history.pushState({},'',link.href);
 scrollToPlaybookSection();
});

document.addEventListener('click',async e=>{if(e.target.closest('#staff-signout')){await fetch('/api/sales/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});location.href='/sales/login';}});

document.addEventListener('click',async event=>{const button=event.target.closest('[data-playbook-copy]');if(!button)return;const text=document.getElementById(button.dataset.playbookCopy)?.innerText||'';const status=button.nextElementSibling;try{await navigator.clipboard.writeText(text);status.textContent='Copied. Adapt before sending.';}catch{status.textContent='Select the starter text to copy it.';}});
