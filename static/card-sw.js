// Public recipient shell only. Never cache API responses, credentials, leads or app routes.
const CACHE='huddle-recipient-v1';const ASSETS=['/static/card.css','/static/public-card.css','/static/public-card.js','/static/card-renderer.js','/static/huddle-icon-192.png','/static/huddle-icon-512.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('huddle-recipient-')&&k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',event=>{const url=new URL(event.request.url);if(event.request.method!=='GET'||url.origin!==self.location.origin||!ASSETS.includes(url.pathname))return;event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)));});
