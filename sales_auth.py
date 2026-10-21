"""Internal sales credentials and sessions, separate from customer passwords/memberships."""
import hashlib,secrets,re
from http.cookies import SimpleCookie
import platform_admin
COOKIE='huddle_sales'
DUMMY='00000000000000000000000000000000:'+('0'*64)

def token(h):
    try:value=SimpleCookie(h.headers.get('Cookie',''))[COOKIE].value
    except (KeyError,ValueError):return None
    return hashlib.sha256(value.encode()).hexdigest()

def cookie(app,value='',age=0):
    return COOKIE+'='+value+'; HttpOnly; SameSite=Strict; Path=/; Max-Age='+str(age)+('; Secure' if app.base_url().startswith('https://') else '')

def identity(app,h,c):
    key=token(h)
    if not key:return None
    row=c.execute('SELECT a.id,a.email,s.name,s.must_change,s.version FROM sales_staff_sessions t JOIN sales_staff_credentials s ON s.account_id=t.account_id AND s.version=t.credential_version JOIN sales_agent_grants g ON g.account_id=t.account_id JOIN accounts a ON a.id=t.account_id WHERE t.token_hash=? AND t.expires>? AND g.active=1 AND a.disabled IS NULL',(key,app.now())).fetchone()
    if not row:raise app.Problem('Please sign in to the sales workspace again.',401)
    return {**dict(row),'manager':False,'auth_kind':'staff'}

def new_session(app,h,c,account,version):
    value=secrets.token_urlsafe(32);c.execute('DELETE FROM sales_staff_sessions WHERE expires<?',(app.now(),))
    c.execute('INSERT INTO sales_staff_sessions VALUES(?,?,?,?)',(hashlib.sha256(value.encode()).hexdigest(),account,version,app.now()+8*3600))
    return cookie(app,value,8*3600)

def password(app,d):
    value=d.get('password')
    if not isinstance(value,str) or not 12<=len(value)<=256:raise app.Problem('Use a staff password between 12 and 256 characters.')
    if value!=d.get('confirm_password'):raise app.Problem('Passwords do not match.')
    return app.password_hash(value)

def instructions(app,account,name):return {'email':account['email'],'name':name,'login_url':app.base_url()+'/sales/login','delivery':'copy','email_enabled':False}

def public_routes(app,h,c,method,path):
    if path=='/sales/login' and method=='GET':
        h.send(200,(app.ROOT/'static/sales-login.html').read_bytes(),'text/html; charset=utf-8');return True,None
    if path=='/api/sales/auth/login' and method=='POST':
        h.limited('staff-login',30);d=h.body();address=app.text(d.get('email'),255).lower();h.limited('staff-login-'+hashlib.sha256(address.encode()).hexdigest(),10)
        row=c.execute('SELECT a.id,a.email,s.password_hash,s.version,s.must_change FROM accounts a JOIN sales_staff_credentials s ON s.account_id=a.id JOIN sales_agent_grants g ON g.account_id=a.id WHERE a.email=? AND a.disabled IS NULL AND g.active=1',(address,)).fetchone()
        valid=app.password_matches(str(d.get('password',''))[:257],row['password_hash'] if row else DUMMY)
        if not row or not valid:raise app.Problem('Email or password is incorrect, or sales access is unavailable.',401)
        platform_admin.audit(app,c,row['id'],'sales.staff_login',reason='Internal sales sign-in')
        h.send(200,{'ok':True,'must_change':bool(row['must_change'])},headers={'Set-Cookie':new_session(app,h,c,row['id'],row['version'])});return True,None
    if path=='/api/sales/auth/logout' and method=='POST':
        c.execute('DELETE FROM sales_staff_sessions WHERE token_hash=?',(token(h) or '',))
        h.send(200,{'ok':True},headers={'Set-Cookie':cookie(app)});return True,None
    return False,None

