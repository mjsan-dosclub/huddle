"""Vercel WSGI entrypoint, sharing the tested web/native API and session rules."""
import base64,io,os
from email.message import Message
from flask import Flask,Response,request
import server
import database

app=Flask(__name__,static_folder=None)
app.config['MAX_CONTENT_LENGTH']=4_400_000

def configuration_errors():
    errors=[]
    if not os.environ.get('VERCEL'):return errors
    for key in ('DATABASE_URL','SUPABASE_URL','SUPABASE_SERVICE_ROLE_KEY','HUDDLE_ENCRYPTION_KEY','PUBLIC_BASE_URL'):
        if not os.environ.get(key):errors.append(key)
    for key in ('PUBLIC_BASE_URL','HUDDLE_APP_ORIGIN','HUDDLE_PUBLIC_ORIGIN','SUPABASE_URL'):
        value=os.environ.get(key)
        if value and not value.startswith('https://'):errors.append(key+' must use HTTPS')
    try:
        if len(base64.urlsafe_b64decode(os.environ.get('HUDDLE_ENCRYPTION_KEY','')))!=32:errors.append('HUDDLE_ENCRYPTION_KEY must encode 32 bytes')
    except ValueError:errors.append('HUDDLE_ENCRYPTION_KEY format')
    if os.environ.get('DATABASE_URL'):
        try:
            from psycopg.conninfo import conninfo_to_dict
            options=conninfo_to_dict(os.environ['DATABASE_URL'])
            if options.get('sslmode') not in ('require','verify-ca','verify-full'):errors.append('DATABASE_URL must require TLS')
            if not options.get('user','').split('.')[0]=='huddle_backend':errors.append('DATABASE_URL must use huddle_backend')
        except Exception:errors.append('DATABASE_URL format')
    return list(dict.fromkeys(errors))

class RequestHandler(server.Handler):
    def __init__(self):
        self.path=request.full_path.rstrip('?');self.command=request.method
        self.headers=Message()
        for k,v in request.headers.items():self.headers[k]=v
        identity=request.remote_addr or 'unknown'
        # Vercel overwrites X-Forwarded-For at its trusted edge.
        if os.environ.get('VERCEL'):identity=request.headers.get('X-Forwarded-For',identity).split(',')[0].strip()
        self.client_address=(identity,0);self.rfile=io.BytesIO(request.get_data());self.response=None
    def send(self,status,content,mime='application/json',headers=None):
        raw=server.dump(content) if mime=='application/json' or mime.endswith('+json') else content
        self.response=Response(raw,status=status,content_type=mime,headers=headers)
        self.response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"})

@app.route('/',defaults={'path':''},methods=['GET','HEAD','POST','PUT','DELETE'])
@app.route('/<path:path>',methods=['GET','HEAD','POST','PUT','DELETE'])
def dispatch(path):
    if configuration_errors():return {'error':'Server configuration incomplete. See deployment environment settings.'},503
    handler=RequestHandler()
    handler.handle_safe('GET' if request.method=='HEAD' else request.method)
    # Responses are buffered until the database transaction has committed.
    return handler.response if handler.response is not None else Response(status=204)

@app.errorhandler(413)
def too_large(error):return {'error':'Request too large. Use images smaller than 3 MB and workbooks smaller than 2 MB.'},413
