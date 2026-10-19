"""HUDDLE membership-scoped authenticator and Google OIDC authorization-code flows."""
import base64,hashlib,hmac,io,json,os,secrets,struct,time,urllib.parse,urllib.request
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives import hashes

def totp(secret,stamp=None,digits=6):
    counter=int(time.time() if stamp is None else stamp)//30
    raw=hmac.new(base64.b32decode(secret+'='*((-len(secret))%8)),struct.pack('>Q',counter),hashlib.sha1).digest();offset=raw[-1]&15
    return str((struct.unpack('>I',raw[offset:offset+4])[0]&0x7fffffff)%(10**digits)).zfill(digits)

def key(app):
    value=os.environ.get('HUDDLE_ENCRYPTION_KEY')
    if value:
        try:raw=base64.urlsafe_b64decode(value)
        except ValueError:raise app.Problem('Invalid server encryption key.',503)
        if len(raw)!=32:raise app.Problem('Use a 32-byte base64 server encryption key.',503)
        return raw
    if os.environ.get('VERCEL'):raise app.Problem('Server encryption key unavailable.',503)
    path=app.DATA/'.security-key'
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(secrets.token_bytes(32))
    except FileExistsError:pass
    raw=path.read_bytes()
    if len(raw)!=32:raise app.Problem('Server encryption key unavailable.',503)
    return raw

def encrypt(app,tenant,user,value):
    nonce=secrets.token_bytes(12);raw=AESGCM(key(app)).encrypt(nonce,value.encode(),(tenant+':'+user).encode());return base64.urlsafe_b64encode(nonce+raw).decode()
def decrypt(app,tenant,user,value):
    raw=base64.urlsafe_b64decode(value);return AESGCM(key(app)).decrypt(raw[:12],raw[12:],(tenant+':'+user).encode()).decode()
def setting(c,tenant,user):return c.execute('SELECT * FROM user_security WHERE tenant_id=? AND user_id=?',(tenant,user)).fetchone()
def enabled(c,tenant,user):
    s=setting(c,tenant,user);return bool(s and s['enabled'])
def verify(app,c,tenant,user,code):
    s=setting(c,tenant,user)
    if not s or not s['enabled']:return False
    code=str(code).strip()
    if len(code)==6 and code.isdigit():
        secret=decrypt(app,tenant,user,s['secret'])
        for offset in (-1,0,1):
            counter=app.now()//30+offset
            if counter>s['last_counter'] and hmac.compare_digest(totp(secret,counter*30),code):
                c.execute('UPDATE user_security SET last_counter=? WHERE tenant_id=? AND user_id=?',(counter,tenant,user));return True
    digest=hashlib.sha256(code.replace('-','').upper().encode()).hexdigest();recovery=json.loads(s['recovery_hashes'])
    for item in recovery:
        if hmac.compare_digest(digest,item):
            recovery.remove(item);c.execute('UPDATE user_security SET recovery_hashes=? WHERE tenant_id=? AND user_id=?',(json.dumps(recovery),tenant,user));return True
    return False

