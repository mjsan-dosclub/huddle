"""Deployment adapter, private storage and fail-closed configuration checks."""
import base64,io,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import database,object_storage
from app import app,configuration_errors

class DeploymentTests(unittest.TestCase):
    def test_vercel_cannot_fall_back_to_local_database_or_encryption_key(self):
        with patch.dict(os.environ,{'VERCEL':'1'},clear=True):
            self.assertIn('DATABASE_URL',configuration_errors())
            with self.assertRaises(RuntimeError):database.connection('/tmp/never-create.sqlite3')
            self.assertEqual(app.test_client().get('/').status_code,503)
    def test_sql_translation_preserves_literals_and_governance_placeholders(self):
        self.assertEqual(database.sql("SELECT '?' FROM cards WHERE tenant_id=? AND persona LIKE '50%'"),"SELECT '?' FROM cards WHERE tenant_id=%s AND persona LIKE '50%%'")
        self.assertEqual(database.sql('BEGIN IMMEDIATE'),'BEGIN ISOLATION LEVEL SERIALIZABLE')
        self.assertIn('ON CONFLICT DO NOTHING',database.sql('INSERT OR IGNORE INTO assets VALUES(?)'))
    def test_storage_keys_cannot_escape_tenant_prefix_or_traverse(self):
        for key in ['/media/../../secret.png','https://evil.test/x','/media/other/file.png','/static/app.js']:
            with self.assertRaises(ValueError):object_storage.object_path(key)
        self.assertEqual(object_storage.object_path('/media/'+'a'*24+'/'+'b'*64+'.png'),'a'*24+'/'+'b'*64+'.png')
    def test_storage_uses_private_object_endpoint_and_server_only_headers(self):
        key='/media/'+'a'*24+'/'+'b'*64+'.png'
        with patch.dict(os.environ,{'SUPABASE_URL':'https://project.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'fixture-server-only'},clear=True):
            with patch.object(object_storage.urllib.request,'urlopen',return_value=io.BytesIO(b'fixture-image')) as send:
                self.assertEqual(object_storage.request('GET',key),b'fixture-image')
                request=send.call_args.args[0]
                self.assertNotIn('/public/',request.full_url);self.assertEqual(request.get_header('Authorization'),'Bearer fixture-server-only')
    def test_serverless_limit_rejected_before_routing_or_database_access(self):
        with patch.dict(os.environ,{},clear=True):
            response=app.test_client().post('/api/upload',data=b'x'*4_400_001,content_type='application/json')
        self.assertEqual(response.status_code,413)
        self.assertIn('3 MB',response.json['error'])
    def test_transaction_failure_discards_success_and_session_cookie(self):
        import server
        from contextlib import contextmanager
        @contextmanager
        def fail_at_commit():
            yield object()
            raise RuntimeError('Fixture commit failure')
        def successful_route(handler,c,method,path):
            handler.send(200,{'ok':True},headers={'Set-Cookie':'hello_session=must-not-escape'})
        with patch.dict(os.environ,{},clear=True),patch.object(server,'connection',fail_at_commit),patch.object(server.Handler,'route',successful_route):
            # Provide execute so the transaction BEGIN succeeds before the fixture fails.
            from unittest.mock import MagicMock
            @contextmanager
            def failing_connection():
                yield MagicMock()
                raise RuntimeError('Fixture commit failure')
            with patch.object(server,'connection',failing_connection):response=app.test_client().get('/')
        self.assertEqual(response.status_code,500);self.assertNotIn('Set-Cookie',response.headers)
    def test_bulk_email_delivery_uses_one_mocked_batch_request(self):
        import server,json
        from unittest.mock import MagicMock
        invitations=[{'id':str(i),'email':'fixture'+str(i)+'@example.com','token':'fixture-token'} for i in range(2)]
        with patch.dict(os.environ,{'RESEND_API_KEY':'fixture','RESEND_FROM':'fixture@example.com','PUBLIC_BASE_URL':'https://example.com'}),patch.object(server,'DEMO',False),patch.object(server,'company',return_value={'name':'Fixture'}),patch.object(server.urllib.request,'urlopen',return_value=io.BytesIO(b'{"data":[{"id":"one"},{"id":"two"}]}')) as send:
            c=MagicMock();server.send_invites(c,'fixture-tenant',invitations)
            self.assertEqual(send.call_count,1);request=send.call_args.args[0]
            self.assertTrue(request.full_url.endswith('/emails/batch'));self.assertEqual(len(json.loads(request.data)),2)
            self.assertEqual(c.execute.call_count,2)
