"""Billing and operator invariants through the actual WSGI API; no real payments."""
import base64,hashlib,hmac,io,json,os,secrets,sqlite3,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as app,billing,security
from app import app as web

class MonetizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'PUBLIC_BASE_URL':'http://localhost','HUDDLE_DATA_DIR':self.tmp.name,'RAZORPAY_MODE':'test'},clear=True);self.env.start()
        self.old=app.DATA,app.DB,app.DEMO;app.DATA=Path(self.tmp.name);app.DB=app.DATA/'huddle.sqlite3';app.DEMO=False;app.RATE.clear()
        import migrate
        migrate.apply(app);self.client=web.test_client();self.other=web.test_client()
        self.email='owner-'+secrets.token_hex(5)+'@example.com';self.password='BillingTest!2026'
        self.register(self.client,self.email);self.state=self.client.get('/api/state').json;self.tenant=self.state['organization']['id'];self.card=self.state['cards'][0]['id'];self.aid=self.account(self.email)
        self.register(self.other,'other-'+secrets.token_hex(5)+'@example.com');self.otherstate=self.other.get('/api/state').json
    def tearDown(self):app.DATA,app.DB,app.DEMO=self.old;self.env.stop();self.tmp.cleanup()
    def register(self,client,address):
        r=client.post('/api/register',json={'email':address,'password':self.password,'name':'Owner','organization':'Company'});self.assertEqual(r.status_code,200,r.json)
    def account(self,address):
        with app.connection() as c:return c.execute('SELECT id FROM accounts WHERE email=?',(address,)).fetchone()[0]
    def grant(self,plan='pro',expires=None,tenant=None):
        with app.connection() as c:c.execute('INSERT INTO entitlement_overrides VALUES(?,?,?,?,?,?,?,?,?)',(app.uid(),tenant or self.tenant,plan,'{}','Test access grant','test',app.now(),expires or app.now()+86400,None))
    def platform(self):
        with app.connection() as c:c.execute('INSERT INTO platform_admin_grants VALUES(?,?,?,?)',(self.aid,app.now(),'test','Provisioned test operator'))
        r=self.client.post('/api/platform/mfa/setup',json={'password':self.password});self.assertEqual(r.status_code,200,r.json);secret=r.json['secret']
        r=self.client.post('/api/platform/mfa/confirm',json={'password':self.password,'code':security.totp(secret)});self.assertEqual(r.status_code,200,r.json);return secret
    def gateway_env(self):
        os.environ.update(RAZORPAY_KEY_ID='rzp_test_fixture',RAZORPAY_KEY_SECRET='fixture-secret',RAZORPAY_WEBHOOK_SECRET='fixture-webhook',RAZORPAY_PLAN_PRO_MONTHLY='plan_fixture')
    def subscription(self,status='AUTHENTICATED',mode='test',end=0):
        sid=app.uid()
        with app.connection() as c:c.execute('INSERT INTO subscriptions(id,tenant_id,plan_id,price_id,status,mode,provider_subscription_id,current_period_end,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,self.tenant,'pro','pro-monthly',status,mode,'sub_'+sid,end,app.now()+1,app.now()))
        return sid
    def snapshot(self,sid,status='active',end=None):return {'id':'sub_'+sid,'status':status,'plan_id':'plan_fixture','quantity':1,'current_end':end or app.now()+30*86400,'current_start':app.now(),'notes':{'huddle_subscription_id':sid,'huddle_tenant_id':self.tenant},'customer_id':'cus_fixture'}
    def webhook(self,event,eid='fixture-event',signature=True):
        raw=json.dumps(event).encode();sig=hmac.new(b'fixture-webhook',raw,hashlib.sha256).hexdigest() if signature else 'bad'
        return self.client.post('/api/webhooks/razorpay',data=raw,content_type='application/json',headers={'X-Razorpay-Signature':sig,'X-Razorpay-Event-Id':eid})
    def test_free_and_tenant_isolation(self):
        b=self.client.get('/api/billing').json;self.assertEqual(b['plan'],'free');self.assertEqual(b['usage']['cards'],1)
        r=self.client.post('/api/cards',json={'persona':'Second'});self.assertEqual(r.status_code,402);self.assertEqual(r.json['error'],'QUOTA_EXCEEDED')
        self.assertEqual(self.client.post('/api/invitations',json={'name':'Person','email':'person@example.com'}).status_code,402)
        self.assertEqual(self.client.get('/api/leads/export').status_code,402)
        self.assertEqual(self.client.put('/api/cards/'+self.otherstate['cards'][0]['id'],json={'persona':'Hacked'}).status_code,404)
        self.assertEqual(self.client.get('/api/billing?tenant_id='+self.otherstate['organization']['id']).json['plan'],'free')
    def test_public_gates_and_standard_qr(self):
        slug=self.state['user']['slug'];p=self.client.get('/api/card/'+slug).json;self.assertFalse(p['lead_capture']);self.assertTrue(p['show_huddle_branding'])
        self.assertEqual(self.client.post('/api/exchange/'+slug,json={'name':'Visitor','email':'v@example.com','consent':True}).status_code,402)
        self.assertEqual(self.client.put('/api/company',json={'background':'#123456'}).status_code,402)
        self.assertEqual(self.client.get('/qr/'+slug+'.svg').status_code,200)
        self.assertEqual(self.client.post('/api/cards/'+self.card+'/wallet/apple',json={}).status_code,402)
        self.grant();self.assertEqual(self.client.post('/api/cards/'+self.card+'/wallet/apple',json={}).status_code,503)
    def test_reserved_invitations_and_quota_reactivation(self):
        self.grant();r=self.client.post('/api/invitations',json={'name':'Member','email':'member@example.com'});self.assertEqual(r.status_code,200,r.json)
        with app.connection() as c:
            inv=c.execute('SELECT token FROM invitations WHERE tenant_id=?',(self.tenant,)).fetchone()[0]
            c.execute('UPDATE entitlement_overrides SET limits=? WHERE tenant_id=?',(json.dumps({'max_cards':2,'max_seats':2}),self.tenant))
        self.assertEqual(self.client.post('/api/cards',json={'persona':'Reserved'}).status_code,402)
        guest=web.test_client();r=guest.post('/api/accept',json={'token':inv,'password':'MemberTest!2026'});self.assertEqual(r.status_code,200,r.json)
        with app.connection() as c:self.assertEqual(billing.usage(app,c,self.tenant)['reserved_invitations'],0)
        self.assertEqual(self.client.post('/api/invitations',json={'name':'Extra','email':'extra@example.com'}).status_code,402)
    def test_trial_once_and_preserved_downgrade(self):
        self.assertEqual(self.client.post('/api/billing/trial',json={}).status_code,200)
        self.assertEqual(self.client.post('/api/billing/trial',json={}).status_code,409)
        r=self.client.post('/api/cards',json={'persona':'Community'});self.assertEqual(r.status_code,200,r.json);extra=r.json['id']
        with app.connection() as c:c.execute("UPDATE subscriptions SET current_period_end=? WHERE tenant_id=? AND status='TRIALING'",(app.now()-1,self.tenant))
        self.assertEqual(self.client.put('/api/cards/'+self.card,json={'bio':'edit'}).status_code,402)
        self.assertEqual(self.client.get('/api/card/'+self.state['user']['slug']).status_code,200)
        self.assertEqual(self.client.put('/api/cards/'+extra,json={'active':False}).status_code,200)
        self.assertEqual(self.client.put('/api/cards/'+self.card,json={'bio':'edit'}).status_code,200)
        self.assertEqual(self.client.put('/api/cards/'+extra,json={'active':True}).status_code,402)
        with app.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM cards WHERE tenant_id=?',(self.tenant,)).fetchone()[0],2)
    def test_operator_requires_separate_grant_and_mfa(self):
        self.assertEqual(self.client.get('/super-admin').status_code,404);self.assertEqual(self.client.get('/api/platform/overview').status_code,404)
        secret=self.platform();self.assertEqual(self.client.get('/super-admin').status_code,200);self.assertEqual(self.client.get('/api/platform/overview').status_code,200)
        self.assertEqual(self.other.get('/api/platform/overview').status_code,404)
        self.client.post('/api/platform/logout',json={});self.assertEqual(self.client.get('/api/platform/overview').status_code,404)
        self.assertEqual(self.client.post('/api/platform/elevate',json={'password':self.password,'code':security.totp(secret)}).status_code,403)
    def test_grant_suspend_support_and_append_only_audit(self):
        self.platform();target=self.otherstate['organization']['id'];url='/api/platform/tenants/'+target
        r=self.client.post(url+'/override',json={'plan_id':'enterprise','days':30,'limits':{'max_cards':25},'reason':'Offline enterprise access'});self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.other.get('/api/billing').json['entitlements']['max_cards'],25)
        s=self.client.post('/api/platform/support',json={'tenant_id':target,'reason':'Investigate reported issue'}).json
        self.assertTrue(self.client.get('/api/platform/support/'+s['id']).json['read_only']);self.assertEqual(self.client.put('/api/platform/support/'+s['id'],json={}).status_code,405)
        self.assertEqual(self.other.get('/api/platform/support/'+s['id']).status_code,404)
        self.assertEqual(self.client.post(url+'/status',json={'status':'suspended','reason':'Requested account suspension'}).status_code,200)
        self.assertEqual(self.other.get('/api/state').status_code,401);self.assertEqual(self.other.get('/api/card/'+self.otherstate['user']['slug']).status_code,404)
        self.client.post(url+'/status',json={'status':'active','reason':'Restore verified workspace'});self.assertEqual(self.other.get('/api/state').status_code,200)
        with app.connection() as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute('DELETE FROM platform_audit')
    def test_webhook_signatures_duplicates_and_out_of_order(self):
        self.gateway_env();sid=self.subscription();entity=self.snapshot(sid);event={'event':'subscription.activated','created_at':app.now(),'payload':{'subscription':{'entity':entity}}}
        self.assertEqual(self.webhook(event,signature=False).status_code,400)
        with patch.object(billing,'gateway',return_value=entity) as remote:
            self.assertEqual(self.webhook(event).status_code,200);self.assertTrue(self.webhook(event).json['duplicate']);self.assertEqual(remote.call_count,1)
            # A delayed authenticated event reconciles to CURRENT active state, never rolls back.
            event['event']='subscription.authenticated';event['created_at']=1
            self.assertEqual(self.webhook(event,'delayed').status_code,200)
        self.assertEqual(self.client.get('/api/billing').json['plan'],'pro')
        self.assertEqual(self.other.get('/api/billing').json['plan'],'free')
        with patch.dict(os.environ,{'RAZORPAY_MODE':'live'}):self.assertEqual(self.client.get('/api/billing').json['plan'],'free')
    def test_failed_payment_grace_does_not_extend_on_retries(self):
        self.gateway_env();sid=self.subscription('ACTIVE',end=app.now()+100);pending=self.snapshot(sid,'pending');pending['current_start']=app.now()-2*86400
        event={'event':'subscription.pending','payload':{'subscription':{'entity':pending}}}
        with patch.object(billing,'gateway',return_value=pending):
            self.assertEqual(self.webhook(event).status_code,200)
            first=self.client.get('/api/billing').json['subscription']['grace_until'];self.webhook(event,'retry')
            self.assertEqual(self.client.get('/api/billing').json['subscription']['grace_until'],first)
        with app.connection() as c:c.execute('UPDATE subscriptions SET grace_until=? WHERE id=?',(app.now()-1,sid))
        self.assertEqual(self.client.get('/api/billing').json['plan'],'free')
    def test_checkout_price_validation_and_no_client_activation(self):
        self.gateway_env();entity={'id':'sub_checkout','short_url':'https://rzp.io/i/test'}
        def remote(app,path,payload=None):return {'item':{'amount':49900,'currency':'INR'},'period':'monthly','interval':1} if path.startswith('plans/') else entity
        with patch.object(billing,'gateway',side_effect=remote):
            r=self.client.post('/api/billing/checkout',json={'price_id':'pro-monthly','amount_paise':1,'tenant_id':self.otherstate['organization']['id']});self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.client.get('/api/billing').json['plan'],'free')
        self.assertEqual(self.client.post('/api/billing/checkout-success',json={'paid':True}).status_code,404)
        self.assertEqual(self.client.get('/api/billing').json['plan'],'free')
    def test_revenue_excludes_grants_trials_and_test_payments(self):
        self.platform();self.grant('enterprise');self.client.post('/api/billing/trial',json={})
        self.subscription('ACTIVE',end=app.now()+86400)
        self.assertEqual(self.client.get('/api/platform/overview').json['mrr_paise'],0)
        r=self.client.post('/api/platform/tenants/'+self.tenant+'/offline-payment',json={'price_id':'pro-annual','reference':'bank-test-001','reason':'Annual bank payment received'});self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.client.get('/api/platform/overview').json['mrr_paise'],round(499900/12))
    def test_paid_leads_scoped_and_role_billing_guard(self):
        self.grant();slug=self.state['user']['slug'];self.assertEqual(self.other.post('/api/exchange/'+slug,json={'name':'Visitor','email':'v@example.com','consent':True}).status_code,200)
        self.assertEqual(len(self.client.get('/api/leads').json['leads']),1);self.assertEqual(len(self.other.get('/api/leads').json['leads']),0)
        with app.connection() as c:c.execute("UPDATE users SET role='admin' WHERE tenant_id=? AND account_id=?",(self.tenant,self.aid))
        self.assertEqual(self.client.get('/api/billing').status_code,403)
    def test_operator_elevation_expiry_and_price_versioning(self):
        self.platform();r=self.client.post('/api/platform/prices',json={'id':'pro-revised-monthly','plan_id':'pro','interval':'monthly','amount_paise':59900,'reason':'New customers revised pricing'});self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.client.post('/api/platform/prices/pro-monthly',json={'active':False,'reason':'Retire old checkout price'}).status_code,200)
        catalog=self.other.get('/api/public/plans').json;self.assertNotIn('pro-monthly',[p['id'] for p in catalog['prices']]);self.assertIn('pro-revised-monthly',[p['id'] for p in catalog['prices']])
        with app.connection() as c:self.assertEqual(c.execute("SELECT amount_paise FROM plan_prices WHERE id='pro-monthly'").fetchone()[0],49900)
        stamp=app.now()
        with patch.object(app,'now',return_value=stamp+601):self.assertEqual(self.client.get('/api/platform/overview').status_code,404)
    def test_captured_payments_deduplicate_across_event_ids_and_do_not_create_live_mrr(self):
        self.gateway_env();sid=self.subscription();entity=self.snapshot(sid)
        payment={'id':'pay_fixture','status':'captured','currency':'INR','amount':49900,'created_at':app.now()}
        event={'event':'subscription.charged','payload':{'subscription':{'entity':entity},'payment':{'entity':payment}}}
        def remote(app,path,payload=None):return payment if path.startswith('payments/') else entity
        with patch.object(billing,'gateway',side_effect=remote):
            self.assertEqual(self.webhook(event,'charge-one').status_code,200);self.assertEqual(self.webhook(event,'charge-two').status_code,200)
        self.assertEqual(len(self.client.get('/api/billing').json['payments']),1)
        self.platform();self.assertEqual(self.client.get('/api/platform/overview').json['mrr_paise'],0)
    def test_failed_signature_checked_before_json_and_provider_ownership_mismatch_rolls_back(self):
        self.gateway_env()
        self.assertEqual(self.client.post('/api/webhooks/razorpay',data=b'not-json',content_type='application/json',headers={'X-Razorpay-Signature':'invalid'}).status_code,400)
        sid=self.subscription();entity=self.snapshot(sid);entity['notes']['huddle_tenant_id']=self.otherstate['organization']['id']
        event={'event':'subscription.activated','payload':{'subscription':{'entity':entity}}}
        with patch.object(billing,'gateway',return_value=entity):self.assertEqual(self.webhook(event).status_code,400)
        self.assertEqual(self.client.get('/api/billing').json['plan'],'free')
        with app.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM billing_events WHERE tenant_id=?',(self.tenant,)).fetchone()[0],0)
    def test_upgrade_preserves_existing_organization_and_adds_expiring_grant(self):
        import migrate
        legacy=app.DATA/'legacy-upgrade.sqlite3'
        with sqlite3.connect(legacy) as c:
            c.executescript((app.ROOT/'migrations/001_multitenant.sql').read_text());c.executescript((app.ROOT/'migrations/002_auth_surfaces.sql').read_text())
            c.execute('INSERT INTO schema_migrations VALUES(1,1)');c.execute('INSERT INTO schema_migrations VALUES(2,1)')
            c.execute('INSERT INTO organizations VALUES(?,?,?,?,?,?)',('legacy-org','Preserved Company','preserved-company','active','{}',1))
        with patch.object(app,'DB',legacy):
            migrate.apply(app);migrate.apply(app)
            with app.connection() as c:
                self.assertEqual(c.execute('SELECT name FROM organizations').fetchone()[0],'Preserved Company')
                self.assertEqual(c.execute('SELECT count(*) FROM entitlement_overrides').fetchone()[0],1)
                grant=c.execute('SELECT * FROM entitlement_overrides').fetchone();self.assertEqual(grant['plan_id'],'enterprise');self.assertGreaterEqual(grant['expires'],app.now()+89*86400)
                self.assertEqual(c.execute('SELECT count(*) FROM platform_admin_grants').fetchone()[0],0)
                self.assertEqual(c.execute('SELECT count(*) FROM platform_audit').fetchone()[0],1)
    def test_migration_grant_only_for_preexisting_tenants(self):
        import migrate
        # Migration is idempotent; post-migration registrations do not get migration grants.
        migrate.apply(app)
        with app.connection() as c:self.assertEqual(c.execute("SELECT count(*) FROM entitlement_overrides WHERE created_by='migration'").fetchone()[0],0)
        self.assertEqual(self.client.get('/api/billing').json['plan'],'free')

if __name__=='__main__':unittest.main()
