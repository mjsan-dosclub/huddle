"""Tenant entitlements and Razorpay billing. Access is derived on every request."""
import base64,hashlib,hmac,json,os,re,urllib.error,urllib.parse,urllib.request
import security

class BillingError(Exception):
    def __init__(self,code,**details):self.payload={'error':code,'upgrade_url':'/app/dashboard/billing',**details};self.code=402

def plan(c,id):
    r=c.execute('SELECT * FROM plans WHERE id=?',(id,)).fetchone()
    return dict(r,entitlements=json.loads(r['entitlements'])) if r else None

def effective(app,c,tenant):
    stamp=app.now();override=c.execute('SELECT * FROM entitlement_overrides WHERE tenant_id=? AND revoked_at IS NULL AND expires>? ORDER BY created DESC,id DESC LIMIT 1',(tenant,stamp)).fetchone()
    rows=c.execute('SELECT * FROM subscriptions WHERE tenant_id=? ORDER BY created DESC,id DESC',(tenant,)).fetchall()
    usable=[r for r in rows if (r['mode']!='test' or mode()=='test') and (r['status'] in ('ACTIVE','TRIALING','CANCELED') and r['current_period_end']>stamp or r['status']=='PAST_DUE' and r['grace_until']>stamp)]
    sub=usable[0] if usable else next((r for r in rows if r['status']!='AUTHENTICATED'),None)
    p=plan(c,override['plan_id'] if override else usable[0]['plan_id'] if usable else 'free')
    ent=p['entitlements'].copy()
    if override:
        limits=json.loads(override['limits'])
        ent.update({k:v for k,v in limits.items() if k in ('max_cards','max_seats','max_admins')})
    return {'plan':p['id'],'name':p['name'],'entitlements':ent,'source':'override' if override else 'subscription' if usable else 'free','override_expires':override['expires'] if override else None,'subscription':dict(sub) if sub else None}

def usage(app,c,tenant):
    cards=c.execute('SELECT count(*) FROM cards ca JOIN users u ON u.tenant_id=ca.tenant_id AND u.id=ca.user_id WHERE ca.tenant_id=? AND ca.active=1 AND u.active=1',(tenant,)).fetchone()[0]
    seats=c.execute('SELECT count(*) FROM users WHERE tenant_id=? AND active=1',(tenant,)).fetchone()[0]
    admins=c.execute("SELECT count(*) FROM users WHERE tenant_id=? AND active=1 AND role IN ('owner','admin')",(tenant,)).fetchone()[0]
    invites=c.execute("SELECT data FROM invitations WHERE tenant_id=? AND status='pending' AND expires>?",(tenant,app.now())).fetchall()
    return {'cards':cards,'seats':seats,'admins':admins,'reserved_invitations':len(invites),'reserved_admins':sum(json.loads(r['data']).get('role')=='admin' for r in invites)}

def require(app,c,tenant,feature):
    if not effective(app,c,tenant)['entitlements'].get(feature):raise BillingError('ENTITLEMENT_REQUIRED',feature=feature)

def capacity(app,c,tenant,kind,amount=1,exclude_invitation_email=None):
    # Serializes quota writers at READ COMMITTED too; requests also use SERIALIZABLE.
    c.execute('UPDATE organizations SET status=status WHERE id=?',(tenant,))
    e=effective(app,c,tenant)['entitlements'];u=usage(app,c,tenant)
    reserved=u['reserved_admins'] if kind=='admins' else u['reserved_invitations']
    if exclude_invitation_email:
        inv=c.execute("SELECT data FROM invitations WHERE tenant_id=? AND email=? AND status='pending' AND expires>?",(tenant,exclude_invitation_email,app.now())).fetchone()
        if inv and (kind!='admins' or json.loads(inv['data']).get('role')=='admin'):reserved-=1
    limit=e['max_'+kind]
    if limit is not None and u[kind]+reserved+amount>limit:raise BillingError('QUOTA_EXCEEDED',resource=kind,current_usage=u[kind],reserved=reserved,current_limit=limit)

