"""Internal staff provisioning, password realms, session revocation and assignment scopes."""
import json,unittest,secrets
import test_monetization as fixtures
import server as app
from app import app as web

class SalesStaffAuthTests(unittest.TestCase):
    def provision(self,email=None,must_change=False):
        address=email or 'arun-'+secrets.token_hex(4)+'@huddleapp.in'
        r=self.client.post('/api/sales/team/provision',json={'name':'Arun Kumar','email':address,'password':'InitialSales!2026','confirm_password':'InitialSales!2026','must_change':must_change,'delivery':'copy','reason':'Official sales team onboarding'})
        self.assertEqual(r.status_code,200,r.json);return address,r
    def login_staff(self,email,password='InitialSales!2026',client=None):
        cl=client or web.test_client();r=cl.post('/api/sales/auth/login',json={'email':email,'password':password});self.assertEqual(r.status_code,200,r.json);return cl
    def test_no_customer_signup_and_no_secret_disclosure(self):
        self.assertEqual(self.other.post('/api/sales/team/provision',json={}).status_code,404)
        self.platform();address,r=self.provision()
        self.assertNotIn('InitialSales',json.dumps(r.json));self.assertEqual(r.json['login_url'],'http://localhost/sales/login');self.assertFalse(r.json['email_enabled'])
        aid=self.account(address)
        with app.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM users WHERE account_id=?',(aid,)).fetchone()[0],0)
            stored=c.execute('SELECT password_hash FROM sales_staff_credentials WHERE account_id=?',(aid,)).fetchone()[0]
            self.assertNotEqual(stored,'InitialSales!2026');self.assertTrue(app.password_matches('InitialSales!2026',stored))
            self.assertNotIn('InitialSales',json.dumps([dict(x) for x in c.execute('SELECT * FROM platform_audit')]))
        staff=self.login_staff(address);self.assertEqual(staff.get('/sales').status_code,200)
        self.assertEqual(staff.get('/api/sales/access').json['auth_kind'],'staff')
        self.assertEqual(staff.get('/api/sales/enquiries').json['total'],0)
        self.assertEqual(staff.get('/api/state').status_code,401)
        self.assertEqual(staff.get('/api/platform/prices').status_code,404)
        self.assertEqual(staff.post('/api/sales/team/provision',json={}).status_code,404)
        self.assertEqual(web.test_client().get('/sales').status_code,302)
        login=web.test_client().get('/sales/login')
        self.assertEqual(login.status_code,200)
        for css in ('app.css','workspace-theme.css','platform.css','sales.css'):
            self.assertIn(('/static/'+css).encode(),login.data)
        self.assertEqual(web.test_client().get('/sales/playbook').status_code,302)
        self.assertEqual(staff.get('/sales/playbook').status_code,200)
        bad=web.test_client().post('/api/sales/auth/login',json={'email':address,'password':'wrong'});self.assertEqual(bad.status_code,401)
        self.assertEqual(web.test_client().post('/api/login',json={'email':address,'password':'InitialSales!2026'}).status_code,401)
        item={'name':'Meera','email':'buyer@example.com','company':'Malabar','seats':25,'consent':True}
        eid=self.client.post('/api/public/enterprise-quotes',json=item).json['reference'];other=self.client.post('/api/public/enterprise-quotes',json=item).json['reference']
        self.assertEqual(self.client.post('/api/sales/enquiries/'+eid+'/assign',json={'account_id':aid,'version':1}).status_code,200)
        self.assertEqual(staff.get('/api/sales/enquiries').json['total'],1)
        self.assertEqual(staff.get('/api/sales/enquiries/'+other).status_code,404)
    def test_password_change_and_manager_reset_invalidate_every_session(self):
        self.platform();address,_=self.provision(must_change=True);aid=self.account(address)
        first=self.login_staff(address);second=self.login_staff(address)
        self.assertTrue(first.get('/api/sales/access').json['must_change'])
        self.assertEqual(first.get('/api/sales/enquiries').status_code,403)
        payload={'current':'wrong','password':'ChangedSales!2026','confirm_password':'ChangedSales!2026'}
        self.assertEqual(first.post('/api/sales/auth/password',json=payload).status_code,403)
        payload['current']='InitialSales!2026';self.assertEqual(first.post('/api/sales/auth/password',json=payload).status_code,200)
        self.assertEqual(first.get('/api/sales/access').status_code,401);self.assertEqual(second.get('/api/sales/access').status_code,401)
        first=self.login_staff(address,'ChangedSales!2026');self.assertFalse(first.get('/api/sales/access').json['must_change'])
        agent=next(x for x in self.client.get('/api/sales/team').json['agents'] if x['account_id']==aid)
        reset={'password':'ManagerReset!2026','confirm_password':'ManagerReset!2026','version':agent['version'],'must_change':False,'reason':'Requested internal password recovery'}
        self.assertEqual(first.post('/api/sales/team/'+aid+'/password',json=reset).status_code,404)
        self.assertEqual(self.client.post('/api/sales/team/'+aid+'/password',json=reset).status_code,200)
        self.assertEqual(self.client.post('/api/sales/team/'+aid+'/password',json=reset).status_code,409)
        self.assertEqual(first.get('/api/sales/access').status_code,401)
        third=self.login_staff(address,'ManagerReset!2026')
        self.assertEqual(third.post('/api/sales/auth/logout',json={}).status_code,200);self.assertEqual(third.get('/api/sales/access').status_code,401)
    def test_customer_password_is_not_reset_and_revocation_does_not_resurrect_sessions(self):
        self.platform();address=self.otherstate['user']['email'];self.provision(address)
        aid=self.account(address);staff=self.login_staff(address)
        with app.connection() as c:self.assertTrue(app.password_matches(self.password,c.execute('SELECT password_hash FROM accounts WHERE id=?',(aid,)).fetchone()[0]))
        self.assertEqual(self.other.get('/api/state').status_code,200)
        self.assertEqual(self.other.get('/api/sales/access').status_code,401)
        for active in (False,True):
            self.assertEqual(self.client.post('/api/sales/team',json={'email':address,'active':active,'reason':'Sales colleague access maintenance'}).status_code,200)
            self.assertEqual(staff.get('/api/sales/access').status_code,401)
        self.login_staff(address)
    def test_provision_validation_and_platform_protection(self):
        self.platform();base={'name':'Arun','email':'new@huddleapp.in','password':'InitialSales!2026','confirm_password':'InitialSales!2026','reason':'Official sales colleague setup'}
        for update in ({'password':'short','confirm_password':'short'},{'confirm_password':'different'},{'delivery':'email'},{'must_change':'yes'},{'name':''}):
            self.assertEqual(self.client.post('/api/sales/team/provision',json={**base,**update}).status_code,400)
        self.assertEqual(self.client.post('/api/sales/team/provision',json={**base,'email':self.email}).status_code,409)
        self.provision(base['email'])
        self.assertEqual(self.client.post('/api/sales/team/provision',json=base).status_code,409)

for helper in ('setUp','tearDown','register','account','platform'):setattr(SalesStaffAuthTests,helper,getattr(fixtures.MonetizationTests,helper))
