"""Published offers are separate from immutable historical billing prices."""
import re,json,urllib.parse

ORDER = ('free', 'pro-individual', 'pro-workspace', 'enterprise')
CONSENT_VERSION = 'sales-enquiry-v2'


def offers(c):
    rows = {r['plan_id']: dict(r) for r in c.execute('SELECT * FROM pricing_offers')}
    return [rows[key] for key in ORDER if key in rows]


def update_offer(app, c, plan_id, data, actor, audit):
    before = c.execute('SELECT * FROM pricing_offers WHERE plan_id=?', (plan_id,)).fetchone()
    if not before:
        raise app.Problem('Published offer not found.', 404)
    reason = app.text(data.get('reason'), 1000)
    if len(reason) < 10:
        raise app.Problem('Enter a pricing change reason of at least 10 characters.')
    version = data.get('version')
    if type(version) != int or version != before['version']:
        raise app.Problem('Published pricing changed. Reload before saving.', 409)
    values = dict(before)
    if plan_id == 'enterprise':
        for key in ('quote_annual_seat_paise', 'minimum_seats', 'cards_per_seat'):
            value = data.get(key)
            maximum = 100000000 if key.endswith('paise') else 100000
            if type(value) != int or not 1 <= value <= maximum:
                raise app.Problem('Enter positive whole numbers for the Enterprise quote terms.')
            values[key] = value
    elif plan_id == 'free':
        raise app.Problem('Free pricing stays at zero. Manage allowances under Packages.')
    else:
        for interval in ('monthly', 'annual'):
            key = interval + '_price_id'
            price_id = data.get(key)
            row = c.execute('SELECT * FROM plan_prices WHERE id=? AND active=1', (price_id,)).fetchone() if isinstance(price_id, str) else None
            if not row or row['plan_id'] != plan_id or row['interval'] != interval:
                raise app.Problem('Select an available price for this package and billing cycle.')
            values[key] = price_id
    changed = c.execute(
        'UPDATE pricing_offers SET monthly_price_id=?,annual_price_id=?,quote_annual_seat_paise=?,minimum_seats=?,cards_per_seat=?,version=version+1 WHERE plan_id=? AND version=?',
        tuple(values[k] for k in ('monthly_price_id', 'annual_price_id', 'quote_annual_seat_paise', 'minimum_seats', 'cards_per_seat')) + (plan_id, version))
    if changed.rowcount != 1:
        raise app.Problem('Published pricing changed. Reload before saving.', 409)
    after = dict(c.execute('SELECT * FROM pricing_offers WHERE plan_id=?', (plan_id,)).fetchone())
    audit(app, c, actor, 'billing.offer_updated', reason=reason,
          details={'plan': plan_id, 'before': dict(before), 'after': after})
    return {'ok': True, 'offer': after}


def request_quote(app, h, c):
    h.limited('enterprise-quote', 5)
    data = h.body()
    if data.get('website_trap'):
        return {'ok': True}
    name = app.text(data.get('name'), 100)
    email = app.text(data.get('email'), 254).lower()
    company = app.text(data.get('company'), 160)
    seats = data.get('seats')
    request_type=data.get('request_type','enterprise')
    if request_type not in ('enterprise','nfc'):raise app.Problem('Select a valid enquiry type.')
    minimum = c.execute("SELECT minimum_seats FROM pricing_offers WHERE plan_id='enterprise'").fetchone()[0]
    if request_type=='nfc':minimum=1
    if not name or not company or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise app.Problem('Enter your name, company and a valid work email.')
    if type(seats) != int or not minimum <= seats <= 100000:
        raise app.Problem('Enter a team size from ' + str(minimum) + ' to 100,000.')
    if data.get('consent') is not True:
        raise app.Problem('Agree to be contacted about this quote.')
    def field(key,limit=160):
        value=data.get(key,'')
        if not isinstance(value,str) or len(value)>limit:raise app.Problem('Check the '+key.replace('_',' ')+' field.')
        return value.strip()
    phone=field('phone',30)
    if phone and not re.fullmatch(r'[+() 0-9.-]{7,30}',phone):raise app.Problem('Enter a valid contact phone number.')
    if phone and not 7<=len(re.sub(r'\D','',phone))<=15:raise app.Problem('Enter a valid contact phone number.')
    website=field('company_website',300)
    try:parsed=urllib.parse.urlsplit(website)
    except ValueError:raise app.Problem('Enter a valid company website.')
    if website and (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password):raise app.Problem('Enter a company website starting with https://.')
    timeline=field('timeline',40)
    if timeline not in ('','exploring','this-month','1-3-months','3-plus-months'):raise app.Problem('Choose a valid rollout timeline.')
    hardware=field('hardware',40)
    if hardware not in ('','digital-only','own-cards','buy-cards','unsure'):raise app.Problem('Choose a valid NFC preference.')
    quantity=data.get('nfc_quantity',0)
    if type(quantity)!=int or not 0<=quantity<=100000:raise app.Problem('Enter a valid NFC card quantity.')
    if (hardware=='buy-cards' or request_type=='nfc') and quantity<1:raise app.Problem('Enter how many NFC cards you need.')
    needs=data.get('needs',[])
    allowed={'branding','bulk-onboarding','lead-capture','analytics','nfc','integrations'}
    if not isinstance(needs,list) or len(needs)>len(allowed) or any(not isinstance(n,str) or n not in allowed for n in needs):raise app.Problem('Choose valid requirements.')
    details={'request_type':request_type,'phone':phone,'job_title':field('job_title',100),'company_website':website,'industry':field('industry',100),'location':field('location',160),'timeline':timeline,'hardware':hardware,'nfc_quantity':quantity,'needs':list(dict.fromkeys(needs))}
    request_id=app.uid()
    c.execute('INSERT INTO enterprise_quote_requests(id,name,email,company,seats,message,consent_version,created,details) VALUES(?,?,?,?,?,?,?,?,?)',
              (request_id,name,email,company,seats,app.text(data.get('message'),2000),CONSENT_VERSION,app.now(),json.dumps(details)))
    import sales
    sales.record(app,c,request_id,None,'received','new','Enquiry received')
    return {'ok':True,'reference':request_id}
