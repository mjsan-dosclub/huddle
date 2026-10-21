"""Immutable URL reservations. Public routing resolves to a card ID, never a tenant claim."""
import re,urllib.parse
RESERVED={'api','app','admin','super-admin','sales','login','signup','dashboard','templates','pricing','features','static','manifest','sw','sw-js','support','help','contact','privacy','terms','nfc-cards','downloads','new','settings','null','undefined','www','huddle'}

def valid(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[a-z0-9][a-z0-9-]{1,58}[a-z0-9]',value)) and value not in RESERVED

def segment(app,value):
    if not valid(value):raise app.Problem('Use 3–60 lowercase letters, numbers or single hyphens, with a letter or number at each end. Choose a non-reserved name.')
    if '--' in value:raise app.Problem('Use single hyphens between words.')
    return value

def decode(app,value):
    if not re.fullmatch(r'[a-zA-Z0-9-]+(?:/[a-zA-Z0-9-]+)?',value):raise app.Problem('This card is unavailable.',404)
    return value

def canonical(c,card):
    r=c.execute('SELECT o.slug,s.card_slug FROM card_url_settings s JOIN organizations o ON o.id=s.tenant_id WHERE s.tenant_id=? AND s.card_id=?',(card['tenant_id'],card['id'])).fetchone()
    return r['slug']+'/'+r['card_slug'] if r else card['slug']

def reserve(app,c,path,tenant,cid):
    row=c.execute('SELECT tenant_id,card_id FROM public_url_aliases WHERE path=?',(path,)).fetchone()
    if row:
        if row['tenant_id']!=tenant or row['card_id']!=cid:raise app.Problem('That URL is already reserved. Choose another name.',409)
    else:c.execute('INSERT INTO public_url_aliases VALUES(?,?,?,?)',(path,tenant,cid,app.now()))

def new_card(app,c,tenant,cid,legacy):
    c.execute('INSERT INTO card_url_settings VALUES(?,?,?)',(cid,tenant,legacy))
    reserve(app,c,legacy,tenant,cid)
    org=c.execute('SELECT slug FROM organizations WHERE id=?',(tenant,)).fetchone()[0]
    reserve(app,c,org+'/'+legacy,tenant,cid)

def legacy_handle(app,c,tenant,cid,handle):
    # Optional signup short aliases share the same permanent registry as old links.
    segment(app,handle);reserve(app,c,handle,tenant,cid)
    set_card(app,c,tenant,cid,handle)

def set_card(app,c,tenant,cid,name):
    segment(app,name);org=c.execute('SELECT slug FROM organizations WHERE id=?',(tenant,)).fetchone()[0]
    reserve(app,c,org+'/'+name,tenant,cid)
    c.execute('UPDATE card_url_settings SET card_slug=? WHERE tenant_id=? AND card_id=?',(name,tenant,cid))

def settings(c,card):
    org=c.execute('SELECT slug FROM organizations WHERE id=?',(card['tenant_id'],)).fetchone()[0]
    name=c.execute('SELECT card_slug FROM card_url_settings WHERE tenant_id=? AND card_id=?',(card['tenant_id'],card['id'])).fetchone()[0]
    return {'namespace':org,'card_slug':name,'path':org+'/'+name}

def routes(app,h,c,actor,method,path):
    tenant=actor['tenant_id'];admin=actor['role'] in ('owner','admin')
    if path=='/api/public-urls/organization/availability' and method=='GET':
        app.require_admin(actor);h.limited('namespace-check',120);name=h.query().get('name',[''])[0]
        row=c.execute('SELECT tenant_id FROM public_namespaces WHERE slug=?',(name,)).fetchone() if valid(name) else None
        available=valid(name) and '--' not in name and (not row or row['tenant_id']==tenant)
        return True,{'available':bool(available),'message':'Available for your organization.' if available else 'Choose a different, valid organization URL name.'}
    if path=='/api/public-urls/organization' and method=='PUT':
        app.require_admin(actor);h.limited('namespace-update',10);d=h.body();name=segment(app,d.get('namespace'))
        org=c.execute('SELECT slug FROM organizations WHERE id=?',(tenant,)).fetchone()[0]
        if d.get('expected_namespace')!=org:raise app.Problem('The organization URL changed. Reload and try again.',409)
        row=c.execute('SELECT tenant_id FROM public_namespaces WHERE slug=?',(name,)).fetchone()
        if row and row['tenant_id']!=tenant:raise app.Problem('That organization URL is already reserved.',409)
        if not row:c.execute('INSERT INTO public_namespaces VALUES(?,?,?)',(name,tenant,app.now()))
        # Reserve every new destination first. Any conflict rolls back the whole rename.
        for card in c.execute('SELECT card_id,card_slug FROM card_url_settings WHERE tenant_id=?',(tenant,)).fetchall():reserve(app,c,name+'/'+card['card_slug'],tenant,card['card_id'])
        c.execute('UPDATE organizations SET slug=? WHERE id=?',(name,tenant))
        app.audit(c,actor,'public_url.organization_changed',org+' → '+name)
        return True,{'ok':True,'namespace':name}
    match=re.fullmatch(r'/api/cards/([a-zA-Z0-9-]+)/public-url(?:/(availability))?',path)
    if not match:return False,None
    cid,availability=match.groups();card=app.scoped(c,'cards',tenant,cid)
    if card['user_id']!=actor['id']:app.require_admin(actor)
    if admin and card['user_id']!=actor['id']:
        target=app.scoped(c,'users',tenant,card['user_id'])
        if target['role']=='owner' and actor['role']!='owner':raise app.Problem('Only Owners can edit another Owner.',403)
    current=settings(c,card)
    if availability and method=='GET':
        h.limited('url-check',120);name=h.query().get('name',[''])[0];ok=valid(name) and '--' not in name
        row=c.execute('SELECT card_id FROM public_url_aliases WHERE path=?',(current['namespace']+'/'+name,)).fetchone() if ok else None
        available=ok and (not row or row['card_id']==cid)
        suggestions=[]
        if ok and not available:
            for suffix in ('2','3','team'):
                proposed=name[:54]+'-'+suffix
                if not c.execute('SELECT 1 FROM public_url_aliases WHERE path=?',(current['namespace']+'/'+proposed,)).fetchone():suggestions.append(proposed)
        return True,{'available':bool(available),'suggestions':suggestions,'message':'Available for your card.' if available else 'Use an available name with 3–60 lowercase letters, numbers or single hyphens.'}
    if not availability and method=='GET':return True,{**current,'can_edit_namespace':admin,'url':app.base_url()+'/c/'+current['path']}
    if not availability and method=='PUT':
        h.limited('url-update',20);d=h.body()
        if d.get('expected_path')!=current['path']:raise app.Problem('The public URL changed. Reload before saving.',409)
        name=d.get('card_slug');set_card(app,c,tenant,cid,name)
        app.audit(c,actor,'public_url.card_changed',cid+': '+current['path']+' → '+current['namespace']+'/'+name)
        return True,{'ok':True,'path':current['namespace']+'/'+name}
    raise app.Problem('Method not allowed.',405)
