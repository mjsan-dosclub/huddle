"""Operator control plane. Global grants never arise from tenant registration."""
import base64,hashlib,hmac,html,json,os,re,secrets,urllib.parse,urllib.request
from http.cookies import SimpleCookie
import billing,security,pricing

AUDIT_LABELS={
 'sales.staff_created':'Internal sales login created','sales.staff_password_reset':'Sales password reset by administrator','sales.staff_password_changed':'Sales colleague changed password','sales.staff_login':'Sales colleague signed in',
 'sales.agent_access':'Sales colleague access changed','sales.export':'Sales enquiries exported','sales.open':'Enquiry opened','sales.activity':'Sales follow-up recorded','sales.assign':'Enquiry assignment changed',
 'billing.offer_updated':'Published pricing updated',
 'package.updated':'Package updated','tenant.plan_override':'Package access changed',
 'tenant.active':'Organization activated','tenant.paused':'Organization paused','tenant.suspended':'Organization suspended',
 'billing.price_created':'Price created','billing.price_availability':'Price availability changed',
 'billing.reconciled':'Subscription checked','billing.offline_payment_recorded':'Offline payment recorded',
 'support.started':'Support inspection opened','support.viewed':'Support information viewed','support.ended':'Support inspection closed',
 'platform.elevated':'Super Admin unlocked','platform.logout':'Super Admin locked',
 'platform.mfa_setup_started':'Authenticator setup started','platform.mfa_enrolled':'Authenticator enabled',
 'tenant.renamed':'Organization name changed','tenant.archived':'Organization archived','tenant.restored':'Organization restored',
 'tenant.password_reset':'Customer password set by administrator','tenant.password_link':'Customer password recovery email sent'
}
def audit_label(action):return AUDIT_LABELS.get(action,action.replace('.',' ').replace('_',' ').capitalize())

def audit(app,c,account,action,tenant=None,reason='',details=None):
    c.execute('INSERT INTO platform_audit VALUES(?,?,?,?,?,?,?)',(app.uid(),account,tenant,action,app.text(reason,1000),app.dump(details or {}),app.now()))

def token(h):
    try:return hashlib.sha256(SimpleCookie(h.headers.get('Cookie',''))['huddle_operator'].value.encode()).hexdigest()
    except (KeyError,ValueError):return ''

def identity(app,h,c,elevated=True):
    op=c.execute('SELECT a.* FROM platform_sessions s JOIN accounts a ON a.id=s.account_id JOIN platform_admin_grants g ON g.account_id=a.id WHERE s.token_hash=? AND s.expires>? AND a.disabled IS NULL',(token(h),app.now())).fetchone()
    if op:return dict(op)
    if elevated:raise app.Problem('Not found.',404)
    try:normal=h.token_hash()
    except app.Problem:raise app.Problem('Not found.',404)
    row=c.execute('SELECT a.* FROM sessions s JOIN accounts a ON a.id=s.account_id JOIN platform_admin_grants g ON g.account_id=a.id WHERE s.token_hash=? AND s.expires>? AND a.disabled IS NULL',(normal,app.now())).fetchone()
    if not row:raise app.Problem('Not found.',404)
    return dict(row)