def manager_routes(app,h,c,actor,method,path):
    if path=='/api/sales/team/provision' and method=='POST':
        if not actor['manager']:raise app.Problem('Not found.',404)
        h.limited('staff-provision',20);d=h.body();reason=app.text(d.get('reason'),1000);name=app.text(d.get('name'),150);address=app.email(d.get('email'))
        if len(reason)<10 or not name or type(d.get('must_change',True))!=bool:raise app.Problem('Enter the colleague’s name, a reason and valid password-change preference.')
        if d.get('delivery','copy')!='copy':raise app.Problem('Email delivery is not enabled yet. Choose copy instructions.')
        hashed=password(app,d);account=c.execute('SELECT id,email,disabled FROM accounts WHERE email=?',(address,)).fetchone()
        if account and (account['disabled'] is not None or c.execute('SELECT 1 FROM platform_admin_grants WHERE account_id=?',(account['id'],)).fetchone()):raise app.Problem('This account cannot be provisioned as a sales colleague.',409)
        if account and c.execute('SELECT 1 FROM sales_staff_credentials WHERE account_id=?',(account['id'],)).fetchone():raise app.Problem('This sales login already exists. Use Reset password or update access.',409)
        if not account:
            account={'id':app.uid(),'email':address}
            # An identity record supports assignment/audit foreign keys; no tenant or customer password is created.
            c.execute('INSERT INTO accounts VALUES(?,?,?,?,?)',(account['id'],address,app.password_hash(secrets.token_urlsafe(48)),app.now(),None))
        c.execute('INSERT INTO sales_staff_credentials VALUES(?,?,?,?,?,?,?)',(account['id'],name,hashed,int(d.get('must_change',True)),1,app.now(),app.now()))
        c.execute('INSERT INTO sales_agent_grants VALUES(?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET active=excluded.active,granted_by=excluded.granted_by',(account['id'],1,app.now(),actor['id']))
        platform_admin.audit(app,c,actor['id'],'sales.staff_created',reason=reason,details={'account':account['id'],'email':address})
        return True,{'ok':True,**instructions(app,account,name)}
    match=re.fullmatch(r'/api/sales/team/([a-zA-Z0-9-]+)/password',path)
    if match and method=='POST':
        if not actor['manager']:raise app.Problem('Not found.',404)
        h.limited('staff-reset',20);d=h.body();reason=app.text(d.get('reason'),1000);aid=match[1]
        row=c.execute('SELECT s.*,a.email FROM sales_staff_credentials s JOIN accounts a ON a.id=s.account_id WHERE s.account_id=?',(aid,)).fetchone()
        if not row:raise app.Problem('Internal sales login not found.',404)
        if c.execute('SELECT 1 FROM platform_admin_grants WHERE account_id=?',(aid,)).fetchone():raise app.Problem('Platform accounts cannot be reset here.',403)
        if len(reason)<10 or type(d.get('must_change',True))!=bool:raise app.Problem('Enter a reason and valid password-change preference.')
        if type(d.get('version'))!=int or d['version']!=row['version']:raise app.Problem('The sales login changed. Reload before resetting.',409)
        hashed=password(app,d)
        changed=c.execute('UPDATE sales_staff_credentials SET password_hash=?,must_change=?,version=version+1,updated=? WHERE account_id=? AND version=?',(hashed,int(d.get('must_change',True)),app.now(),aid,row['version']))
        if changed.rowcount!=1:raise app.Problem('The sales login changed. Reload before resetting.',409)
        c.execute('DELETE FROM sales_staff_sessions WHERE account_id=?',(aid,))
        platform_admin.audit(app,c,actor['id'],'sales.staff_password_reset',reason=reason,details={'account':aid})
        return True,{'ok':True,**instructions(app,{'email':row['email']},row['name'])}
    return False,None

def change_password(app,h,c,actor,method,path):
    if path!='/api/sales/auth/password' or method!='POST':return False,None
    if actor.get('auth_kind')!='staff':raise app.Problem('Sign in using your internal sales login to change its password.',403)
    h.limited('staff-password',10);d=h.body();row=c.execute('SELECT password_hash,version FROM sales_staff_credentials WHERE account_id=?',(actor['id'],)).fetchone()
    if not app.password_matches(str(d.get('current',''))[:257],row['password_hash']):raise app.Problem('Current sales password is incorrect.',403)
    if d.get('password')==d.get('current'):raise app.Problem('Choose a different password.')
    hashed=password(app,d)
    changed=c.execute('UPDATE sales_staff_credentials SET password_hash=?,must_change=0,version=version+1,updated=? WHERE account_id=? AND version=?',(hashed,app.now(),actor['id'],row['version']))
    if changed.rowcount!=1:raise app.Problem('The sales login changed. Sign in again.',409)
    c.execute('DELETE FROM sales_staff_sessions WHERE account_id=?',(actor['id'],))
    platform_admin.audit(app,c,actor['id'],'sales.staff_password_changed',reason='Sales colleague changed their password')
    h.send(200,{'ok':True},headers={'Set-Cookie':cookie(app)});return True,None