def editable(app,c,tenant,row,data):
    if data.get('active') is False:return
    if not row['active'] and data.get('active'):capacity(app,c,tenant,'cards')
    limit=effective(app,c,tenant)['entitlements']['max_cards']
    if limit is not None and usage(app,c,tenant)['cards']>limit:raise BillingError('QUOTA_EXCEEDED',resource='cards',current_limit=limit,remediation='Deactivate excess cards or upgrade. Records are preserved.')

def mode():return os.environ.get('RAZORPAY_MODE','test')
def configured():
    m=mode();key=os.environ.get('RAZORPAY_KEY_ID','')
    return m in ('test','live') and key.startswith('rzp_'+m+'_') and bool(os.environ.get('RAZORPAY_KEY_SECRET') and os.environ.get('RAZORPAY_WEBHOOK_SECRET'))

def gateway(app,path,payload=None):
    if not configured():raise app.Problem('Razorpay credentials and webhook configuration required.',503)
    auth=base64.b64encode((os.environ['RAZORPAY_KEY_ID']+':'+os.environ['RAZORPAY_KEY_SECRET']).encode()).decode()
    req=urllib.request.Request('https://api.razorpay.com/v1/'+path,data=app.dump(payload).encode() if payload is not None else None,headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=12) as r:return json.load(r)
    except (OSError,ValueError):raise app.Problem('Payment provider unavailable. Reconcile before retrying checkout.',503)

def gateway_id(value,prefix):return isinstance(value,str) and bool(re.fullmatch(prefix+r'_[A-Za-z0-9]+',value))

def prices(c):return [dict(r) for r in c.execute('SELECT * FROM plan_prices WHERE active=1 ORDER BY amount_paise')]

def summary(app,c,tenant):
    e=effective(app,c,tenant)
    return {**e,'trial_available':e['source']=='free' and not c.execute("SELECT 1 FROM subscriptions WHERE tenant_id=? AND status!='FREE'",(tenant,)).fetchone(),'usage':usage(app,c,tenant),'prices':prices(c),'gateway_configured':configured(),'gateway_mode':mode(),'notices':[dict(r) for r in c.execute('SELECT id,kind,message,created FROM billing_notices WHERE tenant_id=? AND resolved IS NULL ORDER BY created DESC LIMIT 10',(tenant,))],'payments':[dict(r) for r in c.execute('SELECT id,amount_paise,currency,status,paid_at,mode FROM payments WHERE tenant_id=? ORDER BY paid_at DESC LIMIT 30',(tenant,))],'availability':{'wallet':False,'crm':False,'saml':False,'scim':False,'events':False},'notes':['Wallet, CRM, SAML/SCIM and Events are not yet operational.','Manual access grants do not count as revenue.']}

