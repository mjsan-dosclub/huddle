"""Tenant boundary, role, persona, lead and migration regression tests."""
import base64,hashlib,importlib.util,io,json,os,sqlite3,tempfile,threading,unittest,urllib.error,urllib.request
from pathlib import Path
spec=importlib.util.spec_from_file_location('huddle_server',Path(__file__).resolve().parents[1]/'server.py');app=importlib.util.module_from_spec(spec)
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.modules[spec.name]=app;spec.loader.exec_module(app)
class TenancyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();app.DATA=Path(cls.tmp.name);app.DB=app.DATA/'huddle.sqlite3';app.DEMO=True;app.initialise(True)
        cls.http=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);cls.base='http://127.0.0.1:'+str(cls.http.server_port);os.environ['PUBLIC_BASE_URL']=cls.base
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        cls.a=cls.call('/api/login','POST',{'email':'admin@hello.example','password':'HelloDemo!2026'})[2]
        cls.b=cls.call('/api/register','POST',{'email':'owner-b@example.com','password':'Password!2026','name':'Owner B','organization':'Second organization'})[2]
        cls.sa=cls.call('/api/state',cookie=cls.a)[1];cls.sb=cls.call('/api/state',cookie=cls.b)[1]
        cls.member=cls.call('/api/login','POST',{'email':'sophie.chen@hello.example','password':'HelloDemo!2026'})[2]
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.tmp.cleanup()
    def setUp(self):app.RATE.clear()
    @classmethod
    def call(cls,path,method='GET',data=None,cookie=None):
        headers={'Content-Type':'application/json','Origin':cls.base}
        if cookie:headers['Cookie']=cookie
        req=urllib.request.Request(cls.base+path,data=json.dumps(data).encode() if data is not None else None,method=method,headers=headers)
        try:r=urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:r=e
        raw=r.read();body=json.loads(raw) if 'application/json' in r.headers.get('Content-Type','') else raw
        return r.status,body,r.headers.get('Set-Cookie','').split(';')[0]
    def test_01_state_and_org_switch_boundaries(self):
        self.assertNotEqual(self.sa['organization']['id'],self.sb['organization']['id'])
        self.assertFalse({u['id'] for u in self.sa['team']} & {u['id'] for u in self.sb['team']})
        self.assertEqual(self.call('/api/organizations/switch','POST',{'tenant_id':self.sb['organization']['id']},self.a)[0],403)
        state=self.call('/api/state?tenant_id='+self.sb['organization']['id'],cookie=self.a)[1];self.assertEqual(state['organization']['id'],self.sa['organization']['id'])
    def test_02_cross_tenant_mutations_rejected(self):
        other=self.sb;cases=[('/api/users/'+other['user']['id'],'PUT',{'title':'hacked'}),('/api/cards/'+other['cards'][0]['id'],'PUT',{'persona':'hacked'}),('/api/divisions/'+other['divisions'][0]['id'],'PUT',{'name':'hacked'}),('/api/templates/'+other['templates'][0]['id'],'PUT',{'name':'hacked','layout':'classic'}),('/api/nfc/issue','POST',{'card_id':other['cards'][0]['id']}),('/api/share','POST',{'user_id':other['user']['id']})]
        for path,method,data in cases:self.assertEqual(self.call(path,method,data,self.a)[0],404,path)
    def test_03_foreign_template_and_division_rejected(self):
        self.assertEqual(self.call('/api/users/'+self.sa['user']['id'],'PUT',{'template_id':self.sb['templates'][0]['id']},self.a)[0],404)
        self.assertEqual(self.call('/api/company','PUT',{'default_template':self.sb['templates'][0]['id']},self.a)[0],404)
        self.assertEqual(self.call('/api/analytics?division='+self.sb['divisions'][0]['id'],cookie=self.a)[0],404)
    def test_04_composite_foreign_keys(self):
        with app.connection() as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute('UPDATE cards SET template_id=? WHERE tenant_id=? AND id=?',(self.sb['templates'][0]['id'],self.sa['organization']['id'],self.sa['cards'][0]['id']))
    def test_05_member_rbac_and_locked_persona(self):
        state=self.call('/api/state',cookie=self.member)[1];self.assertNotIn('team',state)
        self.assertEqual(self.call('/api/company','PUT',{'name':'hacked'},self.member)[0],403)
        self.assertEqual(self.call('/api/cards','POST',{'persona':'Personal','name':'bypass'},self.member)[0],403)
        r=self.call('/api/cards','POST',{'persona':'Community'},self.member);self.assertEqual(r[0],200,r)
        own=self.call('/api/cards',cookie=self.member)[1]['cards'];self.assertTrue(all(c['user_id']==state['user']['id'] for c in own))
    def test_06_leads_scoped_to_tenant_and_member(self):
        slug=self.sa['user']['slug'];payload={'name':'Visitor','email':'visitor@example.com','consent':True,'message':'=a formula'}
        self.assertEqual(self.call('/api/exchange/'+slug,'POST',{**payload,'consent':False})[0],400)
        self.assertEqual(self.call('/api/exchange/'+slug,'POST',{**payload,'tenant_id':self.sb['organization']['id']})[0],200)
        self.assertTrue(self.call('/api/leads',cookie=self.a)[1]['leads']);self.assertFalse(self.call('/api/leads',cookie=self.b)[1]['leads']);self.assertFalse(self.call('/api/leads',cookie=self.member)[1]['leads'])
        exported=self.call('/api/leads/export',cookie=self.a)[1];self.assertIn(b"'=a formula",exported)
    def test_07_nfc_stable_and_cross_tenant_management(self):
        r=self.call('/api/nfc/issue','POST',{'user_id':self.sa['user']['id'],'label':'test'},self.a);self.assertEqual(r[0],200)
        assignment=r[1];self.assertEqual(self.call('/api/nfc/confirm','POST',{'id':assignment['id'],'tag_uid':'04aabb'},self.b)[0],404)
        self.assertEqual(self.call('/api/nfc/cards/'+assignment['id'],'PUT',{'card_id':self.sb['cards'][0]['id']},self.a)[0],404)
        self.assertEqual(self.call('/api/nfc/confirm','POST',{'id':assignment['id'],'tag_uid':'04aabb'},self.a)[0],200)
    def test_08_metrics_scoping_and_wallet_scaffold(self):
        self.call('/api/activity','POST',{'slug':self.sa['user']['slug'],'kind':'view','source':'nfc'})
        a=self.call('/api/analytics',cookie=self.a)[1];b=self.call('/api/analytics',cookie=self.b)[1];self.assertGreaterEqual(a['totals']['views'],1);self.assertEqual(b['totals']['views'],0)
        own=self.sa['cards'][0]['id'];foreign=self.sb['cards'][0]['id']
        self.assertEqual(self.call('/api/cards/'+own+'/wallet/apple','POST',{},self.a)[0],503)
        self.assertEqual(self.call('/api/cards/'+foreign+'/wallet/google','POST',{},self.a)[0],404)
    def test_09_csv_onboarding_and_cross_scope_confirmation(self):
        data='Name,Email,Job title,Division\nNew Person,newperson@example.com,Sales,General\n'
        r=self.call('/api/import/preview','POST',{'format':'csv','data':base64.b64encode(data.encode()).decode()},self.a);self.assertEqual(r[0],200,r);self.assertFalse(r[1]['rows'][0]['error'])
        row={**r[1]['rows'][0],'division_id':self.sb['divisions'][0]['id']};result=self.call('/api/import/confirm','POST',{'rows':[row]},self.a)[1];self.assertIn('error',result['results'][0])
    def test_10_account_can_join_and_switch_orgs(self):
        org=self.call('/api/organizations','POST',{'name':'Third workspace'},self.a)[1]['id'];self.assertEqual(self.call('/api/organizations/switch','POST',{'tenant_id':org},self.a)[0],200)
        state=self.call('/api/state',cookie=self.a)[1];self.assertEqual(state['organization']['id'],org);self.assertEqual(len(state['team']),1)
        self.assertEqual(self.call('/api/organizations/switch','POST',{'tenant_id':self.sa['organization']['id']},self.a)[0],200)
    def test_11_whatsapp_upi_and_branded_qr(self):
        card=self.sa['cards'][0];blocks={'whatsapp':{'number':'+91 9876543210','message':'Hello'},'upi':{'id':'demo@upi','name':'Example'}}
        self.assertEqual(self.call('/api/cards/'+card['id'],'PUT',{'blocks':blocks},self.a)[0],200)
        public=self.call('/api/card/'+card['slug'])[1];self.assertEqual(public['blocks']['whatsapp']['url'],'https://wa.me/919876543210?text=Hello')
        self.assertEqual(self.call('/api/company','PUT',{'qr':{'foreground':'#ffffff','background':'#ffffff'}},self.a)[0],400)
        self.assertEqual(self.call('/api/company','PUT',{'qr':{'foreground':'#164e40','background':'#ffffff','frame':'Connect with us'}},self.a)[0],200)
        self.assertIn(b'Connect with us',self.call('/qr/'+card['slug']+'.svg')[1]);self.assertIn(b'<svg',self.call('/upi/'+card['slug']+'.svg')[1])
    def test_12_last_owner_and_member_exports(self):
        self.assertEqual(self.call('/api/users/'+self.sa['user']['id'],'PUT',{'role':'member'},self.a)[0],400)
        member=self.call('/api/state',cookie=self.member)[1];self.assertEqual(self.call('/api/users/'+member['user']['id'],'PUT',{'role':'admin'},self.member)[0],403)
        self.assertEqual(self.call('/api/leads/export',cookie=self.member)[0],200)
    def test_13_assets_are_tenant_owned_and_private_until_published(self):
        from PIL import Image
        stream=io.BytesIO();Image.new('RGB',(8,8),'red').save(stream,format='PNG');url=self.call('/api/upload','POST',{'purpose':'photo','data':base64.b64encode(stream.getvalue()).decode()},self.a)[1]['url']
        self.assertEqual(self.call(url,cookie=self.b)[0],404);self.assertEqual(self.call(url)[0],401)
        self.assertEqual(self.call('/api/company','PUT',{'logo':url},self.b)[0],400)
        self.assertEqual(self.call('/api/company','PUT',{'logo':url},self.a)[0],200);self.assertEqual(self.call(url)[0],200)


    def test_14_existing_account_invitation_preserves_identity(self):
        data={'name':'Owner B joining A','email':'owner-b@example.com','division_id':self.sa['divisions'][0]['id'],'role':'member'}
        r=self.call('/api/invitations','POST',data,self.a);self.assertEqual(r[0],200,r)
        inv=next(x for x in self.call('/api/state',cookie=self.a)[1]['invitations'] if x['id']==r[1]['id']);token=inv['url'].split('token=')[1]
        self.assertEqual(self.call('/api/accept','POST',{'token':token,'password':'Incorrect!2026'})[0],403)
        self.assertEqual(self.call('/api/accept','POST',{'token':token,'password':'Password!2026'})[0],200)
        self.assertEqual(self.call('/api/accept','POST',{'token':token,'password':'Password!2026'})[0],410)
        orgs=self.call('/api/organizations',cookie=self.b)[1]['organizations'];self.assertTrue(any(o['id']==self.sa['organization']['id'] for o in orgs))
    def test_15_stale_tenant_header_rejected(self):
        req=urllib.request.Request(self.base+'/api/state',headers={'Cookie':self.a,'X-Huddle-Tenant':self.sb['organization']['id']})
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
        self.assertEqual(error.exception.code,409)
    def test_16_org_policy_blocks_hidden_and_native_qr_png(self):
        t=self.sa['templates'][0];data={**t['data'],'name':t['name'],'allowed_blocks':[]}
        self.assertEqual(self.call('/api/templates/'+t['id'],'PUT',data,self.a)[0],200)
        self.assertFalse(self.call('/api/card/'+self.sa['user']['slug'])[1]['blocks'])
        self.assertEqual(self.call('/api/cards/'+self.sa['cards'][0]['id'],'PUT',{'blocks':{'upi':{'id':'x@upi'}}},self.a)[0],403)
        png=self.call('/qr/'+self.sa['user']['slug']+'.png')[1];self.assertTrue(png.startswith(b'\x89PNG'))

    def test_17_admin_management_without_owner_escalation(self):
        payload={'name':'Team admin','email':'team.admin@example.com','role':'admin','division_id':self.sa['divisions'][0]['id']}
        r=self.call('/api/invitations','POST',payload,self.a);self.assertEqual(r[0],200)
        inv=next(x for x in self.call('/api/state',cookie=self.a)[1]['invitations'] if x['id']==r[1]['id']);token=inv['url'].split('token=')[1]
        self.assertEqual(self.call('/api/accept','POST',{'token':token,'password':'AdminPass!2026'})[0],200)
        admin=self.call('/api/login','POST',{'email':'team.admin@example.com','password':'AdminPass!2026'})[2];state=self.call('/api/state',cookie=admin)[1]
        self.assertEqual(self.call('/api/company','PUT',{'tagline':'Admin managed'},admin)[0],200)
        self.assertEqual(self.call('/api/users/'+state['user']['id'],'PUT',{'role':'owner'},admin)[0],403)
        self.assertEqual(self.call('/api/users/'+self.sa['user']['id'],'DELETE',{},admin)[0],403)
        self.assertTrue(self.call('/api/leads',cookie=admin)[1]['leads'])
        self.assertEqual(self.call('/api/invitations','POST',{'name':'Forbidden','email':'forbidden@example.com','role':'admin'},admin)[0],403)

