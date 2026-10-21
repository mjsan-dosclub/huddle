"""Platform sales workflow; global operators or explicitly assigned sales agents only."""
import csv,io,json,re,datetime
import platform_admin,sales_auth

STAGES={'new':'New','opened':'Opened','contacted':'Contacted','follow-up':'Follow-up','demo':'Demo requested','won':'Won / onboarded','lost':'Closed / not interested'}
MODES={'phone':'Phone call','email':'Email','whatsapp':'WhatsApp','meeting':'Meeting','internal':'Internal note'}
OUTCOMES={'contacted':'Spoke to customer','no-answer':'Did not pick up','callback':'Asked for a follow-up','not-interested':'Not interested','demo-requested':'Asked for a demo','demo-arranged':'Demo arranged','onboarded':'Deal closed / onboarded','note':'Note'}

def identity(app,h,c):
    try:return {**platform_admin.identity(app,h,c),'manager':True}
    except app.Problem:pass
    staff=sales_auth.identity(app,h,c)
    if staff:return staff
    actor=h.actor(c)
    account=c.execute('SELECT a.id,a.email FROM sales_agent_grants g JOIN accounts a ON a.id=g.account_id WHERE g.account_id=? AND g.active=1 AND a.disabled IS NULL',(actor['account_id'],)).fetchone()
    if not account:raise app.Problem('Not found.',404)
    if c.execute('SELECT 1 FROM sales_staff_credentials WHERE account_id=?',(account['id'],)).fetchone():raise app.Problem('Use your internal sales login at /sales/login.',401)
    return {**dict(account),'manager':False,'auth_kind':'customer','must_change':0}

def number(app,value,default=0,maximum=1000000):
    try:n=int(value)
    except (TypeError,ValueError):raise app.Problem('Invalid page or date filter.')
    if not 0<=n<=maximum:raise app.Problem('Invalid page or date filter.')
    return n

def criteria(app,h,actor):
    q={k:v[0] for k,v in h.query().items()};where=[];args=[]
    if not actor['manager']:where.append('q.assigned_to=?');args.append(actor['id'])
    if q.get('q'):
        where.append('(LOWER(q.name) LIKE ? OR LOWER(q.company) LIKE ? OR LOWER(q.email) LIKE ?)');args.extend(['%'+app.text(q['q'],160).lower()+'%']*3)
    if q.get('stage'):
        if q['stage'] not in STAGES:raise app.Problem('Invalid sales stage.')
        where.append('q.stage=?');args.append(q['stage'])
    if q.get('assignee') and actor['manager']:
        if q['assignee']=='unassigned':where.append('q.assigned_to IS NULL')
        else:where.append('q.assigned_to=?');args.append(q['assignee'])
    if q.get('kind'):
        if q['kind'] not in ('nfc','enterprise'):raise app.Problem('Invalid enquiry type.')
        # JSON text is portable across SQLite and PostgreSQL; historical empty details mean Enterprise.
        where.append("q.details LIKE ?" if q['kind']=='nfc' else "q.details NOT LIKE ?");args.append('%"request_type": "nfc"%')
    for key,op in (('from','>='),('to','<')):
        if q.get(key):
            try:stamp=int(datetime.datetime.strptime(q[key],'%Y-%m-%d').replace(tzinfo=datetime.timezone.utc).timestamp())+(86400 if key=='to' else 0)
            except ValueError:raise app.Problem('Use valid date filters.')
            where.append('q.created'+op+'?');args.append(stamp)
    if q.get('due'):
        if q['due'] not in ('overdue','upcoming','none'):raise app.Problem('Invalid follow-up filter.')
        where.append("q.stage NOT IN ('won','lost')")
        if q['due']=='none':where.append('q.follow_up_at IS NULL')
        else:where.append('q.follow_up_at IS NOT NULL AND q.follow_up_at'+('<' if q['due']=='overdue' else '>=')+'?');args.append(app.now())
    return (' WHERE '+' AND '.join(where) if where else ''),args,q

def record(app,c,enquiry,actor,kind,stage,note='',mode='',outcome='',follow=None):
    ordinal=c.execute('SELECT COALESCE(MAX(ordinal),0)+1 FROM sales_enquiry_events WHERE enquiry_id=?',(enquiry,)).fetchone()[0]
    c.execute('INSERT INTO sales_enquiry_events VALUES(?,?,?,?,?,?,?,?,?,?,?)',(app.uid(),enquiry,actor,kind,mode,outcome,note,stage,follow,app.now(),ordinal))