def checkout(app,h,c,actor,d):
    app.require_owner(actor);tenant=actor['tenant_id'];h.limited('checkout',8)
    price=c.execute('SELECT * FROM plan_prices WHERE id=? AND active=1',(d.get('price_id'),)).fetchone()
    if not price:raise app.Problem('Select an available price.')
    if not configured():raise app.Problem('Razorpay is not configured. Contact the platform owner.',503)
    # No client-provided amount, provider plan, tenant or callback URL is trusted.
    key='RAZORPAY_PLAN_'+price['id'].upper().replace('-','_')
    provider_plan=os.environ.get(key,'')
    if not gateway_id(provider_plan,'plan'):raise app.Problem('This billing price needs a Razorpay plan mapping.',503)
    c.execute('UPDATE organizations SET status=status WHERE id=?',(tenant,))
    if c.execute("SELECT 1 FROM subscriptions WHERE tenant_id=? AND mode='offline' AND status='ACTIVE' AND current_period_end>?",(tenant,app.now())).fetchone():raise app.Problem('An active offline contract already covers this organization. Contact the platform owner to change billing.',409)
    current=c.execute("SELECT * FROM subscriptions WHERE tenant_id=? AND mode=? AND provider_subscription_id IS NOT NULL AND status NOT IN ('CANCELED','COMPLETED') ORDER BY created DESC LIMIT 1",(tenant,mode())).fetchone()
    if current:
        if current['status']=='AUTHENTICATED' and current['price_id']==price['id']:
            entity=gateway(app,'subscriptions/'+current['provider_subscription_id'])
            return checkout_result(app,entity)
        raise app.Problem('An existing gateway subscription must be reconciled and canceled before another is created.',409)
    provider_price=gateway(app,'plans/'+provider_plan);item=provider_price.get('item',{})
    expected='monthly' if price['interval']=='monthly' else 'yearly'
    if item.get('amount')!=price['amount_paise'] or item.get('currency')!='INR' or provider_price.get('period')!=expected or provider_price.get('interval')!=1:raise app.Problem('Gateway plan does not match the configured HUDDLE price.',503)
    sid=app.uid()
    entity=gateway(app,'subscriptions',{'plan_id':provider_plan,'total_count':120 if price['interval']=='monthly' else 10,'quantity':1,'customer_notify':True,'notes':{'huddle_tenant_id':tenant,'huddle_subscription_id':sid}})
    if not gateway_id(entity.get('id'),'sub'):raise app.Problem('Invalid gateway response.',502)
    c.execute('INSERT INTO subscriptions(id,tenant_id,plan_id,price_id,status,mode,provider_subscription_id,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',(sid,tenant,price['plan_id'],price['id'],'AUTHENTICATED',mode(),entity['id'],app.now(),app.now()))
    app.audit(c,actor,'billing.checkout_created',sid)
    return checkout_result(app,entity)

def checkout_result(app,entity):
    url=entity.get('short_url','');parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in ('rzp.io','razorpay.com','api.razorpay.com'):raise app.Problem('Gateway checkout link unavailable. Reconcile the subscription.',502)
    return {'subscription_id':entity['id'],'checkout_url':url,'mode':mode(),'activation':'Confirmed by verified webhook or server reconciliation only.'}

STATUSES={'created':'AUTHENTICATED','authenticated':'AUTHENTICATED','active':'ACTIVE','pending':'PAST_DUE','halted':'HALTED','cancelled':'CANCELED','paused':'PAUSED','completed':'COMPLETED'}
def apply_snapshot(app,c,row,entity,occurred=None):
    if entity.get('id')!=row['provider_subscription_id']:raise app.Problem('Subscription identity mismatch.',400)
    state=STATUSES.get(entity.get('status'))
    if not state:raise app.Problem('Unknown gateway subscription state.',503)
    if entity.get('notes',{}).get('huddle_subscription_id')!=row['id'] or entity.get('notes',{}).get('huddle_tenant_id')!=row['tenant_id']:raise app.Problem('Subscription ownership mismatch.',400)
    expected=os.environ.get('RAZORPAY_PLAN_'+row['price_id'].upper().replace('-','_'),'')
    if entity.get('plan_id')!=expected or entity.get('quantity',1)!=1:raise app.Problem('Subscription plan mismatch.',400)
    end=int(entity.get('current_end') or row['current_period_end']);stamp=app.now()
    if state=='ACTIVE' and end<=stamp:raise app.Problem('Gateway period is not current.',503)
    # Anchor grace to gateway time (or previous period end), never webhook receipt time.
    failed_at=min(stamp,int(occurred or stamp))
    grace=(row['grace_until'] or failed_at+3*86400) if state=='PAST_DUE' else 0
    c.execute('UPDATE subscriptions SET status=?,current_period_end=?,grace_until=?,provider_customer_id=?,last_event_at=?,updated=? WHERE tenant_id=? AND id=?',(state,end,grace,entity.get('customer_id'),stamp,stamp,row['tenant_id'],row['id']))
    if state=='PAST_DUE':
        nid='past-due-'+row['id']+'-'+str(end)
        c.execute('INSERT OR IGNORE INTO billing_notices VALUES(?,?,?,?,?,?)',(nid,row['tenant_id'],'payment_failed','Renewal failed. Paid features remain available until the grace period ends.',stamp,None))
    else:c.execute('UPDATE billing_notices SET resolved=? WHERE tenant_id=? AND resolved IS NULL AND kind=?',(stamp,row['tenant_id'],'payment_failed'))
    return state


