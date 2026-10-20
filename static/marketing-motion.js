// Progressive enhancement: content stays visible without JS or IntersectionObserver.
export function setupMotion(){
 if(!('IntersectionObserver' in window)||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
 document.documentElement.classList.add('motion-ready');
 const observer=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){entry.target.classList.add('is-revealed');observer.unobserve(entry.target);}},{threshold:.06,rootMargin:'0px 0px -24px 0px'});
 const selectors=['.hero-copy','.hero-visual','.hero-bottom','#main>.section:not(.pricing-page)','#main>.preview-bar','#main>.closing','.pricing-page>header','.pricing-plans-wrap','.plan-comparison','.plan-faq','.human-cta','.template-example','.feature-tile','.security-grid>div'];
 document.querySelectorAll(selectors.join(',')).forEach(el=>{el.dataset.reveal='';if(el.matches('.template-example,.feature-tile,.security-grid>div'))el.style.setProperty('--reveal-delay',`${Math.min([...el.parentElement.children].indexOf(el),2)*70}ms`);observer.observe(el);});
 const pref=matchMedia('(prefers-reduced-motion: reduce)');pref.addEventListener?.('change',e=>{if(e.matches){document.documentElement.classList.remove('motion-ready');observer.disconnect();}});
}