def issue(app,h,c,account):
    value=secrets.token_urlsafe(32);c.execute('DELETE FROM platform_sessions WHERE expires<?',(app.now(),))
    c.execute('INSERT INTO platform_sessions VALUES(?,?,?)',(hashlib.sha256(value.encode()).hexdigest(),account,app.now()+600))
    h.send(200,{'ok':True,'expires_in':600},headers={'Set-Cookie':'huddle_operator='+value+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=600'+('; Secure' if app.base_url().startswith('https://') else '')})

def verify(app,c,account,code,pending=False):
    row=c.execute('SELECT * FROM platform_security WHERE account_id=?',(account,)).fetchone()
    encrypted=row['pending_secret'] if row and pending else row['secret'] if row and row['enabled'] else None
    if not encrypted or not re.fullmatch(r'\d{6}',str(code)):return False
    secret=security.decrypt(app,'platform',account,encrypted)
    for offset in (-1,0,1):
        counter=app.now()//30+offset
        if counter>row['last_counter'] and hmac.compare_digest(security.totp(secret,counter*30),str(code)):
            c.execute('UPDATE platform_security SET last_counter=? WHERE account_id=?',(counter,account));return True
    return False

def metrics(app,c):
    # MRR is contracted, current recurring revenue; trial/test/manual access is excluded.
    stamp=app.now();subs=c.execute("SELECT s.*,p.amount_paise,p.interval FROM subscriptions s JOIN plan_prices p ON p.id=s.price_id JOIN organizations o ON o.id=s.tenant_id WHERE s.mode IN ('live','offline') AND s.status='ACTIVE' AND s.current_period_end>?",(stamp,)).fetchall()
    mrr=sum(r['amount_paise']/12 if r['interval']=='annual' else r['amount_paise'] for r in subs)
    trials=c.execute("SELECT count(DISTINCT tenant_id) FROM subscriptions WHERE status='TRIALING'").fetchone()[0]
    converted=c.execute("SELECT count(DISTINCT s.tenant_id) FROM subscriptions s WHERE s.mode IN ('live','offline') AND s.status='ACTIVE' AND s.current_period_end>? AND EXISTS(SELECT 1 FROM subscriptions t WHERE t.tenant_id=s.tenant_id AND t.status='TRIALING')",(stamp,)).fetchone()[0]
    start=stamp-30*86400;ending=c.execute("SELECT count(*) FROM subscriptions WHERE mode IN ('live','offline') AND status IN ('CANCELED','COMPLETED') AND updated>=?",(start,)).fetchone()[0]
    denominator=c.execute("SELECT count(*) FROM subscriptions WHERE mode IN ('live','offline') AND created<? AND (current_period_end>=? OR updated>=?)",(start,start,start)).fetchone()[0]
    return {'mrr_paise':round(mrr),'arr_paise':round(mrr*12),'active_subscriptions':len(subs),'organizations':c.execute('SELECT count(*) FROM organizations').fetchone()[0],'past_due':c.execute("SELECT count(*) FROM subscriptions WHERE status='PAST_DUE' AND mode='live'").fetchone()[0],'trial_conversion_percent':round(converted/trials*100,2) if trials else None,'subscription_churn_30d_percent':round(ending/denominator*100,2) if denominator else None,'definitions':{'mrr':'Current active live/offline recurring contracts, annual price divided by 12. Excludes taxes, trials, test payments and access-only overrides.','churn':'Canceled/completed contracts updated in the last 30 days divided by contracts present at the start. Operational estimate; historical snapshots are not available.','trial_conversion':'Tenants with a recorded trial and currently active live/offline recurring subscription divided by tenants with a recorded trial.'}}

def tenant_detail(app,c,tenant,include_members=False):
    org=c.execute('SELECT id,name,slug,status,created FROM organizations WHERE id=?',(tenant,)).fetchone()
    if not org:raise app.Problem('Organization not found.',404)
    detail={**dict(org),'billing':billing.summary(app,c,tenant),'leads_count':c.execute('SELECT count(*) FROM contact_exchanges WHERE tenant_id=?',(tenant,)).fetchone()[0]}
    if include_members:
        members=c.execute('SELECT u.id,u.role,u.active,u.data,a.email,a.id AS account_id,a.disabled FROM users u JOIN accounts a ON a.id=u.account_id WHERE u.tenant_id=? ORDER BY u.created',(tenant,)).fetchall()
        detail['members']=[{'id':m['id'],'role':m['role'],'active':bool(m['active'] and m['disabled'] is None),'name':json.loads(m['data']).get('name',''),'email':m['email'],
            'other_organizations':max(0,c.execute('SELECT count(*) FROM users WHERE account_id=?',(m['account_id'],)).fetchone()[0]-1),
            'protected':bool(c.execute('SELECT 1 FROM platform_admin_grants WHERE account_id=?',(m['account_id'],)).fetchone())} for m in members]
    return detail

def send_recovery_email(app,address,link):
    key=os.environ.get('RESEND_API_KEY');sender=os.environ.get('RESEND_FROM')
    if not key or not sender or not os.environ.get('PUBLIC_BASE_URL'):raise app.Problem('Email delivery is not configured. Choose a manual or generated password instead.',503)
    payload={'from':sender,'to':[address],'subject':'Reset your HUDDLE password','html':'<p>A HUDDLE administrator requested a password reset for your account.</p><p><a href="'+html.escape(link,quote=True)+'">Choose a new password</a>. This link expires in 30 minutes.</p><p>If you did not expect this, contact your organization administrator.</p>'}
    request=urllib.request.Request('https://api.resend.com/emails',data=app.dump(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=12) as response:
            if not json.load(response).get('id'):raise ValueError('Missing delivery reference')
    except (OSError,ValueError):raise app.Problem('Recovery email could not be confirmed. Try again or choose another method.',502)

def route(app,h,c,method,path):
    if path=='/reset-password' and method=='GET':
        h.send(200,(app.ROOT/'static/reset-password.html').read_bytes(),'text/html; charset=utf-8');return True,None
    if path=='/api/password/recover' and method=='POST':
        h.limited('password-recover',8);d=h.body();value=str(d.get('token',''))
        row=c.execute('SELECT * FROM customer_password_resets WHERE token_hash=? AND used IS NULL AND expires>?',(hashlib.sha256(value.encode()).hexdigest(),app.now())).fetchone()
        if not row:raise app.Problem('This recovery link has expired or has already been used.',410)
        if c.execute('SELECT 1 FROM platform_admin_grants WHERE account_id=?',(row['account_id'],)).fetchone():raise app.Problem('This account needs platform administrator recovery.',403)
        if not c.execute('SELECT 1 FROM accounts WHERE id=? AND disabled IS NULL',(row['account_id'],)).fetchone():raise app.Problem('This account is unavailable.',410)
        c.execute('UPDATE accounts SET password_hash=? WHERE id=?',(app.password_hash(d.get('password')),row['account_id']))
        c.execute('UPDATE customer_password_resets SET used=? WHERE account_id=? AND used IS NULL',(app.now(),row['account_id']))
        c.execute('DELETE FROM sessions WHERE account_id=?',(row['account_id'],))
        c.execute('DELETE FROM auth_challenges WHERE account_id=?',(row['account_id'],))
        c.execute('DELETE FROM platform_sessions WHERE account_id=?',(row['account_id'],))
        return True,{'ok':True}
    if path=='/super-admin' or path.startswith('/super-admin/'):
        identity(app,h,c,False)
        if method!='GET':raise app.Problem('Not found.',404)
        h.send(200,(app.ROOT/'static/platform.html').read_bytes(),'text/html; charset=utf-8');return True,None
    if not path.startswith('/api/platform'):return False,None
    account=identity(app,h,c,False);aid=account['id']
    if path=='/api/platform/access' and method=='GET':
        setting=c.execute('SELECT enabled FROM platform_security WHERE account_id=?',(aid,)).fetchone()
        try:identity(app,h,c);elevated=True
        except app.Problem:elevated=False
        return True,{'mfa_enabled':bool(setting and setting[0]),'elevated':elevated,'email':account['email'],'email_configured':bool(os.environ.get('RESEND_API_KEY') and os.environ.get('RESEND_FROM') and os.environ.get('PUBLIC_BASE_URL'))}
    if path in ('/api/platform/mfa/setup','/api/platform/mfa/confirm','/api/platform/elevate') and method=='POST':
        h.limited('platform-mfa',8);d=h.body()
        if not app.password_matches(str(d.get('password','')),account['password_hash']):raise app.Problem('Password or authenticator is incorrect.',403)
        row=c.execute('SELECT * FROM platform_security WHERE account_id=?',(aid,)).fetchone()
        if path.endswith('/setup'):
            if row and row['enabled']:raise app.Problem('Platform MFA is already enrolled.',409)
            secret=base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=');encrypted=security.encrypt(app,'platform',aid,secret)
            c.execute('INSERT INTO platform_security(account_id,pending_secret) VALUES(?,?) ON CONFLICT(account_id) DO UPDATE SET pending_secret=excluded.pending_secret,last_counter=-1',(aid,encrypted))
            audit(app,c,aid,'platform.mfa_setup_started')
            return True,{'secret':secret,'uri':'otpauth://totp/'+urllib.parse.quote('HUDDLE Platform:'+account['email'])+'?secret='+secret+'&issuer=HUDDLE%20Platform'}
        pending=path.endswith('/confirm')
        if not verify(app,c,aid,d.get('code'),pending):raise app.Problem('Password or authenticator is incorrect.',403)
        if pending:c.execute('UPDATE platform_security SET secret=pending_secret,pending_secret=NULL,enabled=1 WHERE account_id=?',(aid,))
        audit(app,c,aid,'platform.mfa_enrolled' if pending else 'platform.elevated');issue(app,h,c,aid);return True,None
    account=identity(app,h,c)
    if path=='/api/platform/logout' and method=='POST':
        c.execute('DELETE FROM platform_sessions WHERE token_hash=?',(token(h),));audit(app,c,aid,'platform.logout');h.send(200,{'ok':True},headers={'Set-Cookie':'huddle_operator=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'});return True,None
    if path=='/api/platform/overview' and method=='GET':return True,metrics(app,c)
    if path=='/api/platform/tenants' and method=='GET':
        q=app.text(h.query().get('q',[''])[0],100).lower()
        try:page=max(0,min(100000,int(h.query().get('page',['0'])[0])))
        except (ValueError,TypeError):raise app.Problem('Choose a valid organization page.')
        args=('%'+q+'%','%'+q+'%')
        rows=c.execute("SELECT id FROM organizations WHERE lower(name) LIKE ? OR lower(slug) LIKE ? ORDER BY created DESC,id LIMIT 25 OFFSET ?",(*args,page*25)).fetchall()
        total=c.execute('SELECT count(*) FROM organizations WHERE lower(name) LIKE ? OR lower(slug) LIKE ?',args).fetchone()[0]
        return True,{'tenants':[tenant_detail(app,c,r['id']) for r in rows],'page':page,'page_size':25,'total':total,'has_more':(page+1)*25<total}
    if path=='/api/platform/packages' and method=='GET':
        return True,{'packages':[billing.plan(c,r['id']) for r in c.execute("SELECT id FROM plans ORDER BY CASE id WHEN 'free' THEN 0 WHEN 'pro' THEN 1 WHEN 'enterprise' THEN 2 ELSE 3 END,id")],'quota_fields':list(billing.QUOTA_FIELDS)}
    if path.startswith('/api/platform/packages/') and method=='PUT':
        pid=path.rsplit('/',1)[-1];current=billing.plan(c,pid)
        if not current:raise app.Problem('Unknown package.',404)
        d=h.body();reason=app.text(d.get('reason'),1000);name=app.text(d.get('name'),80);ent=d.get('entitlements')
        if len(reason)<10 or not name:raise app.Problem('Enter a package name and change reason (at least 10 characters).')
        if not isinstance(ent,dict) or set(ent)!=set(current['entitlements']):raise app.Problem('Supply every existing package setting; unknown settings are not accepted.')
        for key,value in ent.items():
            if key in billing.QUOTA_FIELDS:
                if value is not None and (type(value)!=int or not 1<=value<=1000000):raise app.Problem('Quotas must be 1–1,000,000, or null for unlimited.')
            elif type(value)!=bool:raise app.Problem('Feature settings must be true or false.')
        version=d.get('version')
        if type(version)!=int or version!=current['version']:raise app.Problem('This package changed. Reload before saving.',409)
        updated=c.execute('UPDATE plans SET name=?,entitlements=?,version=version+1 WHERE id=? AND version=?',(name,app.dump(ent),pid,version))
        if updated.rowcount!=1:raise app.Problem('This package changed. Reload before saving.',409)
        audit(app,c,aid,'package.updated',reason=reason,details={'plan':pid,'before':current,'after':billing.plan(c,pid)})
        return True,{'ok':True,'package':billing.plan(c,pid)}
    if path.startswith('/api/platform/pricing-offers/') and method=='PUT':
        return True,pricing.update_offer(app,c,path.rsplit('/',1)[-1],h.body(),aid,audit)
    if path=='/api/platform/quote-requests' and method=='GET':
        return True,{'requests':[{**dict(r),'details':json.loads(r['details'])} for r in c.execute('SELECT * FROM enterprise_quote_requests ORDER BY created DESC,id DESC LIMIT 100')]}
    if path=='/api/platform/prices':
        if method=='GET':return True,{'prices':[dict(r) for r in c.execute('SELECT * FROM plan_prices ORDER BY plan_id,amount_paise')],'offers':pricing.offers(c),'packages':[dict(r) for r in c.execute('SELECT id,name FROM plans ORDER BY name')]}
        if method=='POST':
            d=h.body();reason=app.text(d.get('reason'),1000);pid=d.get('id')
            if len(reason)<10:raise app.Problem('Enter a pricing change reason.')
            if not isinstance(pid,str) or not re.fullmatch(r'[a-z][a-z0-9-]{2,59}',pid) or (d.get('plan_id')=='free' or not isinstance(d.get('plan_id'),str) or not billing.plan(c,d['plan_id'])) or d.get('interval') not in ('monthly','annual'):raise app.Problem('Invalid price definition.')
            amount=d.get('amount_paise')
            if type(amount)!=int or not 100<=amount<=100000000:raise app.Problem('Use a positive integer amount in paise.')
            c.execute('INSERT INTO plan_prices VALUES(?,?,?,?,?,1)',(pid,d['plan_id'],d['interval'],amount,'INR'))
            audit(app,c,aid,'billing.price_created',reason=reason,details={'price_id':pid,'amount_paise':amount});return True,{'ok':True,'gateway_mapping_required':'RAZORPAY_PLAN_'+pid.upper().replace('-','_')}
    if path.startswith('/api/platform/prices/') and method=='POST':
        d=h.body();pid=path.rsplit('/',1)[-1];reason=app.text(d.get('reason'),1000)
        if len(reason)<10 or type(d.get('active'))!=bool:raise app.Problem('Supply an active flag and pricing change reason.')
        if not c.execute('SELECT 1 FROM plan_prices WHERE id=?',(pid,)).fetchone():raise app.Problem('Price not found.',404)
        c.execute('UPDATE plan_prices SET active=? WHERE id=?',(int(d['active']),pid));audit(app,c,aid,'billing.price_availability',reason=reason,details={'price_id':pid,'active':d['active']});return True,{'ok':True}
    if path=='/api/platform/audit' and method=='GET':
        query=h.query();q=app.text(query.get('q',[''])[0],100).lower()
        try:page=max(0,min(100000,int(query.get('page',['0'])[0])));days=int(query.get('days',['0'])[0])
        except (ValueError,TypeError):raise app.Problem('Choose a valid audit page and date range.')
        if days not in (0,7,30,90):raise app.Problem('Choose a valid audit date range.')
        matching_actions=[key for key,label in AUDIT_LABELS.items() if q and q in label.lower()]
        label_clause=' OR a.action IN ('+','.join('?' for _ in matching_actions)+')' if matching_actions else ''
        where="WHERE (lower(a.action) LIKE ? OR lower(a.reason) LIKE ? OR lower(COALESCE(ac.email,a.actor_account_id)) LIKE ? OR lower(COALESCE(o.name,a.tenant_id,'')) LIKE ?"+label_clause+") AND a.created>=?"
        args=tuple(['%'+q+'%']*4+matching_actions+[app.now()-days*86400 if days else 0])
        joins=' FROM platform_audit a LEFT JOIN accounts ac ON ac.id=a.actor_account_id LEFT JOIN organizations o ON o.id=a.tenant_id '
        rows=c.execute('SELECT a.*,ac.email AS actor_email,o.name AS organization_name'+joins+where+' ORDER BY a.created DESC,a.id DESC LIMIT 25 OFFSET ?',(*args,page*25)).fetchall()
        total=c.execute('SELECT count(*)'+joins+where,args).fetchone()[0]
        return True,{'entries':[{**dict(r),'action_label':audit_label(r['action'])} for r in rows],'page':page,'page_size':25,'total':total,'has_more':(page+1)*25<total,'auto_delete':False,'retention':'Records are retained. Date filters change only what is shown.'}

    if path=='/api/platform/support' and method=='POST':
        d=h.body();tenant=d.get('tenant_id');tenant_detail(app,c,tenant);reason=app.text(d.get('reason'),1000)
        if len(reason)<10:raise app.Problem('Enter a support reason (at least 10 characters).')
        sid=app.uid();c.execute('INSERT INTO support_sessions VALUES(?,?,?,?,?,?,?)',(sid,aid,tenant,reason,app.now(),app.now()+600,None));audit(app,c,aid,'support.started',tenant,reason,{'session_id':sid});return True,{'id':sid,'expires_in':600,'read_only':True}
    if path.startswith('/api/platform/support/'):
        sid=path.rsplit('/',1)[-1];s=c.execute('SELECT * FROM support_sessions WHERE id=? AND actor_account_id=? AND expires>? AND ended IS NULL',(sid,aid,app.now())).fetchone()
        if not s:raise app.Problem('Support session unavailable.',404)
        if method=='DELETE':c.execute('UPDATE support_sessions SET ended=? WHERE id=?',(app.now(),sid));audit(app,c,aid,'support.ended',s['tenant_id'],s['reason']);return True,{'ok':True}
        if method=='GET':
            audit(app,c,aid,'support.viewed',s['tenant_id'],s['reason'])
            # Deliberately excludes contact contents, secrets and invitation bearer links.
            return True,{'read_only':True,'tenant':tenant_detail(app,c,s['tenant_id']),'members':[{'id':r['id'],'role':r['role'],'active':r['active'],'name':json.loads(r['data']).get('name','')} for r in c.execute('SELECT id,role,active,data FROM users WHERE tenant_id=?',(s['tenant_id'],))]}
        raise app.Problem('Read-only support session.',405)
    match=re.fullmatch(r'/api/platform/tenants/([a-zA-Z0-9-]+)(?:/(status|override|reconcile|offline-payment|rename|archive|restore|members/([a-zA-Z0-9-]+)/password))?',path)
    if match:
        tenant,action,member_id=match.groups();detail=tenant_detail(app,c,tenant)
        if method=='GET' and action is None:return True,tenant_detail(app,c,tenant,True)
        if method!='POST':raise app.Problem('Not found.',404)
        d=h.body();reason=app.text(d.get('reason'),1000)
        if len(reason)<10:raise app.Problem('Enter an administrative reason (at least 10 characters).')
        if action=='rename':
            name=app.text(d.get('name'),150)
            if len(name)<2:raise app.Problem('Enter an organization name with at least two characters.')
            old=c.execute('SELECT name,data FROM organizations WHERE id=?',(tenant,)).fetchone();brand=json.loads(old['data']);brand['name']=name
            c.execute('UPDATE organizations SET name=?,data=? WHERE id=?',(name,app.dump(brand),tenant))
            audit(app,c,aid,'tenant.renamed',tenant,reason,{'before':old['name'],'after':name});return True,{'ok':True}
        if action=='archive':
            if d.get('confirm')!=detail['name']:raise app.Problem('Type the organization name to confirm archival.')
            if detail['status']=='archived':raise app.Problem('This organization is already archived.',409)
            if c.execute("SELECT 1 FROM subscriptions WHERE tenant_id=? AND status IN ('ACTIVE','TRIALING','PAST_DUE')",(tenant,)).fetchone():raise app.Problem('Resolve active, trial or past-due billing before archiving this organization.',409)
            if c.execute('SELECT 1 FROM users u JOIN platform_admin_grants g ON g.account_id=u.account_id WHERE u.tenant_id=?',(tenant,)).fetchone():raise app.Problem('Move the platform administrator to another organization before archiving this one.',409)
            c.execute("UPDATE organizations SET status='archived' WHERE id=?",(tenant,))
            c.execute('DELETE FROM sessions WHERE active_tenant_id=?',(tenant,))
            audit(app,c,aid,'tenant.archived',tenant,reason);return True,{'ok':True}
        if action=='restore':
            if detail['status']!='archived':raise app.Problem('Only an archived organization can be restored.',409)
            for owner in c.execute("SELECT account_id FROM users WHERE tenant_id=? AND role='owner' AND active=1",(tenant,)).fetchall():
                billing.organization_capacity(app,c,owner['account_id'],enforce=True)
            c.execute("UPDATE organizations SET status='active' WHERE id=?",(tenant,))
            audit(app,c,aid,'tenant.restored',tenant,reason);return True,{'ok':True}
        if action and action.startswith('members/') and action.endswith('/password'):
            h.limited('platform-password-reset',12)
            m=c.execute('SELECT u.id,u.account_id,u.active,a.email,a.disabled FROM users u JOIN accounts a ON a.id=u.account_id WHERE u.tenant_id=? AND u.id=?',(tenant,member_id)).fetchone()
            if not m:raise app.Problem('Member not found in this organization.',404)
            if not m['active'] or m['disabled'] is not None:raise app.Problem('This member is inactive. Restore their access before resetting the password.',409)
            if c.execute('SELECT 1 FROM platform_admin_grants WHERE account_id=?',(m['account_id'],)).fetchone():raise app.Problem('Platform administrator passwords cannot be reset from an organization.',403)
            mode=d.get('mode')
            if mode=='email':
                value=secrets.token_urlsafe(36);c.execute('UPDATE customer_password_resets SET used=? WHERE account_id=? AND used IS NULL',(app.now(),m['account_id']))
                c.execute('INSERT INTO customer_password_resets VALUES(?,?,?,?,?)',(hashlib.sha256(value.encode()).hexdigest(),m['account_id'],app.now(),app.now()+1800,None))
                link=app.base_url()+'/reset-password?token='+urllib.parse.quote(value)
                send_recovery_email(app,m['email'],link)
                audit(app,c,aid,'tenant.password_link',tenant,reason,{'member':m['id'],'email':m['email']})
                return True,{'ok':True,'delivery':'email'}
            if mode not in ('manual','generated'):raise app.Problem('Choose manual, generated or email recovery.')
            password=d.get('password') if mode=='manual' else secrets.token_urlsafe(18)
            digest=app.password_hash(password)
            c.execute('UPDATE accounts SET password_hash=? WHERE id=?',(digest,m['account_id']))
            c.execute('DELETE FROM sessions WHERE account_id=?',(m['account_id'],))
            c.execute('DELETE FROM auth_challenges WHERE account_id=?',(m['account_id'],))
            c.execute('DELETE FROM platform_sessions WHERE account_id=?',(m['account_id'],))
            c.execute('UPDATE customer_password_resets SET used=? WHERE account_id=? AND used IS NULL',(app.now(),m['account_id']))
            audit(app,c,aid,'tenant.password_reset',tenant,reason,{'member':m['id'],'email':m['email'],'mode':mode})
            return True,{'ok':True,'email':m['email'],'password':password if mode=='generated' else None,'other_organizations':max(0,c.execute('SELECT count(*) FROM users WHERE account_id=?',(m['account_id'],)).fetchone()[0]-1)}
        if action=='status':
            status=d.get('status')
            if status not in ('active','suspended','paused'):raise app.Problem('Invalid workspace status.')
            if detail['status']=='archived':raise app.Problem('Use Restore to reopen an archived organization.',409)
            c.execute('UPDATE organizations SET status=? WHERE id=?',(status,tenant));audit(app,c,aid,'tenant.'+status,tenant,reason);return True,{'ok':True}
        if action=='override':
            pid=d.get('plan_id');p=billing.plan(c,pid)
            if not p:raise app.Problem('Unknown plan.')
            try:days=int(d.get('days',30))
            except (ValueError,TypeError):raise app.Problem('Invalid grant duration.')
            if not 1<=days<=366:raise app.Problem('Use a grant duration from 1 to 366 days.')
            limits=d.get('limits',{})
            if not isinstance(limits,dict) or any(k not in ('max_cards','max_seats','max_admins') or v is not None and (type(v)!=int or not 1<=v<=100000) for k,v in limits.items()):raise app.Problem('Invalid custom quotas.')
            c.execute('UPDATE entitlement_overrides SET revoked_at=? WHERE tenant_id=? AND revoked_at IS NULL',(app.now(),tenant))
            oid=app.uid();c.execute('INSERT INTO entitlement_overrides VALUES(?,?,?,?,?,?,?,?,?)',(oid,tenant,pid,app.dump(limits),reason,aid,app.now(),app.now()+days*86400,None));audit(app,c,aid,'tenant.plan_override',tenant,reason,{'plan':pid,'days':days,'limits':limits});return True,{'ok':True,'override_id':oid}
        if action=='reconcile':
            result=billing.reconcile(app,c,tenant);audit(app,c,aid,'billing.reconciled',tenant,reason);return True,result
        if action=='offline-payment':
            price=c.execute('SELECT * FROM plan_prices WHERE id=? AND active=1',(d.get('price_id'),)).fetchone();reference=app.text(d.get('reference'),200)
            if not price or not reference:raise app.Problem('Select a price and enter a unique bank/payment reference.')
            if c.execute("SELECT 1 FROM subscriptions WHERE tenant_id=? AND mode IN ('live','offline') AND status='ACTIVE' AND current_period_end>?",(tenant,app.now())).fetchone():raise app.Problem('An active offline contract already exists.',409)
            sid=app.uid();end=app.now()+(365 if price['interval']=='annual' else 30)*86400
            c.execute('INSERT INTO subscriptions(id,tenant_id,plan_id,price_id,status,mode,current_period_end,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',(sid,tenant,price['plan_id'],price['id'],'ACTIVE','offline',end,app.now(),app.now()))
            c.execute('INSERT INTO payments VALUES(?,?,?,?,?,?,?,?,?,?)',(app.uid(),tenant,sid,'offline',reference,price['amount_paise'],'INR','captured',app.now(),reference));audit(app,c,aid,'billing.offline_payment_recorded',tenant,reason,{'reference':reference,'amount_paise':price['amount_paise']});return True,{'ok':True}
    raise app.Problem('Not found.',404)
