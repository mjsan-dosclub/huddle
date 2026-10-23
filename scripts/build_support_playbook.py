"""Regenerate the staff playbook module from the reviewed support SOP. Run after content edits."""
from pathlib import Path
import html,json,re
root=Path(__file__).resolve().parents[1]
source=(root/'docs/SUPPORT-SOP.md').read_text()
def inline(s):
 s=html.escape(s)
 s=re.sub(r'`([^`]+)`',r'<code>\1</code>',s)
 s=re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',s)
 return s
lines=source.splitlines(); out=[]; i=0; n=0; opened=False; detail=False
nav=[]
while i<len(lines):
 s=lines[i].strip()
 if not s or s.startswith('Content maintenance:') or s.startswith('# ') or s.startswith('**HUDDLE') or s.startswith('A person has asked'):i+=1;continue
 if s.startswith('## '):
  if detail:out.append('</details>');detail=False
  if opened:out.append('</section>')
  title=s[3:]; slug=re.sub('[^a-z0-9]+','-',title.lower()).strip('-');nav.append((slug,title));opened=True
  out.append(f'<section class="playbook-section" id="{slug}"><h2>{inline(title)}</h2>');i+=1;continue
 if s.startswith('### '):
  if detail:out.append('</details>');detail=False
  if 'Small playbooks' in dict(nav).get(nav[-1][0],''):
   out.append('<details class="playbook-question"><summary>'+inline(s[4:])+'</summary>');detail=True
  else:out.append('<h3>'+inline(s[4:])+'</h3>')
  i+=1;continue
 if s.startswith('|'):
  rows=[]
  while i<len(lines) and lines[i].strip().startswith('|'):
   cells=[x.strip() for x in lines[i].strip().strip('|').split('|')]
   if not all(re.fullmatch(r'[-: ]+',x) for x in cells):rows.append(cells)
   i+=1
  out.append('<div class="playbook-table"><table><thead><tr>'+''.join('<th scope="col">'+inline(x)+'</th>' for x in rows[0])+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+inline(x)+'</td>' for x in row)+'</tr>' for row in rows[1:])+'</tbody></table></div>');continue
 if s.startswith('> '):
  parts=[]
  while i<len(lines) and lines[i].strip().startswith('> '):parts.append(inline(lines[i].strip()[2:]));i+=1
  n+=1;out.append(f'<div class="playbook-template"><blockquote id="reply-{n}">'+ '<br>'.join(parts)+f'</blockquote><button class="btn" type="button" data-playbook-copy="reply-{n}">Copy starter ↗</button><span role="status"></span></div>');continue
 if s.startswith('- ') or re.match(r'\d+\. ',s):
  ordered=not s.startswith('- '); tag='ol' if ordered else 'ul';items=[]
  while i<len(lines):
   item=lines[i].strip();match=re.match(r'\d+\. (.*)',item) if ordered else re.match(r'- (.*)',item)
   if not match:break
   items.append('<li>'+inline(match[1])+'</li>');i+=1
  out.append('<'+tag+'>'+''.join(items)+'</'+tag+'>');continue
 out.append('<p>'+inline(s)+'</p>');i+=1
if detail:out.append('</details>')
if opened:out.append('</section>')
navhtml=''.join('<a href="#'+slug+'">'+html.escape(title)+'</a>' for slug,title in nav)
page='<div class="sales-heading"><div><p class="op-kicker">HUDDLE · TEAM PLAYBOOK</p><h1>The next helpful reply.</h1><p>For product questions, enterprise conversations and NFC enquiries. Pick the situation you need.</p></div><a class="btn" href="/sales" data-sales-link>Open my enquiries ↗</a></div><div class="playbook-welcome"><strong>Read → acknowledge → help → record → confirm.</strong><p>Own the next useful step. Adapt the starters to the person and use your agreed communication channel. The workspace records activity; it does not send replies.</p></div><div class="playbook-layout"><nav class="playbook-nav" aria-label="Playbook sections">'+navhtml+'</nav><article class="playbook-content">'+''.join(out)+'</article></div>'
(root/'static/support-playbook.js').write_text('// Internal team handbook, based on docs/SUPPORT-SOP.md. No customer data.\nexport function supportPlaybook(){return '+json.dumps(page,ensure_ascii=False)+';}\n')