def recover(app,c,entity):
    notes=entity.get('notes',{});tenant=notes.get('huddle_tenant_id');sid=notes.get('huddle_subscription_id')
    if not isinstance(sid,str) or not re.fullmatch(r'[a-f0-9]{24}',sid) or not c.execute('SELECT 1 FROM organizations WHERE id=?',(tenant,)).fetchone():return None
    if not gateway_id(entity.get('id'),'sub'):return None
    matches=[p for p in prices(c) if os.environ.get('RAZORPAY_PLAN_'+p['id'].upper().replace('-','_'))==entity.get('plan_id')]
    if len(matches)!=1:return None
    price=matches[0]
    c.execute('INSERT OR IGNORE INTO subscriptions(id,tenant_id,plan_id,price_id,status,mode,provider_subscription_id,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',(sid,tenant,price['plan_id'],price['id'],'AUTHENTICATED',mode(),entity['id'],int(entity.get('created_at') or app.now()),app.now()))
    return c.execute('SELECT * FROM subscriptions WHERE id=? AND tenant_id=? AND mode=? AND provider_subscription_id=?',(sid,tenant,mode(),entity['id'])).fetchone()

def reconcile(app,c,tenant):
    count=0
    recent=gateway(app,'subscriptions?count=100')
    for entity in recent.get('items',[]):
        if entity.get('notes',{}).get('huddle_tenant_id')==tenant:recover(app,c,entity)
    for row in c.execute('SELECT * FROM subscriptions WHERE tenant_id=? AND mode=? AND provider_subscription_id IS NOT NULL',(tenant,mode())).fetchall():
        apply_snapshot(app,c,row,gateway(app,'subscriptions/'+row['provider_subscription_id']));count+=1
    return {'ok':True,'reconciled':count}

def webhook(app,h,c):
    secret=os.environ.get('RAZORPAY_WEBHOOK_SECRET')
    if not configured() or not secret:raise app.Problem('Billing webhook configuration required.',503)
    try:length=int(h.headers.get('Content-Length',0))
    except ValueError:raise app.Problem('Invalid webhook length.')
    if not 0<length<=262144:raise app.Problem('Invalid webhook size.',413)
    raw=h.rfile.read(length);signature=h.headers.get('X-Razorpay-Signature','')
    if not hmac.compare_digest(hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest(),signature):raise app.Problem('Invalid webhook signature.',400)
    try:event=json.loads(raw)
    except (ValueError,UnicodeError):raise app.Problem('Invalid webhook payload.')
    eid=h.headers.get('X-Razorpay-Event-Id','')
    if not eid or len(eid)>200 or not isinstance(event,dict):raise app.Problem('Webhook event ID required.')
    digest=hashlib.sha256(raw).hexdigest();old=c.execute('SELECT payload_hash FROM billing_events WHERE mode=? AND provider_event_id=?',(mode(),eid)).fetchone()
    if old:
        if old[0]!=digest:raise app.Problem('Conflicting webhook event ID.',409)
        return {'ok':True,'duplicate':True}
    kind=event.get('event','');payload=event.get('payload',{});sub=payload.get('subscription',{}).get('entity',{});pay=payload.get('payment',{}).get('entity',{})
    provider_id=sub.get('id') or pay.get('subscription_id')
    if not provider_id and gateway_id(pay.get('invoice_id'),'inv'):
        invoice=gateway(app,'invoices/'+pay['invoice_id']);provider_id=invoice.get('subscription_id')
    row=c.execute('SELECT * FROM subscriptions WHERE mode=? AND provider_subscription_id=?',(mode(),provider_id)).fetchone() if provider_id else None
    outcome='ignored'
    if not row and gateway_id(provider_id,'sub'):
        row=recover(app,c,gateway(app,'subscriptions/'+provider_id))
    if row:
        # Fetch current state: signed deliveries can be delayed or out of order.
        apply_snapshot(app,c,row,gateway(app,'subscriptions/'+provider_id),event.get('created_at'));outcome='reconciled'
        if kind=='subscription.charged' and gateway_id(pay.get('id'),'pay'):
            verified=gateway(app,'payments/'+pay['id'])
            if verified.get('status')=='captured' and verified.get('currency')=='INR' and verified.get('id')==pay['id']:
                # subscription.charged signature binds the captured payment to this subscription.
                amount=int(verified.get('amount',0))
                if amount<0:raise app.Problem('Invalid payment amount.')
                c.execute('INSERT OR IGNORE INTO payments VALUES(?,?,?,?,?,?,?,?,?,?)',(app.uid(),row['tenant_id'],row['id'],mode(),pay['id'],amount,'INR','captured',int(verified.get('created_at') or app.now()),''))
    c.execute('INSERT INTO billing_events VALUES(?,?,?,?,?,?,?,?,?,?)',(app.uid(),mode(),eid,digest,kind,row['tenant_id'] if row else None,provider_id,int(event.get('created_at') or 0),app.now(),outcome))
    return {'ok':True,'outcome':outcome}

