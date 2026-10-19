"""Routing, recipient bundle, RFC TOTP, challenge and OIDC security tests."""
import base64,hashlib,http.client,json,os,secrets,time,unittest,urllib.parse
from unittest.mock import patch
import test_multitenant as fixtures
app=fixtures.app
import security
class SurfaceSecurityTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.TenancyTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.TenancyTests.tearDownClass.__func__)
    call=classmethod(fixtures.TenancyTests.call.__func__)
    def setUp(self):
        app.RATE.clear();suffix=secrets.token_hex(5);self.address='security.'+suffix+'@example.com';self.password='SecurityPass!2026'
        r=self.call('/api/register','POST',{'email':self.address,'password':self.password,'name':'Security Owner','organization':'Security '+suffix});self.cookie=r[2];self.state=self.call('/api/state',cookie=self.cookie)[1];self.tenant=self.state['organization']['id'];self.member=self.state['user']['id']
    def raw(self,path,host='127.0.0.1',cookie=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.http.server_port);headers={'Host':host}
        if cookie:headers['Cookie']=cookie
        conn.request('GET',path,headers=headers);r=conn.getresponse();data=r.read();headers=dict(r.getheaders());status=r.status;conn.close();return status,data,headers
    def enroll(self):
        r=self.call('/api/security/setup','POST',{'password':self.password},self.cookie);self.assertEqual(r[0],200,r);secret=r[1]['secret']
        r=self.call('/api/security/confirm','POST',{'code':security.totp(secret)},self.cookie);self.assertEqual(r[0],200,r);return secret,r[1]['recovery_codes']
    def test_routing_zones_and_no_open_redirect(self):
        for path in ['/','/pricing','/templates','/features','/enterprise']:
            status,body,_=self.raw(path);self.assertEqual(status,200);self.assertIn(b'marketing.js',body);self.assertNotIn(b'src="/static/app.js"',body)
        status,_,headers=self.raw('/app/dashboard/cards');self.assertEqual(status,302);self.assertTrue(headers['Location'].startswith('/app/login?next='))
        self.assertEqual(self.raw('/app/login',cookie=self.cookie)[2]['Location'],'/app/dashboard');self.assertEqual(self.raw('/app/login?next=https://attacker.example',cookie=self.cookie)[2]['Location'],'/app/dashboard');self.assertEqual(self.raw('/app/login')[0],200);self.assertEqual(self.raw('/login','app.huddle.co.in')[0],200)
        self.assertEqual(self.raw('/dashboard','app.huddle.co.in')[2]['Location'],'/login?next=/dashboard')
        self.assertIn(b'/static/app.js',self.raw('/app/dashboard/cards',cookie=self.cookie)[1]);self.assertEqual(self.raw('/app/unknown')[0],404);self.assertEqual(self.raw('/not-a-page')[0],404);self.assertNotIn(b'/static/app.js',self.raw('/not-a-page')[1])
    def test_public_recipient_is_small_and_tenant_independent(self):
        slug=self.state['user']['slug'];status,body,_=self.raw('/c/'+slug);self.assertEqual(status,200);self.assertIn(b'public-card.js',body);self.assertNotIn(b'/static/app.js',body)
        self.assertIn(b'public-card.js',self.raw('/'+slug,'c.huddle.co.in')[1]);self.assertEqual(self.call('/api/card/'+slug)[0],200)
        status,body,headers=self.raw('/manifest/'+slug+'.webmanifest');self.assertEqual(status,200);self.assertEqual(json.loads(body)['start_url'],'/c/'+slug)
        self.assertEqual(json.loads(self.raw('/manifest/'+slug+'.webmanifest','c.huddle.co.in')[1])['scope'],'/')
        self.assertEqual(self.raw('/sw.js','c.huddle.co.in')[2]['Service-Worker-Allowed'],'/')
        sw=self.raw('/c/sw.js')[1];self.assertIn(b'Never cache API',sw);self.assertNotIn(b"cache.add('/api",sw)
    def test_handle_claim_and_theme_survive_signup(self):
        handle='claimed-'+secrets.token_hex(4);self.assertTrue(self.call('/api/public/handle?handle='+handle)[1]['available'])
        r=self.call('/api/register','POST',{'email':'claim.'+secrets.token_hex(5)+'@example.com','password':self.password,'name':'Claimant','organization':'Claim org','handle':handle,'theme':'sunset'});self.assertEqual(r[0],200,r)
        state=self.call('/api/state',cookie=r[2])[1];self.assertEqual(state['user']['slug'],handle);self.assertEqual(self.call('/api/card/'+handle)[1]['template']['layout'],'sunset');self.assertFalse(self.call('/api/public/handle?handle='+handle)[1]['available'])
        self.assertFalse(self.call('/api/public/handle?handle=dashboard')[1]['available'])
    def test_rfc6238_vectors(self):
        secret=base64.b32encode(b'12345678901234567890').decode().rstrip('=')
        self.assertEqual(security.totp(secret,59,8),'94287082');self.assertEqual(security.totp(secret,1111111109,8),'07081804');self.assertEqual(security.totp(secret,20000000000,8),'65353130')
    def test_enrollment_encryption_and_single_use_recovery(self):
        secret,codes=self.enroll()
        with app.connection() as c:
            row=c.execute('SELECT * FROM user_security WHERE tenant_id=? AND user_id=?',(self.tenant,self.member)).fetchone();self.assertNotIn(secret,row['secret']);self.assertNotIn(codes[0],row['recovery_hashes']);self.assertFalse(row['pending_secret'])
        self.call('/api/logout','POST',{},self.cookie);r=self.call('/api/login','POST',{'email':self.address,'password':self.password});self.assertTrue(r[1]['mfa_required']);self.assertFalse(r[2]);self.assertEqual(self.call('/api/state')[0],401)
        verified=self.call('/api/auth/verify','POST',{'challenge':r[1]['challenge'],'code':codes[0]});self.assertEqual(verified[0],200,verified);self.assertEqual(self.call('/api/state',cookie=verified[2])[0],200)
        self.assertEqual(self.call('/api/auth/verify','POST',{'challenge':r[1]['challenge'],'code':codes[1]})[0],403)
        r=self.call('/api/login','POST',{'email':self.address,'password':self.password});self.assertEqual(self.call('/api/auth/verify','POST',{'challenge':r[1]['challenge'],'code':codes[0]})[0],403)
    def test_totp_replay_and_challenge_attempt_budget(self):
        secret,_=self.enroll();r=self.call('/api/login','POST',{'email':self.address,'password':self.password});token=r[1]['challenge']
        for _ in range(6):self.assertEqual(self.call('/api/auth/verify','POST',{'challenge':token,'code':'bad'})[0],403)
        with app.connection() as c:self.assertEqual(c.execute('SELECT attempts FROM auth_challenges WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()[0],6)
        self.assertEqual(self.call('/api/auth/verify','POST',{'challenge':token,'code':security.totp(secret)})[0],403)
        with app.connection() as c:self.assertFalse(security.verify(app,c,self.tenant,self.member,security.totp(secret)))
    def test_sensitive_actions_require_recent_mfa(self):
        _,codes=self.enroll()
        with app.connection() as c:c.execute('UPDATE sessions SET mfa_at=0 WHERE account_id=(SELECT account_id FROM users WHERE tenant_id=? AND id=?)',(self.tenant,self.member))
        r=self.call('/api/company','PUT',{'tagline':'should wait'},self.cookie);self.assertEqual(r[0],403);self.assertTrue(r[1]['elevation_required'])
        challenge=self.call('/api/security/elevate','POST',{},self.cookie)[1];r=self.call('/api/auth/verify','POST',{'challenge':challenge['challenge'],'code':codes[0]},self.cookie);self.assertEqual(r[0],200,r);self.assertEqual(self.call('/api/company','PUT',{'tagline':'verified'},self.cookie)[0],200)
    def test_switch_requires_target_org_mfa_and_cannot_bypass_password(self):
        _,codes=self.enroll();second=self.call('/api/organizations','POST',{'name':'Unprotected second'},self.cookie)[1]['id'];self.assertEqual(self.call('/api/organizations/switch','POST',{'tenant_id':second},self.cookie)[0],200)
        r=self.call('/api/password','POST',{'current':self.password,'password':'ChangedPass!2026'},self.cookie);self.assertEqual(r[0],403)
        r=self.call('/api/organizations/switch','POST',{'tenant_id':self.tenant},self.cookie);self.assertTrue(r[1]['mfa_required']);self.assertEqual(self.call('/api/state',cookie=self.cookie)[1]['organization']['id'],second)
        r=self.call('/api/auth/verify','POST',{'challenge':r[1]['challenge'],'code':codes[0]},self.cookie);self.assertEqual(r[0],200,r);self.assertEqual(self.call('/api/state',cookie=self.cookie)[1]['organization']['id'],self.tenant)
    def test_cross_tenant_security_and_share_exports(self):
        secret,codes=self.enroll();self.assertFalse(self.call('/api/security',cookie=self.b)[1]['enabled']);card=self.state['cards'][0]
        self.assertEqual(self.call('/api/cards/'+card['id']+'/signature',cookie=self.b)[0],404)
        status,body,_=self.call('/api/cards/'+card['id']+'/signature',cookie=self.cookie);self.assertEqual(status,200);self.assertIn(b'Connect with me',body)
        self.assertTrue(self.call('/api/cards/'+card['id']+'/background.png',cookie=self.cookie)[1].startswith(b'\x89PNG'))
        self.assertEqual(self.call('/api/security/disable','POST',{'password':self.password,'code':codes[0]},self.cookie)[0],200)
    def test_google_unconfigured_and_state_browser_binding(self):
        with patch.dict(os.environ,{'GOOGLE_CLIENT_ID':'','GOOGLE_CLIENT_SECRET':''}):self.assertEqual(self.raw('/api/auth/google/start')[0],503)
        with patch.dict(os.environ,{'GOOGLE_CLIENT_ID':'fixture-client','GOOGLE_CLIENT_SECRET':'fixture-secret'}):
            status,_,headers=self.raw('/api/auth/google/start');self.assertEqual(status,302);q=urllib.parse.parse_qs(urllib.parse.urlsplit(headers['Location']).query);self.assertEqual(q['code_challenge_method'],['S256']);self.assertIn('nonce',q)
            self.assertEqual(self.raw('/api/auth/google/callback?state='+q['state'][0]+'&code=fixture-code')[0],403)
    def test_google_callback_mocked_exchange_and_no_implicit_linking(self):
        import io
        with patch.dict(os.environ,{'GOOGLE_CLIENT_ID':'fixture-client','GOOGLE_CLIENT_SECRET':'fixture-secret'}):
            def callback(address,subject,query=""):
                _,_,headers=self.raw('/api/auth/google/start'+query);q=urllib.parse.parse_qs(urllib.parse.urlsplit(headers['Location']).query);cookie=headers['Set-Cookie'].split(';')[0]
                with patch.object(security.urllib.request,'urlopen',return_value=io.BytesIO(b'{"id_token":"fixture"}')),patch.object(security,'verify_google',return_value={'sub':subject,'email':address,'email_verified':True,'name':'Google Fixture'}):return self.raw('/api/auth/google/callback?state='+q['state'][0]+'&code=fixture-code',cookie=cookie)
            status,_,_=callback(self.address,'existing-password-account');self.assertEqual(status,409)
            address='google.'+secrets.token_hex(5)+'@example.com';handle='google-'+secrets.token_hex(4);status,_,headers=callback(address,'google-sub-'+address,'?handle='+handle+'&theme=mint');self.assertEqual(self.call('/api/card/'+handle)[1]['template']['layout'],'mint');self.assertEqual(status,302);self.assertEqual(headers['Location'],'/app/dashboard');self.assertIn('hello_session=',headers['Set-Cookie'])
    def test_recovery_does_not_depend_on_decrypting_the_totp_secret(self):
        _,codes=self.enroll()
        with patch.dict(os.environ,{'HUDDLE_ENCRYPTION_KEY':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}):
            with app.connection() as c:self.assertTrue(security.verify(app,c,self.tenant,self.member,codes[0]))
    def test_signed_in_account_can_accept_invitation_without_replacing_password(self):
        invitation=self.call('/api/invitations','POST',{'name':'Verified invitee','email':self.address,'division_id':self.sa['divisions'][0]['id']},self.a)[1]['id']
        state=self.call('/api/state',cookie=self.a)[1];url=next(i['url'] for i in state['invitations'] if i['id']==invitation);token=url.split('token=')[1]
        self.assertTrue(self.call('/api/invitation?token='+token,cookie=self.cookie)[1]['signed_in'])
        self.assertEqual(self.call('/api/accept','POST',{'token':token},self.cookie)[0],200)
        self.assertEqual(self.call('/api/login','POST',{'email':self.address,'password':self.password})[0],200)
    def test_oidc_signature_and_claim_validation(self):
        from cryptography.hazmat.primitives.asymmetric import rsa,padding
        from cryptography.hazmat.primitives import hashes
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048);public=key.public_key().public_numbers();enc=lambda b:base64.urlsafe_b64encode(b).decode().rstrip('=')
        jwk={'kid':'fixture','kty':'RSA','n':enc(public.n.to_bytes(256,'big')),'e':enc(public.e.to_bytes(3,'big'))};claims={'iss':'https://accounts.google.com','aud':'fixture-client','sub':'fixture-user','nonce':'nonce','email':'fixture@example.com','email_verified':True,'iat':int(time.time()),'exp':int(time.time())+300}
        def token(data):
            header=enc(json.dumps({'alg':'RS256','kid':'fixture'}).encode());body=enc(json.dumps(data).encode());signed=header+'.'+body;return signed+'.'+enc(key.sign(signed.encode(),padding.PKCS1v15(),hashes.SHA256()))
        with patch.object(security,'_jwks',[jwk]),patch.object(security,'_jwks_until',time.time()+600):
            self.assertEqual(security.verify_google(token(claims),'fixture-client','nonce')['sub'],'fixture-user')
            for updates in [{'aud':'other'},{'nonce':'other'},{'exp':0},{'email_verified':False},{'iss':'https://attacker.example'}]:
                with self.assertRaises(ValueError):security.verify_google(token({**claims,**updates}),'fixture-client','nonce')
            with self.assertRaises(Exception):security.verify_google(token(claims)[:-5]+'AAAAA','fixture-client','nonce')

if __name__=='__main__':unittest.main()
