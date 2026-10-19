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
