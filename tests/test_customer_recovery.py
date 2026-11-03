"""Customer recovery and archive through authenticated platform routes."""
import base64,hashlib,os,sys,tempfile,unittest,urllib.parse
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import platform_admin,server

class Handler:
    def __init__(self,body=None,operator=True):
        self.data=body or {};self.headers={'Cookie':'huddle_operator=fixture-token'} if operator else {}
    def body(self):return self.data
    def limited(self,*args):pass
    def token_hash(self):raise server.Problem('Please sign in.',401)

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'HUDDLE_DATA_DIR':self.temp.name,'HUDDLE_ADMIN_EMAIL':'operator@example.com',
            'HUDDLE_ADMIN_PASSWORD':'Operator-Test!2026','HUDDLE_ENCRYPTION_KEY':base64.urlsafe_b64encode(b'x'*32).decode(),
            'PUBLIC_BASE_URL':'https://www.huddleapp.in'},clear=True);self.env.start()
        self.old=server.DATA,server.DB,server.DEMO
        server.DATA=Path(self.temp.name);server.DB=server.DATA/'huddle.sqlite3';server.DEMO=False
        server.initialise()
        with server.connection() as c:
            self.operator=c.execute("SELECT id FROM accounts WHERE email='operator@example.com'").fetchone()[0]
            c.execute('INSERT INTO platform_admin_grants VALUES(?,?,?,?)',(self.operator,server.now(),'test','Recovery test'))
            c.execute('INSERT INTO platform_sessions VALUES(?,?,?)',(hashlib.sha256(b'fixture-token').hexdigest(),self.operator,server.now()+600))
            self.customer=server.uid()
            c.execute('INSERT INTO accounts VALUES(?,?,?,?,?)',(self.customer,'customer@example.com',server.password_hash('Customer-Test!2026'),server.now(),None))
            self.tenant=server.create_org(c,'Customer Company',self.customer,'Customer')
            self.member=c.execute('SELECT id FROM users WHERE tenant_id=? AND account_id=?',(self.tenant,self.customer)).fetchone()[0]
            c.execute('INSERT INTO sessions(token_hash,account_id,active_tenant_id,expires) VALUES(?,?,?,?)',('customer-session',self.customer,self.tenant,server.now()+3600))
    def tearDown(self):server.DATA,server.DB,server.DEMO=self.old;self.env.stop();self.temp.cleanup()
    def route(self,path,body=None,operator=True):
        with server.connection() as c:matched,result=platform_admin.route(server,Handler(body,operator),c,'POST',path)
        self.assertTrue(matched);return result
    def test_manual_and_generated_reset(self):
        path=f'/api/platform/tenants/{self.tenant}/members/{self.member}/password'
        with self.assertRaisesRegex(server.Problem,'Not found'):
            self.route(path,{'mode':'manual','password':'No-Access!2026','reason':'Unauthorized attempt'},False)
        self.assertTrue(self.route(path,{'mode':'manual','password':'Temporary-New!2026','reason':'Customer verified by support'})['ok'])
        with server.connection() as c:
            self.assertTrue(server.password_matches('Temporary-New!2026',c.execute('SELECT password_hash FROM accounts WHERE id=?',(self.customer,)).fetchone()[0]))
            self.assertEqual(c.execute('SELECT count(*) FROM sessions WHERE account_id=?',(self.customer,)).fetchone()[0],0)
        result=self.route(path,{'mode':'generated','reason':'Customer requested fresh access'})
        self.assertGreaterEqual(len(result['password']),20)
        with server.connection() as c:
            self.assertTrue(server.password_matches(result['password'],c.execute('SELECT password_hash FROM accounts WHERE id=?',(self.customer,)).fetchone()[0]))
            self.assertNotIn(result['password'],str(c.execute("SELECT details FROM platform_audit WHERE action='tenant.password_reset'").fetchall()))
            protected=c.execute('SELECT tenant_id,id FROM users WHERE account_id=?',(self.operator,)).fetchone()
        with self.assertRaisesRegex(server.Problem,'Platform administrator'):
            self.route(f"/api/platform/tenants/{protected['tenant_id']}/members/{protected['id']}/password",{'mode':'manual','password':'Invalid-Test!2026','reason':'Should never reset this'})
    def test_email_link_and_archive_restore(self):
        path=f'/api/platform/tenants/{self.tenant}/members/{self.member}/password';links=[]
        with patch.object(platform_admin,'send_recovery_email',side_effect=lambda app,address,link:links.append(link)):
            self.assertEqual(self.route(path,{'mode':'email','reason':'Customer requested email recovery'})['delivery'],'email')
        token=urllib.parse.parse_qs(urllib.parse.urlsplit(links[0]).query)['token'][0]
        self.assertTrue(self.route('/api/password/recover',{'token':token,'password':'Recovered-Test!2026'},False)['ok'])
        with self.assertRaisesRegex(server.Problem,'expired or has already been used'):
            self.route('/api/password/recover',{'token':token,'password':'Another-Test!2026'},False)
        self.assertTrue(self.route(f'/api/platform/tenants/{self.tenant}/rename',{'name':'Renamed Company','reason':'Customer requested a new name'})['ok'])
        self.assertTrue(self.route(f'/api/platform/tenants/{self.tenant}/archive',{'confirm':'Renamed Company','reason':'Customer requested workspace removal'})['ok'])
        with server.connection() as c:
            self.assertEqual(c.execute('SELECT status FROM organizations WHERE id=?',(self.tenant,)).fetchone()[0],'archived')
            self.assertEqual(c.execute('SELECT count(*) FROM sessions WHERE active_tenant_id=?',(self.tenant,)).fetchone()[0],0)
            self.assertEqual(server.billing.organization_capacity(server,c,self.customer)['owned'],0)
        self.assertTrue(self.route(f'/api/platform/tenants/{self.tenant}/restore',{'reason':'Customer requested workspace restoration'})['ok'])

if __name__=='__main__':unittest.main()
