"""Sales-only access, workflow concurrency, filtering and export boundaries."""
import csv,io,json,unittest
import test_monetization as fixtures
import server as app

class SalesWorkflowTests(unittest.TestCase):
    # Reuse fixture helpers without inheriting all monetization test methods.
    def enquiry(self,email='buyer@example.com'):
        r=self.client.post('/api/public/enterprise-quotes',json={'name':'Meera','email':email,'company':'Malabar Studio','seats':25,'consent':True})
        self.assertEqual(r.status_code,200,r.json);return r.json['reference']
    def enable_agent(self,client=None):
        email=self.otherstate['user']['email']
        r=self.client.post('/api/sales/team',json={'email':email,'active':True,'reason':'Assigned sales team access'});self.assertEqual(r.status_code,200,r.json)
        return self.account(email)
    def test_sales_scope_filters_timeline_and_export(self):
        eid=self.enquiry();other=self.enquiry('second@example.com');self.platform();aid=self.enable_agent()
        self.assertEqual(self.other.get('/api/sales/enquiries').json['total'],0)
        v=self.client.get('/api/sales/enquiries/'+eid).json['enquiry']['version']
        self.assertEqual(self.client.post('/api/sales/enquiries/'+eid+'/assign',json={'account_id':aid,'version':v}).status_code,200)
        self.assertEqual(self.other.get('/api/sales/enquiries').json['total'],1)
        self.assertEqual(self.other.get('/api/sales/enquiries/'+other).status_code,404)
        self.assertEqual(self.other.get('/api/platform/prices').status_code,404)
        self.assertEqual(self.other.get('/api/sales/team').status_code,404)
        r=self.other.get('/api/sales/enquiries/'+eid).json;v=r['enquiry']['version']
        self.assertEqual(self.other.post('/api/sales/enquiries/'+eid+'/open',json={'version':v}).status_code,200)
        v=self.other.get('/api/sales/enquiries/'+eid).json['enquiry']['version']
        activity={'version':v,'mode':'phone','outcome':'callback','stage':'follow-up','note':'Called; asked to follow up tomorrow','follow_up_at':app.now()+86400}
        self.assertEqual(self.other.post('/api/sales/enquiries/'+eid+'/activity',json=activity).status_code,200)
        self.assertEqual(self.other.post('/api/sales/enquiries/'+eid+'/activity',json=activity).status_code,409)
        history=self.other.get('/api/sales/enquiries/'+eid).json
        self.assertEqual(history['event_total'],4);self.assertEqual([e['ordinal'] for e in history['events']],[4,3,2,1])
        self.assertEqual(self.other.get('/api/sales/enquiries?stage=follow-up&due=upcoming').json['total'],1)
        self.assertEqual(self.other.get('/api/sales/enquiries?stage=new').json['total'],0)
        exported=self.other.get('/api/sales/export');self.assertEqual(exported.status_code,200)
        rows=list(csv.reader(io.StringIO(exported.data.decode())))
        self.assertEqual(len(rows),2);self.assertEqual(rows[1][0],eid)
        self.assertEqual(self.other.post('/api/sales/enquiries/'+eid+'/assign',json={'version':history['enquiry']['version'],'account_id':None}).status_code,404)
        self.assertEqual(self.client.post('/api/sales/team',json={'email':self.otherstate['user']['email'],'active':False,'reason':'Remove sales team access'}).status_code,200)
        self.assertEqual(self.other.get('/api/sales/enquiries').status_code,404)
    def test_activity_validation_and_closed_followup(self):
        eid=self.enquiry();self.platform();url='/api/sales/enquiries/'+eid+'/activity';v=1
        base={'version':v,'mode':'phone','outcome':'no-answer','stage':'follow-up','note':'No answer, retry tomorrow','follow_up_at':None}
        for change in ({},{'follow_up_at':True},{'stage':'not-a-stage'},{'mode':'unknown'},{'outcome':'unknown'}):
            self.assertEqual(self.client.post(url,json={**base,**change}).status_code,400)
        self.assertEqual(self.client.post(url,json={**base,'stage':'lost','outcome':'not-interested','follow_up_at':app.now()+100}).status_code,200)
        detail=self.client.get('/api/sales/enquiries/'+eid).json['enquiry'];self.assertIsNone(detail['follow_up_at']);self.assertEqual(detail['stage'],'lost')
        self.assertEqual(self.client.get('/api/sales/enquiries?stage=lost').json['total'],1)
    def test_csv_formulas_are_neutralized_and_invalid_filters_fail(self):
        eid=self.enquiry();self.platform()
        with app.connection() as c:c.execute('UPDATE enterprise_quote_requests SET company=? WHERE id=?',('=HYPERLINK("example")',eid))
        rows=list(csv.reader(io.StringIO(self.client.get('/api/sales/export').data.decode())))
        self.assertTrue(rows[1][4].startswith("'="))
        for q in ('stage=bad','kind=bad','due=bad','page=-1','from=bad'):
            self.assertEqual(self.client.get('/api/sales/enquiries?'+q).status_code,400)

for _name in ('setUp','tearDown','register','account','platform'):
    setattr(SalesWorkflowTests,_name,getattr(fixtures.MonetizationTests,_name))
