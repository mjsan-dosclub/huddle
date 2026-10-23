"""Public marketing, application and recipient routing without shared UI bundles."""
import os,re,urllib.parse,html
import public_urls

def host(h):return urllib.parse.urlsplit('//'+h.headers.get('Host','')).hostname or ''
def app_host(h):return host(h)==os.environ.get('HUDDLE_APP_HOST','app.huddle.co.in') or host(h).startswith('app.') and host(h).endswith('.localhost')
def card_host(h):return host(h)==os.environ.get('HUDDLE_CARD_HOST','c.huddle.co.in') or host(h).startswith('c.') and host(h).endswith('.localhost')
def config(app):return {'app_origin':os.environ.get('HUDDLE_APP_ORIGIN','').rstrip('/'),'public_origin':os.environ.get('HUDDLE_PUBLIC_ORIGIN','').rstrip('/'),'card_origin':os.environ.get('HUDDLE_CARD_ORIGIN','').rstrip('/'),'google_configured':bool(os.environ.get('GOOGLE_CLIENT_ID') and os.environ.get('GOOGLE_CLIENT_SECRET'))}
def serve(app,h,c,method,path):
    if path=='/api/public/config' and method=='GET':return True,config(app)
    if path=='/api/public/handle' and method=='GET':
        h.limited('handle',180);value=h.query().get('handle',[''])[0].lower()
        valid=public_urls.valid(value) and '--' not in value
        available=valid and not c.execute('SELECT 1 FROM public_url_aliases WHERE path=?',(value,)).fetchone()
        return True,{'available':bool(available),'error':'' if available else 'Choose an available handle, 3–40 letters, digits or hyphens.'}
    if path=='/static/sample-qr.svg' and method=='GET':
        target=os.environ.get('HUDDLE_PUBLIC_ORIGIN',app.base_url()).rstrip('/')+'/'
        svg=h.qr_svg(c,'',target,{'foreground':'#183f32','background':'#ffffff'})
        import xml.etree.ElementTree as ET
        root=ET.fromstring(svg);width=float(root.attrib['viewBox'].split()[2]);size=(width-8)*.14;left=(width-size)/2
        logo=f'<rect x="{left-.7}" y="{left-.7}" width="{size+1.4}" height="{size+1.4}" rx=".5" fill="white"/><text x="{width/2}" y="{width/2+size*.23}" text-anchor="middle" font-family="sans-serif" font-weight="700" font-size="{size*.75}" fill="#183f32">h*</text>'
        svg=svg.replace('</svg>',logo+'</svg>')
        h.send(200,svg,'image/svg+xml');return True,None
    if method!='GET':return False,None
    if path in ('/terms','/privacy','/data-protection','/refunds','/shipping','/contact','/about'):
        import legal
        h.send(200,legal.page(path),'text/html; charset=utf-8');return True,None
    if path=='/api/public/preview':
        theme=h.query().get('theme',['executive'])[0]
        if theme not in ('executive','mint','sunset'):theme='executive'
        return True,{'profile':{'name':'Kavin Subramanian','title':'Partnerships · Marina Works, Chennai','email':'kavin@example.com','phone':'+91 98765 43210','bio':'Good conversations make great things happen. Let’s build something together.','photo':'','personal_links':[{'label':'LinkedIn','url':'https://www.linkedin.com/'}]},'company':{'name':'MARINA WORKS','logo':'','logo_scale':100,'background':'#242a29','website':'https://example.com','images':[],'tagline':'','description':'','allow_employee_banners':True},'division':None,'template':{'name':theme,'layout':theme,'accent':{'executive':'#242a29','mint':'#b7f264','sunset':'#ed795e'}[theme]},'slug':'demo-preview','persona':'Executive','banner_images':[],'preview':True,'blocks':{'whatsapp':{'number':'919876543210','url':'https://wa.me/919876543210','message':''}},'lead_capture':True}
    if path=='/sw.js' and card_host(h):
        h.send(200,(app.ROOT/'static/card-sw.js').read_bytes(),'application/javascript',{'Service-Worker-Allowed':'/'});return True,None
    if path=='/accept' and os.environ.get('HUDDLE_APP_ORIGIN') and not app_host(h):
        target=os.environ['HUDDLE_APP_ORIGIN'].rstrip('/')+'/accept?token='+urllib.parse.quote(h.query().get('token',[''])[0])
        h.send(302,b'','text/plain',{'Location':target});return True,None
    if card_host(h) and re.fullmatch('/[a-zA-Z0-9-]+(?:/[a-zA-Z0-9-]+)?',path) and path not in ('/sw.js',):
        return document(app,h,'public-card.html')
    if path.startswith('/c/'):
        if path=='/c/sw.js':
            h.send(200,(app.ROOT/'static/card-sw.js').read_bytes(),'application/javascript',{'Service-Worker-Allowed':'/c/'});return True,None
        return document(app,h,'public-card.html')
    if path.startswith('/manifest/') and path.endswith('.webmanifest'):
        slug=public_urls.decode(app,path[len('/manifest/'):-12]);card=app.public_card(c,slug);slug=card['slug']
        prefix='/' if card_host(h) else '/c/'
        h.send(200,{'name':'HUDDLE digital card','short_name':'HUDDLE','id':prefix+slug,'start_url':prefix+slug,'scope':prefix,'display':'standalone','theme_color':'#164e40','background_color':'#f7f8f4','icons':[{'src':'/static/huddle-icon-192.png','sizes':'192x192','type':'image/png','purpose':'any'},{'src':'/static/huddle-icon-512.png','sizes':'512x512','type':'image/png','purpose':'any maskable'}]},'application/manifest+json');return True,None
    if path in ('/','/pricing','/templates','/features','/enterprise','/nfc-cards','/how-it-works') and not app_host(h):return document(app,h,'marketing.html')
    if not app_host(h) and (path=='/dashboard' or path.startswith('/dashboard/')):
        h.send(302,b'','text/plain',{'Location':'/app'+path});return True,None
    if app_host(h) and path=='/':
        h.send(302,b'','text/plain',{'Location':'/dashboard'});return True,None
    if path in ('/login','/signup','/register','/dashboard') or path.startswith('/dashboard/') or path=='/app' or path.startswith('/app/') or path in ('/accept','/join'):
        canonical=path[4:] if path.startswith('/app/') else path
        if canonical=='/app':canonical='/dashboard'
        prefix='' if app_host(h) else '/app'
        if path in ('/register','/login','/signup') and not app_host(h):
            h.send(302,b'','text/plain',{'Location':prefix+('/signup' if path in ('/register','/signup') else '/login')});return True,None
        if canonical=='/login' and not h.query().get('challenge'):
            try:
                h.actor(c);next_path=h.query().get('next',['/dashboard'])[0]
                if next_path not in ('/dashboard','/dashboard/cards','/dashboard/leads','/dashboard/settings','/dashboard/team','/dashboard/templates','/dashboard/analytics','/dashboard/nfc','/dashboard/billing','/sales'):next_path='/dashboard'
                h.send(302,b'','text/plain',{'Location':'/sales' if next_path=='/sales' else prefix+next_path});return True,None
            except app.Problem as e:
                if e.code not in (401,403):raise
        if canonical.startswith('/dashboard'):
            try:h.actor(c)
            except app.Problem as e:
                if e.code not in (401,403):raise
                h.send(302,b'','text/plain',{'Location':prefix+'/login?next='+urllib.parse.quote(canonical,safe='/')});return True,None
        if canonical in ('/login','/signup','/register') or canonical.startswith('/dashboard') or canonical in ('/accept','/join'):
            return document(app,h,'index.html')
        raise app.Problem('Application route not found.',404)
    return False,None

def document(app,h,name):h.send(200,(app.ROOT/'static'/name).read_bytes(),'text/html; charset=utf-8');return True,None
