#!/usr/bin/env python3
"""Run the real WSGI API and boundary/security suite on a disposable local PG."""
import base64,os,secrets,sys,unittest
from pathlib import Path
from urllib.parse import urlsplit
from wsgiref.simple_server import make_server
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo

root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root),str(root/'tests')]
url=os.environ['TEST_DATABASE_URL']
if urlsplit(url).hostname not in ('localhost','127.0.0.1') or os.environ.get('TEST_ALLOW_RESET')!='1':
    raise SystemExit('This test resets the huddle schema. Use a disposable localhost database and TEST_ALLOW_RESET=1.')
os.environ['MIGRATION_DATABASE_URL']=url
os.environ['HUDDLE_ENCRYPTION_KEY']=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
os.environ.pop('VERCEL',None)
os.environ.pop('SUPABASE_URL',None)
import test_multitenant as fixtures
import test_surfaces_security as security_tests
sys.modules['server']=fixtures.app
import app as deployment
from cloud_migrate import apply

# Use the actual production WSGI handler instead of the development HTTP server.
fixtures.app.ThreadingHTTPServer=lambda address,handler:make_server(address[0],address[1],deployment.app)
class PostgresDeploymentTests(unittest.TestCase):
    def test_free_organization_creation_limit_is_enforced_through_postgres(self):
        client=deployment.app.test_client();address='org-limit-'+secrets.token_hex(5)+'@example.com'
        r=client.post('/api/register',json={'email':address,'password':'LocalFixture!2026','name':'Owner','organization':'First'})
        self.assertEqual(r.status_code,200,r.json)
        r=client.post('/api/organizations',json={'name':'Personal'});self.assertEqual(r.status_code,200,r.json)
        r=client.post('/api/organizations',json={'name':'Third','max_owned_organizations':99})
        self.assertEqual(r.status_code,402,r.json);self.assertEqual(r.json['current_limit'],2)
        self.assertEqual(client.get('/api/organizations').json['ownership']['owned'],2)
    def test_package_column_permission_is_narrow_and_catalogue_is_mutable(self):
        client=deployment.app.test_client();email='package-'+secrets.token_hex(5)+'@example.com'
        r=client.post('/api/register',json={'email':email,'password':'LocalFixture!2026','name':'Owner','organization':'Package test'});self.assertEqual(r.status_code,200)
        self.assertEqual(client.get('/api/platform/packages').status_code,404)
        with fixtures.app.connection() as c:
            row=c.execute("SELECT entitlements FROM plans WHERE id='free'").fetchone();ent=__import__('json').loads(row[0]);ent['max_owned_organizations']=3
            c.execute("UPDATE plans SET entitlements=?,version=version+1 WHERE id='free'",(__import__('json').dumps(ent),))
        self.assertEqual(client.get('/api/organizations').json['ownership']['limit'],3)
        with fixtures.app.connection() as c:
            ent['max_owned_organizations']=2;c.execute("UPDATE plans SET entitlements=? WHERE id='free'",(__import__('json').dumps(ent),))
        with fixtures.app.connection() as c:
            permissions=c.execute("SELECT has_column_privilege(current_user,'huddle.plans','entitlements','UPDATE') AS editable,has_table_privilege(current_user,'huddle.plans','DELETE') AS deletable,has_column_privilege(current_user,'huddle.plans','id','UPDATE') AS identity_editable").fetchone()
            self.assertTrue(permissions['editable']);self.assertFalse(permissions['deletable']);self.assertFalse(permissions['identity_editable'])
    def setUp(self):
        with fixtures.app.connection() as c:c.execute('DELETE FROM rate_limits')
    def test_optional_sqlite_import_preserves_links_mfa_and_private_assets(self):
        import tempfile,hashlib,io
        from unittest.mock import patch
        from scripts.import_sqlite import run
        from PIL import Image
        from psycopg import sql
        import object_storage,security
        dbname='huddle_import_'+secrets.token_hex(5)
        options=conninfo_to_dict(url);options['dbname']=dbname;target=make_conninfo(**options)
        with psycopg.connect(url,autocommit=True) as admin:admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(dbname)))
        original_data,original_db=fixtures.app.DATA,fixtures.app.DB
        try:
            apply(target)
            with tempfile.TemporaryDirectory() as folder:
                fixtures.app.DATA=Path(folder);fixtures.app.DB=Path(folder)/'huddle.sqlite3'
                with patch.dict(os.environ,{},clear=False):
                    os.environ.pop('DATABASE_URL',None)
                    fixtures.app.initialise(True)
                    with fixtures.app.connection() as c:
                        card=c.execute('SELECT * FROM cards LIMIT 1').fetchone();tenant,user=card['tenant_id'],card['user_id']
                        c.execute('INSERT INTO nfc_cards VALUES(?,?,?,?,?,?,?,?,?)',('import-tag',tenant,card['id'],'unchanged-import-token','Fixture',None,1,1,None))
                        secret=security.encrypt(fixtures.app,tenant,user,'JBSWY3DPEHPK3PXP')
                        c.execute('INSERT INTO user_security(tenant_id,user_id,secret,enabled) VALUES(?,?,?,1)',(tenant,user,secret))
                        buffer=io.BytesIO();Image.new('RGB',(4,4),'red').save(buffer,format='PNG');image=buffer.getvalue()
                        key='/media/'+tenant+'/'+hashlib.sha256(image).hexdigest()+'.png'
                        path=Path(folder)/key.lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(image)
                        c.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)',('import-image',tenant,user,key,'private',1))
                    (Path(folder)/'.security-key').write_bytes(base64.urlsafe_b64decode(os.environ['HUDDLE_ENCRYPTION_KEY']))
                    before=hashlib.sha256(fixtures.app.DB.read_bytes()).hexdigest()
                    run(fixtures.app.DB)
                    with patch.dict(os.environ,{'MIGRATION_DATABASE_URL':target,'SUPABASE_URL':'https://fixture.supabase.co'}),patch.object(object_storage,'request',return_value=b'{}') as upload:
                        run(fixtures.app.DB,apply=True);self.assertEqual(upload.call_count,1)
                        with self.assertRaises(RuntimeError):run(fixtures.app.DB,apply=True)
                    self.assertEqual(hashlib.sha256(fixtures.app.DB.read_bytes()).hexdigest(),before)
                with psycopg.connect(target) as c:
                    self.assertEqual(c.execute('SELECT slug FROM huddle.cards WHERE id=%s',(card['id'],)).fetchone()[0],card['slug'])
                    self.assertEqual(c.execute('SELECT token FROM huddle.nfc_cards').fetchone()[0],'unchanged-import-token')
                    self.assertEqual(c.execute('SELECT secret FROM huddle.user_security').fetchone()[0],secret)
                    self.assertEqual(c.execute('SELECT visibility FROM huddle.assets').fetchone()[0],'private')
                    self.assertEqual(c.execute('SELECT count(*) FROM huddle.sessions').fetchone()[0],0)
                    self.assertEqual(c.execute('SELECT plan_id FROM huddle.entitlement_overrides WHERE tenant_id=%s',(tenant,)).fetchone()[0],'enterprise')
        finally:
            fixtures.app.DATA,fixtures.app.DB=original_data,original_db
            with psycopg.connect(url,autocommit=True) as admin:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(dbname)))
    def test_runtime_role_is_not_an_admin_and_clients_cannot_read_tables(self):
        with fixtures.app.connection() as c:
            self.assertEqual(c.execute('SELECT current_user').fetchone()[0],'huddle_backend')
            self.assertFalse(c.execute("SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()[0])
        with psycopg.connect(url,autocommit=True) as c:
            if not c.execute("SELECT 1 FROM pg_roles WHERE rolname='huddle_browser_probe'").fetchone():c.execute('CREATE ROLE huddle_browser_probe NOLOGIN')
            c.execute('SET ROLE huddle_browser_probe')
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT * FROM huddle.cards')
    def test_rate_limit_survives_process_memory_reset_and_rejected_attempts(self):
        import database
        database.limited(fixtures.app,'fixture-ip','fixture-group',1)
        fixtures.app.RATE.clear()
        with self.assertRaises(fixtures.app.Problem):database.limited(fixtures.app,'fixture-ip','fixture-group',1)
        with fixtures.app.connection() as c:self.assertEqual(c.execute('SELECT hits FROM rate_limits').fetchone()[0],2)
    def test_concurrent_recovery_code_can_create_only_one_session(self):
        import security
        from concurrent.futures import ThreadPoolExecutor
        password='ConcurrencyPass!2026';email='race.'+secrets.token_hex(5)+'@example.com'
        client=deployment.app.test_client()
        self.assertEqual(client.post('/api/register',json={'email':email,'password':password,'organization':'Concurrency fixture'}).status_code,200)
        setup=client.post('/api/security/setup',json={'password':password}).json
        codes=client.post('/api/security/confirm',json={'code':security.totp(setup['secret'])}).json['recovery_codes']
        tokens=[deployment.app.test_client().post('/api/login',json={'email':email,'password':password}).json['challenge'] for _ in range(2)]
        def verify(token):return deployment.app.test_client().post('/api/auth/verify',json={'challenge':token,'code':codes[0]})
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(verify,tokens))
        self.assertEqual(sum(r.status_code==200 for r in responses),1)
        self.assertTrue(all(r.status_code in (200,403,409) for r in responses))
        self.assertEqual(sum('hello_session=' in r.headers.get('Set-Cookie','') for r in responses),1)


    def billing_owner(self):
        client=deployment.app.test_client();address='billing.'+secrets.token_hex(6)+'@example.com'
        self.assertEqual(client.post('/api/register',json={'email':address,'password':'BillingPg!2026','organization':'Billing PostgreSQL'}).status_code,200)
        state=client.get('/api/state').json
        return client,address,state
    def test_concurrent_quota_requests_cannot_overallocate_cards(self):
        from concurrent.futures import ThreadPoolExecutor
        import billing
        client,address,state=self.billing_owner();tenant=state['organization']['id']
        with fixtures.app.connection() as c:c.execute('INSERT INTO entitlement_overrides VALUES(?,?,?,?,?,?,?,?,?)',(fixtures.app.uid(),tenant,'pro','{}','Concurrency test grant','test',fixtures.app.now(),fixtures.app.now()+86400,None))
        cookie=client.get_cookie('hello_session').value
        def create(i):
            request=deployment.app.test_client();request.set_cookie('hello_session',cookie)
            r=request.post('/api/cards',json={'persona':'Race '+str(i)});return (r.status_code,r.json)
        with ThreadPoolExecutor(max_workers=12) as pool:results=list(pool.map(create,range(18)))
        self.assertTrue(all(x[0] in (200,402,409) for x in results),results)
        with fixtures.app.connection() as c:self.assertLessEqual(billing.usage(fixtures.app,c,tenant)['cards'],10)
        # Retry serialization conflicts sequentially; exactly ten total cards fit.
        for i in range(12):client.post('/api/cards',json={'persona':'Retry '+str(i)})
        with fixtures.app.connection() as c:self.assertEqual(billing.usage(fixtures.app,c,tenant)['cards'],10)
        self.assertEqual(client.post('/api/invitations',json={'email':'reserved@example.com','name':'Reserved'}).status_code,402)
    def test_platform_grants_cannot_be_self_assigned_and_audit_is_append_only(self):
        import security,psycopg
        client,address,state=self.billing_owner()
        with fixtures.app.connection() as c:aid=c.execute('SELECT account_id FROM users WHERE tenant_id=?',(state['organization']['id'],)).fetchone()[0]
        with self.assertRaises(Exception):
            with fixtures.app.connection() as c:c.execute('INSERT INTO platform_admin_grants VALUES(?,?,?,?)',(aid,fixtures.app.now(),'attack','Tenant cannot self assign'))
        self.assertEqual(client.get('/api/platform/overview').status_code,404)
        with psycopg.connect(url) as admin:admin.execute('INSERT INTO huddle.platform_admin_grants VALUES(%s,%s,%s,%s)',(aid,fixtures.app.now(),'test','Controlled test provision'))
        setup=client.post('/api/platform/mfa/setup',json={'password':'BillingPg!2026'});self.assertEqual(setup.status_code,200,setup.json)
        result=client.post('/api/platform/mfa/confirm',json={'password':'BillingPg!2026','code':security.totp(setup.json['secret'])});self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(client.get('/api/platform/overview').status_code,200)
        with self.assertRaises(Exception):
            with fixtures.app.connection() as c:c.execute('DELETE FROM platform_audit')
        with psycopg.connect(url,autocommit=True) as admin:
            if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname='huddle_browser_probe'").fetchone():admin.execute('CREATE ROLE huddle_browser_probe NOLOGIN')
        for table in ('platform_admin_grants','subscriptions','payments','billing_events','platform_audit'):
            with psycopg.connect(url,autocommit=True) as admin:
                admin.execute('SET ROLE huddle_browser_probe')
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):admin.execute('SELECT * FROM huddle.'+table)
    def test_billing_webhook_uses_transactional_deduplication(self):
        import billing,hashlib,hmac,json
        from unittest.mock import patch
        client,address,state=self.billing_owner();tenant=state['organization']['id'];sid=fixtures.app.uid()
        with fixtures.app.connection() as c:c.execute('INSERT INTO subscriptions(id,tenant_id,plan_id,price_id,status,mode,provider_subscription_id,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',(sid,tenant,'pro','pro-monthly','AUTHENTICATED','test','sub_'+sid,fixtures.app.now(),fixtures.app.now()))
        entity={'id':'sub_'+sid,'status':'active','plan_id':'plan_fixture','current_end':fixtures.app.now()+86400,'notes':{'huddle_tenant_id':tenant,'huddle_subscription_id':sid}}
        raw=json.dumps({'event':'subscription.activated','payload':{'subscription':{'entity':entity}}}).encode();secret='pg-fixture-webhook';signature=hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest();eid='pg-event-'+secrets.token_hex(4)
        env={'RAZORPAY_MODE':'test','RAZORPAY_KEY_ID':'rzp_test_fixture','RAZORPAY_KEY_SECRET':'fixture','RAZORPAY_WEBHOOK_SECRET':secret,'RAZORPAY_PLAN_PRO_MONTHLY':'plan_fixture'}
        with patch.dict(os.environ,env),patch.object(billing,'gateway',return_value=entity):
            a=client.post('/api/webhooks/razorpay',data=raw,content_type='application/json',headers={'X-Razorpay-Signature':signature,'X-Razorpay-Event-Id':eid});self.assertEqual(a.status_code,200,a.json)
            b=client.post('/api/webhooks/razorpay',data=raw,content_type='application/json',headers={'X-Razorpay-Signature':signature,'X-Razorpay-Event-Id':eid});self.assertTrue(b.json['duplicate'])
            self.assertEqual(client.get('/api/billing').json['plan'],'pro')
        with fixtures.app.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM billing_events WHERE provider_event_id=?',(eid,)).fetchone()[0],1)

    def test_upgrade_backfills_existing_tenant_without_granting_platform_access(self):
        import hashlib
        from psycopg import sql
        dbname='huddle_upgrade_'+secrets.token_hex(5);info=conninfo_to_dict(url);info['dbname']=dbname;target=make_conninfo(**info)
        with psycopg.connect(url,autocommit=True) as admin:admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(dbname)))
        try:
            with psycopg.connect(target) as c:
                c.execute('CREATE SCHEMA huddle');c.execute('CREATE TABLE huddle.deployment_migrations(version TEXT PRIMARY KEY,sha256 TEXT NOT NULL,applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
                for path in sorted((root/'supabase/migrations').glob('*.sql'))[:2]:
                    source=path.read_text();c.execute(source,prepare=False);c.execute('INSERT INTO huddle.deployment_migrations(version,sha256) VALUES(%s,%s)',(path.stem,hashlib.sha256(source.encode()).hexdigest()))
                c.execute("INSERT INTO huddle.organizations VALUES('legacy-org','Preserved Company','preserved-company','active','{}',1)")
            apply(target);apply(target)
            with psycopg.connect(target) as c:
                self.assertEqual(c.execute('SELECT name FROM huddle.organizations').fetchone()[0],'Preserved Company')
                self.assertEqual(c.execute('SELECT count(*) FROM huddle.entitlement_overrides').fetchone()[0],1)
                self.assertEqual(c.execute('SELECT count(*) FROM huddle.platform_admin_grants').fetchone()[0],0)
                self.assertEqual(c.execute('SELECT count(*) FROM huddle.platform_audit').fetchone()[0],1)
        finally:
            with psycopg.connect(url,autocommit=True) as admin:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(dbname)))

classes=[fixtures.TenancyTests,security_tests.SurfaceSecurityTests]
total=0;failed=False
for cls in classes:
    with psycopg.connect(url,autocommit=True) as c:c.execute('DROP SCHEMA IF EXISTS huddle CASCADE')
    apply(url)
    password=secrets.token_urlsafe(32)
    from psycopg import sql
    with psycopg.connect(url) as c:c.execute(sql.SQL('ALTER ROLE huddle_backend PASSWORD {}').format(sql.Literal(password)))
    info=conninfo_to_dict(url);info.update(user='huddle_backend',password=password)
    os.environ['DATABASE_URL']=make_conninfo(**info)
    # Fresh rate-limit windows for independent fixtures; no production reset route.
    original=cls.setUp
    def setup(self,previous=original):
        with fixtures.app.connection() as c:c.execute('DELETE FROM rate_limits')
        previous(self)
    cls.setUp=setup
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
    total+=result.testsRun;failed=failed or not result.wasSuccessful()
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PostgresDeploymentTests))
total+=result.testsRun;failed=failed or not result.wasSuccessful()
print('PostgreSQL WSGI boundary/security/deployment tests:',total,'passed' if not failed else 'FAILED')
raise SystemExit(1 if failed else 0)