class MigrationTests(unittest.TestCase):
    def test_legacy_migration_preserves_links_and_is_idempotent(self):
        import migrate
        original_data,original_db=app.DATA,app.DB
        with tempfile.TemporaryDirectory() as folder:
            try:
                app.DATA=Path(folder);app.DB=app.DATA/'huddle.sqlite3'
                c=sqlite3.connect(app.DATA/'hello.sqlite3')
                c.executescript('''CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE users(id TEXT,email TEXT,password TEXT,role TEXT,slug TEXT,active INTEGER,data TEXT,created INTEGER,disabled INTEGER);CREATE TABLE divisions(id TEXT,name TEXT,data TEXT,created INTEGER);CREATE TABLE templates(id TEXT,name TEXT,data TEXT,created INTEGER);CREATE TABLE nfc_cards(id TEXT,user_id TEXT,token TEXT,label TEXT,tag_hash TEXT,active INTEGER,created INTEGER,written INTEGER);''')
                brand={'name':'Legacy Org','default_template':'classic','allow_employee_banners':True,'images':[],'logo':'','logo_scale':100,'background':'#164e40','tagline':'','description':'','website':'','email_domain':''}
                c.execute('INSERT INTO settings VALUES(?,?)',('company',app.dump(brand)));c.execute('INSERT INTO divisions VALUES(?,?,?,?)',('sales','Sales','{}',1));c.execute('INSERT INTO templates VALUES(?,?,?,?)',('classic','Classic',app.dump({'layout':'classic','accent':'#164e40','enabled':True,'visible_fields':app.FIELDS,'locked_fields':[],'personal_links_allowed':True}),1));c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?)',('legacy-user','legacy@example.com',app.password_hash('Password!2026'),'admin','old-card-slug',1,app.dump({'name':'Original','division_id':'sales','template_id':'classic'}),1,None));c.execute('INSERT INTO nfc_cards VALUES(?,?,?,?,?,?,?,?)',('tag','legacy-user','unchanged-token','Original',None,1,1,None));c.commit();c.close()
                before=hashlib.sha256((app.DATA/'hello.sqlite3').read_bytes()).hexdigest();migrate.apply(app);migrate.apply(app)
                with app.connection() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM organizations').fetchone()[0],1);self.assertEqual(db.execute('SELECT slug FROM cards').fetchone()[0],'old-card-slug');self.assertEqual(db.execute('SELECT token FROM nfc_cards').fetchone()[0],'unchanged-token');self.assertEqual(db.execute('SELECT role FROM users').fetchone()[0],'owner');self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
                self.assertEqual(hashlib.sha256((app.DATA/'hello.sqlite3').read_bytes()).hexdigest(),before)
            finally:app.DATA,app.DB=original_data,original_db

if __name__=='__main__':unittest.main()