def challenge(app,c,member,kind='login',data=None):
    token=secrets.token_urlsafe(32);c.execute('DELETE FROM auth_challenges WHERE expires<?',(app.now(),))
    c.execute('INSERT INTO auth_challenges VALUES(?,?,?,?,?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),member['tenant_id'],member['id'],member['account_id'],kind,json.dumps(data or {}),app.now()+300,0,0))
    return {'mfa_required':True,'challenge':token,'expires_in':300,'kind':kind}
def session_valid(app,c,h,actor):
    if not enabled(c,actor['tenant_id'],actor['id']):return
    s=c.execute('SELECT mfa_tenant FROM sessions WHERE token_hash=?',(h.token_hash(),)).fetchone()
    if not s or s['mfa_tenant']!=actor['tenant_id']:raise app.Problem('Verify your authenticator to sign in.',401)
def recent(app,c,h,actor):
    if not enabled(c,actor['tenant_id'],actor['id']):return True
    s=c.execute('SELECT mfa_at,mfa_tenant FROM sessions WHERE token_hash=?',(h.token_hash(),)).fetchone()
    return bool(s and s['mfa_tenant']==actor['tenant_id'] and s['mfa_at']>app.now()-600)
def reauthenticated(app,c,h,actor,password):
    row=c.execute('SELECT password_hash FROM accounts WHERE id=?',(actor['account_id'],)).fetchone()
    if app.password_matches(str(password or ''),row[0]):return True
    google=c.execute("SELECT 1 FROM oauth_identities WHERE provider='google' AND account_id=?",(actor['account_id'],)).fetchone()
    session=c.execute('SELECT authenticated_at FROM sessions WHERE token_hash=?',(h.token_hash(),)).fetchone()
    return bool(google and session and session[0]>app.now()-300)
def fresh(c,h,tenant,stamp):c.execute('UPDATE sessions SET mfa_tenant=?,mfa_at=? WHERE token_hash=?',(tenant,stamp,h.token_hash()))
def app_origin(app):return os.environ.get('HUDDLE_APP_ORIGIN',app.base_url()).rstrip('/')
def redirect_uri(app):return app_origin(app)+'/api/auth/google/callback'
def google_configured():return bool(os.environ.get('GOOGLE_CLIENT_ID') and os.environ.get('GOOGLE_CLIENT_SECRET'))
_jwks=None
_jwks_until=0

def verify_google(token,audience,nonce):
    """Verify Google's RS256 JWT using its HTTPS JWKS; no tokeninfo/debug endpoint."""
    global _jwks,_jwks_until
    def decode(v):return base64.urlsafe_b64decode(v+'='*((-len(v))%4))
    parts=token.split('.')
    if len(parts)!=3:raise ValueError('Invalid identity token')
    header=json.loads(decode(parts[0]));claims=json.loads(decode(parts[1]))
    if header.get('alg')!='RS256' or not isinstance(header.get('kid'),str):raise ValueError('Unsupported signature')
    if not _jwks or time.time()>_jwks_until or not any(k.get('kid')==header['kid'] for k in _jwks):
        with urllib.request.urlopen('https://www.googleapis.com/oauth2/v3/certs',timeout=10) as r:_jwks=json.load(r)['keys']
        _jwks_until=time.time()+3600
    k=next((k for k in _jwks if k.get('kid')==header['kid'] and k.get('kty')=='RSA'),None)
    if not k:raise ValueError('Unknown identity key')
    pub=rsa.RSAPublicNumbers(int.from_bytes(decode(k['e']),'big'),int.from_bytes(decode(k['n']),'big')).public_key();pub.verify(decode(parts[2]),(parts[0]+'.'+parts[1]).encode(),padding.PKCS1v15(),hashes.SHA256())
    audiences=claims.get('aud');audiences=audiences if isinstance(audiences,list) else [audiences]
    if audience not in audiences or len(audiences)>1 and claims.get('azp')!=audience:raise ValueError('Wrong audience')
    if claims.get('iss') not in ('https://accounts.google.com','accounts.google.com') or claims.get('nonce')!=nonce or not claims.get('sub'):raise ValueError('Wrong identity context')
    if float(claims.get('exp',0))<=time.time() or float(claims.get('iat',0))>time.time()+60 or claims.get('email_verified') is not True:raise ValueError('Expired or unverified identity')
    return claims

def handle(app,h,c,method,path):
    if path=='/api/auth/google/start' and method=='GET':
        if not google_configured():h.send(503,{'error':'Google sign-in needs server credentials.','status':'configuration_required'});return True,None
        state=secrets.token_urlsafe(32);browser=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48);nonce=secrets.token_urlsafe(32)
        context={k:app.text(h.query().get(k,[''])[0],80) for k in ('handle','theme')}
        c.execute('DELETE FROM oauth_states WHERE expires<?',(app.now(),));c.execute('INSERT INTO oauth_states VALUES(?,?,?,?,?,?,?)',(hashlib.sha256(state.encode()).hexdigest(),verifier,nonce,hashlib.sha256(browser.encode()).hexdigest(),app.now()+300,0,json.dumps(context)))
        params={'client_id':os.environ['GOOGLE_CLIENT_ID'],'redirect_uri':redirect_uri(app),'response_type':'code','scope':'openid email profile','state':state,'nonce':nonce,'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),'code_challenge_method':'S256','prompt':'select_account'}
        cookie='huddle_oauth='+browser+'; HttpOnly; SameSite=Lax; Path=/api/auth/google; Max-Age=300'+('; Secure' if app_origin(app).startswith('https://') else '')
        h.send(302,b'','text/plain',{'Location':'https://accounts.google.com/o/oauth2/v2/auth?'+urllib.parse.urlencode(params),'Set-Cookie':cookie});return True,None
    if path=='/api/auth/google/callback' and method=='GET':
        from http.cookies import SimpleCookie
        if not google_configured():raise app.Problem('Google sign-in is not configured.',503)
        h.limited('oauth',30);q=h.query();state=q.get('state',[''])[0];r=c.execute('SELECT * FROM oauth_states WHERE state_hash=?',(hashlib.sha256(state.encode()).hexdigest(),)).fetchone();cookie=SimpleCookie(h.headers.get('Cookie',''));browser=cookie['huddle_oauth'].value if 'huddle_oauth' in cookie else ''
        if not r or r['used'] or r['expires']<app.now() or not hmac.compare_digest(r['browser_hash'],hashlib.sha256(browser.encode()).hexdigest()):raise app.Problem('Sign-in expired. Start again.',403)
        c.execute('UPDATE oauth_states SET used=1 WHERE state_hash=?',(r['state_hash'],))
        try:
            payload=urllib.parse.urlencode({'code':q.get('code',[''])[0],'client_id':os.environ['GOOGLE_CLIENT_ID'],'client_secret':os.environ['GOOGLE_CLIENT_SECRET'],'redirect_uri':redirect_uri(app),'grant_type':'authorization_code','code_verifier':r['verifier']}).encode()
            with urllib.request.urlopen(urllib.request.Request('https://oauth2.googleapis.com/token',data=payload),timeout=15) as response:tokens=json.load(response)
            claims=verify_google(tokens['id_token'],os.environ['GOOGLE_CLIENT_ID'],r['nonce'])
        except Exception:raise app.Problem('Google identity could not be verified. Start again.',403)
        identity=c.execute("SELECT a.* FROM oauth_identities i JOIN accounts a ON a.id=i.account_id WHERE i.provider='google' AND i.subject=? AND a.disabled IS NULL",(claims['sub'],)).fetchone()
        if identity and json.loads(r['context']).get('handle'):raise app.Problem('This account already exists. Sign in to manage your cards; signup claims are for new accounts.',409)
        if not identity:
            # Do not silently link an existing password account by matching email.
            if c.execute('SELECT 1 FROM accounts WHERE email=?',(app.email(claims['email']),)).fetchone():raise app.Problem('This email already has an account. Sign in with your password; Google linking is not enabled.',409)
            aid=app.uid();c.execute('INSERT INTO accounts VALUES(?,?,?,?,?)',(aid,app.email(claims['email']),app.password_hash(secrets.token_urlsafe(48)),app.now(),None));c.execute('INSERT INTO oauth_identities VALUES(?,?,?)',('google',claims['sub'],aid));tenant=app.create_org(c,(app.text(claims.get('name')) or 'My')+' workspace',aid,app.text(claims.get('name')));app.signup_preferences(c,tenant,json.loads(r['context']));identity=c.execute('SELECT * FROM accounts WHERE id=?',(aid,)).fetchone()
        member=c.execute("SELECT u.* FROM users u JOIN organizations o ON o.id=u.tenant_id WHERE u.account_id=? AND u.active=1 AND o.status='active' ORDER BY u.created",(identity['id'],)).fetchone()
        if not member:raise app.Problem('No active organization membership.',403)
        if enabled(c,member['tenant_id'],member['id']):
            pending=challenge(app,c,member);location=('' if app.surfaces.app_host(h) else '/app')+'/login?challenge='+urllib.parse.quote(pending['challenge']);h.send(302,b'','text/plain',{'Location':location});return True,None
        h.send(302,b'','text/plain',{'Location':('' if app.surfaces.app_host(h) else '/app')+'/dashboard','Set-Cookie':h.session(c,identity['id'],member['tenant_id'])});return True,None
    if path=='/api/auth/verify' and method=='POST':
        h.limited('mfa',30);d=h.body();r=c.execute('SELECT * FROM auth_challenges WHERE token_hash=?',(hashlib.sha256(str(d.get('challenge','')).encode()).hexdigest(),)).fetchone()
        if not r or r['used'] or r['attempts']>=6 or r['expires']<app.now():raise app.Problem('Verification expired. Sign in again.',403)
        c.execute('UPDATE auth_challenges SET attempts=attempts+1 WHERE token_hash=?',(r['token_hash'],))
        m=app.scoped(c,'users',r['tenant_id'],r['user_id'])
        if not m['active']:raise app.Problem('Membership unavailable.',403)
        if not verify(app,c,r['tenant_id'],r['user_id'],d.get('code')):
            # Commit the attempt counter even though verification is rejected.
            c.commit();h.send(403,{'error':'Authenticator or recovery code is incorrect.'});return True,None
        c.execute('UPDATE auth_challenges SET used=1 WHERE token_hash=?',(r['token_hash'],));payload=json.loads(r['data'])
        if r['kind']=='login':
            h.send(200,{'ok':True},headers={'Set-Cookie':h.session(c,r['account_id'],r['tenant_id'],verified=True)});return True,None
        actor=h.actor(c)
        if actor['account_id']!=r['account_id'] or payload.get('session')!=h.token_hash():raise app.Problem('Verification belongs to another session.',403)
        if r['kind']=='switch':c.execute('UPDATE sessions SET active_tenant_id=? WHERE token_hash=? AND account_id=?',(r['tenant_id'],h.token_hash(),r['account_id']))
        fresh(c,h,r['tenant_id'],app.now());return True,{'ok':True}
    if not path.startswith('/api/security'):return False,None
    actor=h.actor(c);tenant,user=actor['tenant_id'],actor['id'];s=setting(c,tenant,user)
    if path=='/api/security' and method=='GET':return True,{'enabled':bool(s and s['enabled']),'recovery_remaining':len(json.loads(s['recovery_hashes'])) if s else 0,'recent':recent(app,c,h,actor),'google_configured':google_configured(),'scope':'organization membership'}
    if path=='/api/security/elevate' and method=='POST':
        if not enabled(c,tenant,user):return True,{'ok':True}
        return True,challenge(app,c,{'tenant_id':tenant,'id':user,'account_id':actor['account_id']},'elevate',{'session':h.token_hash()})
    if path=='/api/security/setup' and method=='POST':
        h.limited('security-setup',10);d=h.body();a=c.execute('SELECT password_hash FROM accounts WHERE id=?',(actor['account_id'],)).fetchone()
        if not reauthenticated(app,c,h,actor,d.get('password')):raise app.Problem('Confirm your password, or sign in with Google again, to set up your authenticator.',403)
        if s and s['enabled']:raise app.Problem('Authenticator is already enabled.')
        secret=base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=');enc=encrypt(app,tenant,user,secret)
        c.execute('INSERT INTO user_security(tenant_id,user_id,pending_secret) VALUES(?,?,?) ON CONFLICT(tenant_id,user_id) DO UPDATE SET pending_secret=excluded.pending_secret',(tenant,user,enc))
        label=urllib.parse.quote('HUDDLE:'+app.company(c,tenant)['name']+':'+actor['email'],safe='');uri='otpauth://totp/'+label+'?'+urllib.parse.urlencode({'secret':secret,'issuer':'HUDDLE','algorithm':'SHA1','digits':6,'period':30})
        return True,{'secret':secret,'uri':uri,'qr_url':'/api/security/setup/qr'}
    if path=='/api/security/setup/qr' and method=='GET':
        if not s or not s['pending_secret']:raise app.Problem('Start authenticator setup first.',404)
        secret=decrypt(app,tenant,user,s['pending_secret']);uri='otpauth://totp/'+urllib.parse.quote('HUDDLE:'+actor['email'],safe='')+'?'+urllib.parse.urlencode({'secret':secret,'issuer':'HUDDLE','algorithm':'SHA1','digits':6,'period':30});svg=h.qr_svg(c,tenant,uri,{})
        if h.query().get('format',[''])[0]=='png':h.send(200,h.qr_png(svg),'image/png')
        else:h.send(200,svg,'image/svg+xml')
        return True,None
    if path=='/api/security/confirm' and method=='POST':
        h.limited('setup-mfa',20);d=h.body()
        if not s or not s['pending_secret']:raise app.Problem('Start authenticator setup first.')
        secret=decrypt(app,tenant,user,s['pending_secret']);code=str(d.get('code',''));counter=None
        for offset in (-1,0,1):
            n=app.now()//30+offset
            if hmac.compare_digest(totp(secret,n*30),code):counter=n
        if counter is None:raise app.Problem('Authenticator code is incorrect.',403)
        recovery=[secrets.token_hex(8).upper() for _ in range(8)];digests=[hashlib.sha256(v.encode()).hexdigest() for v in recovery]
        c.execute('UPDATE user_security SET secret=pending_secret,pending_secret=NULL,enabled=1,recovery_hashes=?,last_counter=? WHERE tenant_id=? AND user_id=?',(json.dumps(digests),counter,tenant,user));fresh(c,h,tenant,app.now());app.audit(c,actor,'security.totp_enabled',user);return True,{'ok':True,'recovery_codes':recovery}
    if path=='/api/security/disable' and method=='POST':
        h.limited('security-disable',10);d=h.body();a=c.execute('SELECT password_hash FROM accounts WHERE id=?',(actor['account_id'],)).fetchone()
        if not reauthenticated(app,c,h,actor,d.get('password')) or not verify(app,c,tenant,user,d.get('code')):raise app.Problem('Confirm password and a fresh authenticator/recovery code.',403)
        c.execute('DELETE FROM user_security WHERE tenant_id=? AND user_id=?',(tenant,user));c.execute('DELETE FROM sessions WHERE account_id=? AND active_tenant_id=? AND token_hash!=?',(actor['account_id'],tenant,h.token_hash()));app.audit(c,actor,'security.totp_disabled',user);return True,{'ok':True}
    raise app.Problem('Route not found.',404)