def routes(app,h,c,method,path):
    if path=='/api/webhooks/razorpay' and method=='POST':return True,webhook(app,h,c)
    if path=='/api/public/plans' and method=='GET':return True,{'plans':[plan(c,p) for p in ('free','pro','enterprise')],'prices':prices(c),'checkout_configured':configured()}
    if not path.startswith('/api/billing'):return False,None
    actor=h.actor(c);app.require_owner(actor);tenant=actor['tenant_id']
    if (method!='GET' or path.endswith('/receipts')) and not security.recent(app,c,h,actor):
        h.send(403,{'error':'Verify your authenticator to continue.','elevation_required':True});return True,None
    if path=='/api/billing' and method=='GET':return True,summary(app,c,tenant)
    if path=='/api/billing/checkout' and method=='POST':return True,checkout(app,h,c,actor,h.body())
    if path=='/api/billing/reconcile' and method=='POST':
        h.limited('billing-reconcile',12);return True,reconcile(app,c,tenant)
    if path=='/api/billing/cancel' and method=='POST':
        h.limited('billing-cancel',6);d=h.body();row=c.execute('SELECT * FROM subscriptions WHERE tenant_id=? AND id=? AND mode=?',(tenant,d.get('subscription_id'),mode())).fetchone()
        if not row or not row['provider_subscription_id']:raise app.Problem('Subscription not found.',404)
        gateway(app,'subscriptions/'+row['provider_subscription_id']+'/cancel',{'cancel_at_cycle_end':1});app.audit(c,actor,'billing.cancel_requested',row['id']);return True,reconcile(app,c,tenant)
    if path=='/api/billing/trial' and method=='POST':
        c.execute('UPDATE organizations SET status=status WHERE id=?',(tenant,))
        if c.execute("SELECT 1 FROM subscriptions WHERE tenant_id=? AND status!='FREE'",(tenant,)).fetchone():raise app.Problem('Trial already used or a paid subscription exists.',409)
        c.execute('INSERT INTO subscriptions(id,tenant_id,plan_id,status,mode,current_period_end,created,updated) VALUES(?,?,?,?,?,?,?,?)',(app.uid(),tenant,'pro','TRIALING','none',app.now()+14*86400,app.now(),app.now()));app.audit(c,actor,'billing.trial_started',tenant);return True,summary(app,c,tenant)
    if path=='/api/billing/receipts' and method=='GET':
        rows=[dict(r) for r in c.execute('SELECT id,amount_paise,currency,status,paid_at,mode,reference FROM payments WHERE tenant_id=? ORDER BY paid_at DESC',(tenant,))]
        h.csv_response(rows,['id','amount_paise','currency','status','paid_at','mode','reference'],'huddle-payment-receipts.csv');return True,None
    raise app.Problem('Route not found.',404)
