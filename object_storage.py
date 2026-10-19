"""Private Supabase bucket. Every read still passes through tenant/visibility checks."""
import os,re,urllib.parse,urllib.request

def remote():return bool(os.environ.get('SUPABASE_URL'))
def object_path(key):
    if not re.fullmatch(r'/media/(?:[a-f0-9]{24}/)?[a-f0-9]{64}\.png',key):raise ValueError('Invalid asset key')
    return key.removeprefix('/media/')
def request(method,key,data=None):
    project=os.environ['SUPABASE_URL'].rstrip('/')
    bucket=os.environ.get('SUPABASE_STORAGE_BUCKET','huddle-assets')
    url=project+'/storage/v1/object/'+urllib.parse.quote(bucket,safe='')+'/'+object_path(key)
    token=os.environ['SUPABASE_SERVICE_ROLE_KEY']
    headers={'Authorization':'Bearer '+token,'apikey':token}
    if data is not None:headers.update({'Content-Type':'image/png','x-upsert':'true'})
    req=urllib.request.Request(url,data=data,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=15) as response:
        # Assets served via Functions must also respect the response payload limit.
        raw=response.read(3*1024*1024+1)
        if len(raw)>3*1024*1024:raise ValueError('Stored asset exceeds size limit')
        return raw
def write(app,key,raw):
    object_path(key)
    if remote():request('POST',key,raw);return
    if os.environ.get('VERCEL'):raise RuntimeError('Supabase Storage is required on Vercel')
    path=app.DATA/key.lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
def read(app,key):
    object_path(key)
    if remote():return request('GET',key)
    if os.environ.get('VERCEL'):raise RuntimeError('Supabase Storage is required on Vercel')
    return (app.DATA/key.lstrip('/')).read_bytes()
