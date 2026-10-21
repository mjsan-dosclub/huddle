"""Permanent public URL ownership and namespaced card routing through WSGI."""
import unittest,concurrent.futures
import test_monetization as fixtures
import server as app
from app import app as web

class PublicURLTests(unittest.TestCase):
    def get_url(self,client=None,card=None):return (client or self.client).get('/api/cards/'+(card or self.card)+'/public-url').json
    def rename(self,name,client=None,card=None):
        client=client or self.client;card=card or self.card;r=self.get_url(client,card)
        return client.put('/api/cards/'+card+'/public-url',json={'card_slug':name,'expected_path':r['path']})
    def namespace(self,name,client=None):
        client=client or self.client;r=client.get('/api/state').json
        return client.put('/api/public-urls/organization',json={'namespace':name,'expected_namespace':r['organization']['slug']})
    def test_same_name_across_tenants_legacy_and_namespace_retention(self):
        old=self.state['user']['slug'];legacy=old.split('/')[-1]
        self.assertEqual(self.namespace('touchmark').status_code,200)
        r=self.rename('mohanraajg');self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(r.json['path'],'touchmark/mohanraajg')
        self.assertEqual(self.namespace('malabar',self.other).status_code,200)
        self.assertEqual(self.rename('mohanraajg',self.other,self.otherstate['cards'][0]['id']).status_code,200)
        for path in (old,legacy,'touchmark/mohanraajg'):
            r=self.client.get('/api/card/'+path);self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['card_id'],self.card)
        self.assertEqual(self.namespace('marina').status_code,200)
        self.assertEqual(self.rename('mohanraajg-sales').status_code,200)
        for path in ('touchmark/mohanraajg','marina/mohanraajg','marina/mohanraajg-sales'):
            self.assertEqual(self.client.get('/api/card/'+path).json['card_id'],self.card)
        self.assertEqual(self.namespace('touchmark',self.other).status_code,409)
        self.assertEqual(self.other.get('/api/cards/'+self.card+'/public-url').status_code,404)
        self.assertEqual(self.client.get('/api/card/touchmark%2Fmohanraajg').status_code,200)
        self.assertEqual(self.client.get('/api/card/touchmark%252Fmohanraajg').status_code,404)
        self.assertEqual(self.client.get('/contact/touchmark/mohanraajg.vcf').status_code,200)
        self.assertIn(b'/c/marina/mohanraajg-sales',self.client.get('/contact/'+legacy+'.vcf').data)
        self.assertEqual(self.client.get('/qr/touchmark/mohanraajg.svg').status_code,200)
        self.assertEqual(self.client.get('/manifest/touchmark/mohanraajg.webmanifest').json['start_url'],'/c/marina/mohanraajg-sales')
        self.assertTrue(self.client.get('/api/share').status_code in (404,405))
        self.assertEqual(self.client.post('/api/share',json={'card_id':self.card}).json['url'],'http://localhost/c/marina/mohanraajg-sales')
    def second_card(self):
        self.grant('enterprise')
        r=self.client.post('/api/cards',json={'persona':'Personal'});self.assertEqual(r.status_code,200,r.json);return r.json['id']
    def test_retired_name_cannot_be_taken_and_parallel_claims_have_one_winner(self):
        other=self.second_card();self.assertEqual(self.rename('mohanraajg').status_code,200)
        self.assertEqual(self.rename('mohanraajg-sales').status_code,200)
        self.assertEqual(self.rename('mohanraajg',card=other).status_code,409)
        r=self.client.get('/api/cards/'+other+'/public-url/availability?name=mohanraajg').json
        self.assertFalse(r['available']);self.assertIn('mohanraajg-2',r['suggestions'])
        # Independent signed-in sessions race for the same path. DB constraints decide.
        a=web.test_client();b=web.test_client()
        for cl in (a,b):self.assertEqual(cl.post('/api/login',json={'email':self.email,'password':self.password}).status_code,200)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda args:self.rename('same-name',*args).status_code,[(a,self.card),(b,other)]))
        self.assertEqual(sorted(results),[200,409])
    def test_validation_stale_updates_and_unpublished_cards(self):
        current=self.get_url()
        for bad in ('ab','Admin','admin','../owner','a/b','mohán','mohan--raaj','a'*61,'mohan%2fraaj'):
            self.assertEqual(self.rename(bad).status_code,400,bad)
        self.assertEqual(self.rename('mohanraajg').status_code,200)
        self.assertEqual(self.client.put('/api/cards/'+self.card+'/public-url',json={'card_slug':'another','expected_path':current['path']}).status_code,409)
        path=self.get_url()['path']
        self.assertEqual(self.client.put('/api/cards/'+self.card,json={'active':False}).status_code,200)
        self.assertEqual(self.client.get('/api/card/'+path).status_code,404)
        self.assertEqual(self.client.put('/api/cards/'+self.card,json={'active':True}).status_code,200)
        with app.connection() as c:c.execute("UPDATE organizations SET status='suspended' WHERE id=?",(self.tenant,))
        self.assertEqual(self.other.get('/api/card/'+path).status_code,404)
    def test_member_permissions_and_disabled_member_public_access(self):
        self.grant('enterprise');address='member@example.com'
        with app.connection() as c:
            mid=app.add_user(c,self.tenant,{'name':'Mohanraaj G','email':address},self.password)
            row=c.execute('SELECT * FROM cards WHERE tenant_id=? AND user_id=?',(self.tenant,mid)).fetchone();cid=row['id']
        cl=web.test_client();self.assertEqual(cl.post('/api/login',json={'email':address,'password':self.password}).status_code,200)
        self.assertEqual(self.rename('mohanraajg',cl,cid).status_code,200)
        self.assertEqual(cl.get('/api/cards/'+self.card+'/public-url').status_code,403)
        r=cl.put('/api/public-urls/organization',json={'namespace':'takeover','expected_namespace':self.state['organization']['slug']});self.assertEqual(r.status_code,403)
        path=self.get_url(cl,cid)['path']
        self.assertEqual(self.client.delete('/api/users/'+mid,json={}).status_code,200)
        self.assertEqual(self.other.get('/api/card/'+path).status_code,404)

for helper in ('setUp','tearDown','register','account','grant'):setattr(PublicURLTests,helper,getattr(fixtures.MonetizationTests,helper))
