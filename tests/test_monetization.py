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
    def test_owned_organization_limit_free_and_no_partial_creation(self):
        r=self.client.get('/api/organizations');self.assertEqual(r.json['ownership']['limit'],2)
        self.assertEqual(self.client.post('/api/organizations',json={'name':'Personal'}).status_code,200)
        blocked=self.client.post('/api/organizations',json={'name':'Third','plan':'enterprise','limit':999})
        self.assertEqual(blocked.status_code,402);self.assertEqual(blocked.json['current_limit'],2)
        self.assertEqual(self.client.get('/api/organizations').json['ownership']['owned'],2)
        with app.connection() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM organizations WHERE name='Third'").fetchone()[0],0)
    def test_owned_plan_limit_changes_without_lending_paid_access(self):
        self.grant('pro')
        created=[]
        for i in range(4):
            r=self.client.post('/api/organizations',json={'name':'Workspace '+str(i)});self.assertEqual(r.status_code,200,r.json);created.append(r.json['id'])
        self.assertEqual(self.client.post('/api/organizations',json={'name':'Sixth'}).status_code,402)
        with app.connection() as c:
            self.assertEqual(billing.effective(app,c,created[0])['plan'],'free')
            c.execute('UPDATE entitlement_overrides SET expires=? WHERE tenant_id=?',(app.now()-1,self.tenant))
        r=self.client.get('/api/organizations').json
        self.assertEqual(r['ownership']['owned'],5);self.assertEqual(r['ownership']['limit'],2)
        self.assertFalse(r['ownership']['can_create']);self.assertEqual(len(r['organizations']),5)
        self.assertEqual(self.client.post('/api/organizations/switch',json={'tenant_id':created[0]}).status_code,200)
    def test_invited_membership_neither_consumes_ownership_nor_lends_enterprise(self):
        other_tenant=self.otherstate['organization']['id'];self.grant('enterprise',tenant=other_tenant)
        with app.connection() as c:
            app.add_user(c,other_tenant,{'name':'Invited member'},account_id=self.aid)
        quota=self.client.get('/api/organizations').json
        self.assertEqual(len(quota['organizations']),2);self.assertEqual(quota['ownership']['owned'],1)
        self.assertEqual(quota['ownership']['limit'],2)
    def test_enterprise_and_suspended_owned_organizations_still_count(self):
        self.grant('enterprise')
        r=self.client.get('/api/organizations').json;self.assertEqual(r['ownership']['limit'],20)
        new=self.client.post('/api/organizations',json={'name':'Suspended'}).json['id']
        with app.connection() as c:c.execute("UPDATE organizations SET status='suspended' WHERE id=?",(new,))
        r=self.client.get('/api/organizations').json
        self.assertEqual(r['ownership']['owned'],2);self.assertEqual(len(r['organizations']),1)
        with app.connection() as c:
            c.execute('UPDATE users SET active=0 WHERE tenant_id=? AND account_id=?',(self.tenant,self.aid))
            self.assertEqual(billing.organization_capacity(app,c,self.aid)['limit'],2)
    def test_package_manager_requires_platform_elevation_and_audits_changes(self):
        self.assertEqual(self.client.get('/api/platform/packages').status_code,404)
        self.platform();catalog=self.client.get('/api/platform/packages').json
        free=next(p for p in catalog['packages'] if p['id']=='free')
        payload={'name':'Free','version':free['version'],'reason':'Reviewed ownership allowance','entitlements':{**free['entitlements'],'max_owned_organizations':3}}
        self.assertEqual(self.other.put('/api/platform/packages/free',json=payload).status_code,404)
        r=self.client.put('/api/platform/packages/free',json=payload);self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.other.get('/api/organizations').json['ownership']['limit'],3)
        public=next(p for p in self.other.get('/api/public/plans').json['plans'] if p['id']=='free')
        self.assertEqual(public['entitlements']['max_owned_organizations'],3)
        self.assertEqual(self.client.put('/api/platform/packages/free',json=payload).status_code,409)
        with app.connection() as c:
            entries=c.execute("SELECT details FROM platform_audit WHERE action='package.updated'").fetchall()
            self.assertEqual(len(entries),1);self.assertEqual(json.loads(entries[0][0])['before']['entitlements']['max_owned_organizations'],2)
    def test_package_manager_rejects_invalid_and_unknown_settings(self):
        self.platform();p=next(p for p in self.client.get('/api/platform/packages').json['packages'] if p['id']=='free')
        base={'name':p['name'],'version':p['version'],'reason':'Validate package settings','entitlements':p['entitlements']}
        for change in ({'max_cards':True},{'max_owned_organizations':-1},{'custom_qr':1},{'is_platform_admin':True}):
            payload={**base,'entitlements':{**base['entitlements'],**change}}
            self.assertEqual(self.client.put('/api/platform/packages/free',json=payload).status_code,400)
    def test_catalogue_changes_drive_invite_limits_and_pending_reservations(self):
        state=self.client.get('/api/state').json;self.assertTrue(state['invitation_capacity']['reached'])
        invite={'name':'New colleague','email':'new@example.com','division_id':state['divisions'][0]['id'],'template_id':state['templates'][0]['id']}
        r=self.client.post('/api/invitations',json=invite);self.assertEqual(r.status_code,402);self.assertIn('limit',r.json['message'])
        self.platform();p=next(p for p in self.client.get('/api/platform/packages').json['packages'] if p['id']=='free')
        ent={**p['entitlements'],'max_seats':2,'max_cards':2}
        self.assertEqual(self.client.put('/api/platform/packages/free',json={'name':'Free','version':p['version'],'reason':'Adjusted member and card quota','entitlements':ent}).status_code,200)
        self.assertFalse(self.client.get('/api/state').json['invitation_capacity']['reached'])
        self.assertEqual(self.client.post('/api/invitations',json=invite).status_code,200)
        self.assertTrue(self.client.get('/api/state').json['invitation_capacity']['reached'])
        self.assertEqual(self.client.post('/api/invitations',json={**invite,'email':'another@example.com'}).status_code,402)
        self.assertEqual(len(self.client.get('/api/state').json['invitations']),1)
    def test_unlimited_ownership_comes_from_catalogue_and_survives_migration_rerun(self):
        with app.connection() as c:
            p=billing.plan(c,'free');p['entitlements']['max_owned_organizations']=None
            c.execute('UPDATE plans SET entitlements=? WHERE id=?',(app.dump(p['entitlements']),'free'))
        import migrate
        migrate.apply(app)
        self.assertIsNone(self.client.get('/api/organizations').json['ownership']['limit'])
        for i in range(3):self.assertEqual(self.client.post('/api/organizations',json={'name':'Personal '+str(i)}).status_code,200)
    def test_audit_table_paging_filters_and_human_labels_preserve_old_records(self):
        self.platform();target=self.otherstate['organization']['id']
        with app.connection() as c:
            for i in range(70):
                c.execute('INSERT INTO platform_audit VALUES(?,?,?,?,?,?,?)',(app.uid(),self.aid,target,'package.updated','Readable audit fixture '+str(i),'{}',app.now()-(14*86400 if i<45 else 0)))
        entries=[]
        for page,size in [(0,25),(1,25),(2,20)]:
            r=self.client.get('/api/platform/audit?q=Readable+audit+fixture&page='+str(page)).json
            self.assertEqual(len(r['entries']),size);self.assertEqual(r['total'],70);self.assertEqual(r['has_more'],page<2)
            self.assertFalse(r['auto_delete']);entries+=r['entries']
        self.assertEqual(len({e['id'] for e in entries}),70)
        self.assertTrue(all(e['action_label']=='Package updated' and e['actor_email']==self.email and e['organization_name']=='Company' for e in entries))
        recent=self.client.get('/api/platform/audit?q=Readable+audit+fixture&days=7').json
        self.assertEqual(recent['total'],25)
        human_search=self.client.get('/api/platform/audit?q=Package+updated').json
        self.assertEqual(human_search['total'],70)
        with app.connection() as c:self.assertEqual(c.execute("SELECT count(*) FROM platform_audit WHERE reason LIKE 'Readable audit fixture%' ").fetchone()[0],70)
        self.assertEqual(self.other.get('/api/platform/audit').status_code,404)
        self.assertEqual(self.client.get('/api/platform/audit?days=invalid').status_code,400)
    def test_organization_roster_has_real_pagination_totals_and_dedicated_routes(self):
        self.platform();r=self.client.get('/api/platform/tenants?q=Company').json
        self.assertEqual(r['total'],2);self.assertEqual(r['page_size'],25);self.assertFalse(r['has_more'])
        self.assertEqual(self.client.get('/api/platform/tenants?page=invalid').status_code,400)
        for path in ('/super-admin/organizations/'+self.tenant,'/super-admin/packages/free','/super-admin/audit'):
            self.assertEqual(self.client.get(path).status_code,200);self.assertEqual(self.other.get(path).status_code,404)
    def test_india_offers_preserve_legacy_billing_and_package_allowances(self):
        catalog=self.client.get('/api/public/plans').json
        self.assertEqual([o['plan_id'] for o in catalog['offers']],['free','pro-individual','pro-workspace','enterprise'])
        by_id={p['id']:p for p in catalog['plans']}
        self.assertEqual(by_id['pro-individual']['entitlements']['max_cards'],3)
        self.assertEqual(by_id['pro-individual']['entitlements']['max_seats'],1)
        self.assertEqual(by_id['pro-workspace']['entitlements']['max_cards'],50)
        self.assertEqual(by_id['pro-workspace']['entitlements']['max_seats'],10)
        self.assertEqual(by_id['pro']['entitlements']['max_cards'],10)
        sid=self.subscription(status='ACTIVE',end=app.now()+86400)
        with app.connection() as c:
            before=dict(c.execute('SELECT * FROM subscriptions WHERE id=?',(sid,)).fetchone())
            legacy=dict(c.execute("SELECT * FROM plan_prices WHERE id='enterprise-monthly'").fetchone())
        import migrate
        migrate.apply(app)
        with app.connection() as c:
            self.assertEqual(dict(c.execute('SELECT * FROM subscriptions WHERE id=?',(sid,)).fetchone()),before)
            self.assertEqual(dict(c.execute("SELECT * FROM plan_prices WHERE id='enterprise-monthly'").fetchone()),legacy)
        self.assertFalse(any(p['plan_id']=='enterprise' for p in catalog['prices']))

    def test_published_offer_selection_updates_catalogue_without_repricing_subscriptions(self):
        sid=self.subscription(status='ACTIVE',end=app.now()+86400)
        self.platform()
        payload={'id':'individual-revised-monthly','plan_id':'pro-individual','interval':'monthly','amount_paise':17900,'reason':'Test published individual price'}
        self.assertEqual(self.client.post('/api/platform/prices',json=payload).status_code,200)
        offer=next(o for o in self.client.get('/api/platform/prices').json['offers'] if o['plan_id']=='pro-individual')
        update={**offer,'monthly_price_id':payload['id'],'reason':'Publish tested individual offer'}
        url='/api/platform/pricing-offers/pro-individual'
        self.assertEqual(self.other.put(url,json=update).status_code,404)
        self.assertEqual(self.client.put(url,json=update).status_code,200)
        public=next(o for o in self.other.get('/api/public/plans').json['offers'] if o['plan_id']=='pro-individual')
        self.assertEqual(public['monthly_price_id'],payload['id'])
        self.assertEqual(self.client.put(url,json=update).status_code,409)
        with app.connection() as c:
            self.assertEqual(c.execute('SELECT price_id FROM subscriptions WHERE id=?',(sid,)).fetchone()[0],'pro-monthly')
            self.assertEqual(c.execute("SELECT amount_paise FROM plan_prices WHERE id='pro-monthly'").fetchone()[0],49900)
            self.assertEqual(c.execute("SELECT count(*) FROM platform_audit WHERE action='billing.offer_updated'").fetchone()[0],1)

    def test_published_offer_rejects_cross_package_or_retired_price(self):
        self.platform()
        offer=next(o for o in self.client.get('/api/platform/prices').json['offers'] if o['plan_id']=='pro-individual')
        base={**offer,'reason':'Validate published offer guard'}
        for bad in ('pro-monthly','enterprise-monthly','pro-individual-annual','missing'):
            self.assertEqual(self.client.put('/api/platform/pricing-offers/pro-individual',json={**base,'monthly_price_id':bad}).status_code,400)
        self.client.post('/api/platform/prices/pro-individual-monthly',json={'active':False,'reason':'Retire individual price fixture'})
        self.assertEqual(self.client.put('/api/platform/pricing-offers/pro-individual',json=base).status_code,400)

    def test_enterprise_quote_terms_are_versioned_and_public(self):
        self.platform();url='/api/platform/pricing-offers/enterprise'
        offer=next(o for o in self.client.get('/api/platform/prices').json['offers'] if o['plan_id']=='enterprise')
        payload={**offer,'quote_annual_seat_paise':129900,'minimum_seats':30,'cards_per_seat':6,'reason':'Revise Enterprise quote terms'}
        for key in ('minimum_seats','cards_per_seat','quote_annual_seat_paise'):
            self.assertEqual(self.client.put(url,json={**payload,key:True}).status_code,400)
        self.assertEqual(self.client.put(url,json=payload).status_code,200)
        current=next(o for o in self.other.get('/api/public/plans').json['offers'] if o['plan_id']=='enterprise')
        self.assertEqual((current['minimum_seats'],current['quote_annual_seat_paise']),(30,129900))

    def test_quote_requires_consent_and_is_visible_only_to_elevated_platform_owner(self):
        visitor=web.test_client();url='/api/public/enterprise-quotes'
        data={'name':'Arun Kumar','email':'arun@example.com','company':'Kaveri Industrial Supplies','seats':25,'message':'A Chennai pilot','consent':True}
        self.assertEqual(visitor.post(url,json={**data,'consent':False}).status_code,400)
        self.assertEqual(visitor.post(url,json={**data,'seats':24}).status_code,400)
        self.assertEqual(visitor.post(url,json={**data,'seats':True}).status_code,400)
        self.assertEqual(visitor.post(url,json=data).status_code,200)
        self.assertEqual(visitor.get('/api/platform/quote-requests').status_code,404)
        self.assertEqual(self.client.get('/api/platform/quote-requests').status_code,404)
        self.platform();quotes=self.client.get('/api/platform/quote-requests').json['requests']
        self.assertEqual(len(quotes),1);self.assertEqual(quotes[0]['email'],data['email'])
        self.assertEqual(quotes[0]['consent_version'],'sales-enquiry-v2')
        with app.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM payments').fetchone()[0],0)
        self.assertEqual(visitor.post(url,json=data).status_code,200)
        self.assertEqual(visitor.post(url,json=data).status_code,429)

    def test_individual_checkout_uses_its_own_package_and_enforces_three_cards(self):
        self.gateway_env();os.environ['RAZORPAY_PLAN_PRO_INDIVIDUAL_MONTHLY']='plan_individual'
        calls=[]
        def provider(app,path,payload=None):
            calls.append((path,payload))
            if path=='plans/plan_individual':return {'item':{'amount':14900,'currency':'INR'},'period':'monthly','interval':1}
            return {'id':'sub_individual','status':'created','short_url':'https://rzp.io/i/fixture'}
        with patch.object(billing,'gateway',side_effect=provider):
            result=self.client.post('/api/billing/checkout',json={'price_id':'pro-individual-monthly','amount_paise':1,'plan':'enterprise'})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(calls[-1][1]['quantity'],1)
        with app.connection() as c:
            sub=c.execute("SELECT plan_id,price_id FROM subscriptions WHERE provider_subscription_id='sub_individual'").fetchone()
            self.assertEqual((sub['plan_id'],sub['price_id']),('pro-individual','pro-individual-monthly'))
        self.grant('pro-individual')
        for persona in ('Consulting','Community'):
            self.assertEqual(self.client.post('/api/cards',json={'persona':persona}).status_code,200)
        self.assertEqual(self.client.post('/api/cards',json={'persona':'Fourth'}).status_code,402)
        self.assertEqual(self.client.post('/api/invitations',json={'name':'Colleague','email':'colleague@example.com'}).status_code,402)

    def test_enterprise_checkout_is_quote_only_before_calling_provider(self):
        self.gateway_env()
        with patch.object(billing,'gateway',side_effect=AssertionError('Enterprise must not call provider')):
            result=self.client.post('/api/billing/checkout',json={'price_id':'enterprise-monthly'})
        self.assertEqual(result.status_code,409,result.json)
        self.assertIn('quote',result.json['error'])

    def test_structured_enquiry_validation_and_private_inbox(self):
        data={'name':'Meera Nair','email':'meera@example.com','company':'Malabar Studio','seats':30,'consent':True,'phone':'+91 98765 43210','job_title':'Sales director','company_website':'https://example.com','industry':'Manufacturing','location':'Chennai, India','timeline':'1-3-months','hardware':'buy-cards','nfc_quantity':30,'needs':['branding','nfc']}
        r=self.client.post('/api/public/enterprise-quotes',json=data);self.assertEqual(r.status_code,200,r.json);reference=r.json['reference']
        self.platform();q=self.client.get('/api/platform/quote-requests').json['requests'][0]
        self.assertEqual(q['id'],reference);self.assertEqual(q['details']['nfc_quantity'],30);self.assertEqual(q['details']['location'],'Chennai, India')
        for bad in ({'needs':['unknown']},{'nfc_quantity':True},{'phone':'not-a-number'},{'company_website':'javascript:alert(1)'}):
            app.RATE.clear();self.assertEqual(self.other.post('/api/public/enterprise-quotes',json={**data,**bad}).status_code,400)
        with app.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM enterprise_quote_requests').fetchone()[0],1)
    def test_hardware_enquiry_separate_from_enterprise_minimum_and_no_subscription(self):
        with app.connection() as c:before=c.execute('SELECT count(*) FROM subscriptions').fetchone()[0]
        data={'name':'Kavin','email':'kavin@example.com','company':'Marina Works','seats':1,'consent':True,'request_type':'nfc','hardware':'buy-cards','nfc_quantity':1}
        self.assertEqual(self.client.post('/api/public/enterprise-quotes',json=data).status_code,200)
        self.assertEqual(self.client.post('/api/public/enterprise-quotes',json={**data,'request_type':'enterprise'}).status_code,400)
        self.assertEqual(self.client.post('/api/public/enterprise-quotes',json={**data,'nfc_quantity':0}).status_code,400)
        with app.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM subscriptions').fetchone()[0],before)
            self.assertEqual(c.execute('SELECT count(*) FROM payments').fetchone()[0],0)
    def test_public_company_policies_and_nfc_route(self):
        for path in ('/terms','/privacy','/data-protection','/refunds','/shipping','/contact','/about'):
            r=self.other.get(path);self.assertEqual(r.status_code,200);self.assertIn(b'Touchmark Descience',r.data);self.assertIn(b'info@touchmarkdes.com',r.data)
        self.assertIn(b'33AAGCT9408C1ZI',self.other.get('/contact').data)
        self.assertIn(b'duplicate payments',self.other.get('/refunds').data)
        self.assertEqual(self.other.get('/nfc-cards').status_code,200)

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
    def test_signup_paid_preference_never_grants_access(self):
        client=web.test_client()
        result=client.post('/api/register',json={'email':'plan-choice@example.com','password':self.password,'name':'New Owner','organization':'Plan Choice','selected_plan':'enterprise','plan':'enterprise','interval':'annual','price_id':'enterprise-monthly','amount_paise':0,'tenant_id':self.otherstate['organization']['id']})
        self.assertEqual(result.status_code,200,result.json)
        b=client.get('/api/billing').json
        self.assertEqual((b['plan'],b['source'],b['subscription']['status']),('free','free','FREE'))
        self.assertTrue(b['trial_available'])
        self.assertEqual(b['usage']['cards'],1)
        self.assertEqual(client.post('/api/cards',json={'persona':'Extra'}).status_code,402)
        self.assertNotEqual(client.get('/api/state').json['organization']['id'],self.otherstate['organization']['id'])

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
        secret=self.platform()
        with app.connection() as c:consumed=c.execute('SELECT last_counter FROM platform_security WHERE account_id=?',(self.aid,)).fetchone()[0]
        replayed_code=security.totp(secret,consumed*30)
        self.assertEqual(self.client.get('/super-admin').status_code,200);self.assertEqual(self.client.get('/api/platform/overview').status_code,200)
        self.assertEqual(self.other.get('/api/platform/overview').status_code,404)
        self.client.post('/api/platform/logout',json={});self.assertEqual(self.client.get('/api/platform/overview').status_code,404)
        self.assertEqual(self.client.post('/api/platform/elevate',json={'password':self.password,'code':replayed_code}).status_code,403)
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