def scoped(app,c,actor,eid):
    row=c.execute('SELECT q.*,a.email AS assignee_email FROM enterprise_quote_requests q LEFT JOIN accounts a ON a.id=q.assigned_to WHERE q.id=?'+('' if actor['manager'] else ' AND q.assigned_to=?'),(eid,) if actor['manager'] else (eid,actor['id'])).fetchone()
    if not row:raise app.Problem('Enquiry not found.',404)
    return dict(row)

def routes(app,h,c,method,path):
    matched,result=sales_auth.public_routes(app,h,c,method,path)
    if matched:return True,result
    if path=='/sales' or path.startswith('/sales/'):
        if method!='GET':return False,None
        try:identity(app,h,c)
        except app.Problem as error:
            if error.code==401:
                h.send(302,b'','text/plain',{'Location':'/sales/login'});return True,None
            raise
        h.send(200,(app.ROOT/'static/sales.html').read_bytes(),'text/html; charset=utf-8');return True,None
    if not path.startswith('/api/sales'):return False,None
    actor=identity(app,h,c)
    if path=='/api/sales/access' and method=='GET':return True,{'email':actor['email'],'name':actor.get('name',actor['email']),'manager':actor['manager'],'auth_kind':actor.get('auth_kind','operator'),'must_change':bool(actor.get('must_change')),'stages':STAGES,'modes':MODES,'outcomes':OUTCOMES}
    matched,result=sales_auth.change_password(app,h,c,actor,method,path)
    if matched:return True,result
    if actor.get('must_change'):
        h.send(403,{'error':'Change your initial sales password before viewing enquiries.','password_change_required':True});return True,None
    matched,result=sales_auth.manager_routes(app,h,c,actor,method,path)
    if matched:return True,result
    if path=='/api/sales/team':
        if not actor['manager']:raise app.Problem('Not found.',404)
        if method=='GET':return True,{'login_url':app.base_url()+'/sales/login','email_enabled':False,'agents':[dict(r) for r in c.execute('SELECT g.account_id,g.active,a.email,s.name,s.version,s.must_change FROM sales_agent_grants g JOIN accounts a ON a.id=g.account_id LEFT JOIN sales_staff_credentials s ON s.account_id=g.account_id ORDER BY a.email')]}
        if method=='POST':
            d=h.body();reason=app.text(d.get('reason'),1000)
            if len(reason)<10 or type(d.get('active'))!=bool:raise app.Problem('Enter a reason and valid access state.')
            account=c.execute('SELECT id,email FROM accounts WHERE LOWER(email)=? AND disabled IS NULL',(app.text(d.get('email'),254).lower(),)).fetchone()
            if not account:raise app.Problem('Use Create sales colleague to set up this internal login.')
            c.execute('INSERT INTO sales_agent_grants VALUES(?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET active=excluded.active,granted_by=excluded.granted_by',(account['id'],int(d['active']),app.now(),actor['id']))
            if not d['active']:c.execute('DELETE FROM sales_staff_sessions WHERE account_id=?',(account['id'],))
            platform_admin.audit(app,c,actor['id'],'sales.agent_access',reason=reason,details={'account':account['id'],'email':account['email'],'active':d['active']})
            return True,{'ok':True}
    if path in ('/api/sales/enquiries','/api/sales/export') and method=='GET':
        where,args,q=criteria(app,h,actor)
        select='SELECT q.*,a.email AS assignee_email FROM enterprise_quote_requests q LEFT JOIN accounts a ON a.id=q.assigned_to'
        total=c.execute('SELECT count(*) FROM enterprise_quote_requests q'+where,args).fetchone()[0]
        if path.endswith('/export'):
            if total>5000:raise app.Problem('Narrow the filters to export at most 5,000 records.')
            h.limited('sales-export',10)
            rows=c.execute(select+where+' ORDER BY q.created DESC,q.id DESC',args).fetchall()
            out=io.StringIO();w=csv.writer(out);w.writerow(['Reference','Received (UTC)','Name','Email','Company','Users','Type','Stage','Assigned to','Next follow-up (UTC)','Phone','Location','NFC quantity','Message'])
            def safe(v):
                s=str(v or '')
                return "'"+s if s.lstrip().startswith(('=','+','-','@','\t','\r')) else s
            def dt(v):return datetime.datetime.fromtimestamp(v,datetime.timezone.utc).isoformat() if v else ''
            for r in rows:
                d=json.loads(r['details']);w.writerow([safe(v) for v in [r['id'],dt(r['created']),r['name'],r['email'],r['company'],r['seats'],d.get('request_type','enterprise'),STAGES[r['stage']],r['assignee_email'],dt(r['follow_up_at']),d.get('phone'),d.get('location'),d.get('nfc_quantity'),r['message']]])
            platform_admin.audit(app,c,actor['id'],'sales.export',reason='Sales enquiry export',details={'count':total,'scope':'all' if actor['manager'] else 'assigned'})
            h.send(200,out.getvalue(),'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="huddle-sales-enquiries.csv"'});return True,None
        page=number(app,q.get('page',0));rows=[dict(r) for r in c.execute(select+where+' ORDER BY q.created DESC,q.id DESC LIMIT 25 OFFSET ?',args+[page*25])]
        for row in rows:row['details']=json.loads(row['details'])
        return True,{'requests':rows,'total':total,'page':page,'page_size':25}
    match=re.fullmatch(r'/api/sales/enquiries/([a-zA-Z0-9-]+)(?:/(open|activity|assign))?',path)
    if match:
        eid,action=match.groups();row=scoped(app,c,actor,eid)
        if method=='GET' and not action:
            page=number(app,h.query().get('event_page',['0'])[0]);events=[dict(r) for r in c.execute('SELECT e.*,a.email AS actor_email FROM sales_enquiry_events e LEFT JOIN accounts a ON a.id=e.actor_id WHERE e.enquiry_id=? ORDER BY e.ordinal DESC LIMIT 50 OFFSET ?',(eid,page*50))]
            row['details']=json.loads(row['details'])
            return True,{'enquiry':row,'events':events,'event_page':page,'event_total':c.execute('SELECT count(*) FROM sales_enquiry_events WHERE enquiry_id=?',(eid,)).fetchone()[0]}
        if method=='POST' and action:
            h.limited('sales-write',80);d=h.body()
            if type(d.get('version'))!=int or d['version']!=row['version']:raise app.Problem('This enquiry changed. Reload before saving.',409)
            stage=row['stage'];follow=row['follow_up_at'];assignee=row['assigned_to'];opened=row['opened_at'];note='';mode='';outcome=''
            if action=='open':
                if opened:return True,{'ok':True}
                opened=app.now();stage='opened' if stage=='new' else stage;note='Enquiry opened'
            elif action=='assign':
                if not actor['manager']:raise app.Problem('Not found.',404)
                assignee=d.get('account_id') or None
                if assignee and not c.execute('SELECT 1 FROM sales_agent_grants WHERE account_id=? AND active=1',(assignee,)).fetchone():raise app.Problem('Select an active sales colleague.')
                note='Assigned to '+c.execute('SELECT email FROM accounts WHERE id=?',(assignee,)).fetchone()[0] if assignee else 'Assignment removed'
            else:
                note=app.text(d.get('note'),2000);stage=d.get('stage');mode=d.get('mode');outcome=d.get('outcome');follow=d.get('follow_up_at')
                if not 3<=len(note)<=2000 or stage not in STAGES or mode not in MODES or outcome not in OUTCOMES:raise app.Problem('Add a note and select valid activity details.')
                if follow is not None and (type(follow)!=int or not 0<follow<4102444800):raise app.Problem('Choose a valid next follow-up date.')
                if stage in ('follow-up','demo') and follow is None:raise app.Problem('Set the next follow-up date for this stage.')
                if stage in ('won','lost'):follow=None
            updated=c.execute('UPDATE enterprise_quote_requests SET stage=?,assigned_to=?,follow_up_at=?,opened_at=?,version=version+1,updated=? WHERE id=? AND version=?',(stage,assignee,follow,opened,app.now(),eid,row['version']))
            if updated.rowcount!=1:raise app.Problem('This enquiry changed. Reload before saving.',409)
            record(app,c,eid,actor['id'],action,stage,note,mode,outcome,follow)
            platform_admin.audit(app,c,actor['id'],'sales.'+action,reason='Sales enquiry '+action,details={'enquiry':eid,'stage':stage})
            return True,{'ok':True}
    raise app.Problem('Not found.',404)
