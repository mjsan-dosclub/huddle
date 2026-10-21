#!/usr/bin/env python3
"""Safe deployment diagnostics: outputs names/status only, never secret values."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import configuration_errors
import database

errors=configuration_errors()
if not database.postgres():errors.append('DATABASE_URL is missing')
if errors:
    print(json.dumps({'ready':False,'configuration_errors':errors}));raise SystemExit(1)
try:
    with database.connection(None) as c:
        c.execute('SELECT 1 FROM organizations LIMIT 1')
        c.execute('SELECT 1 FROM rate_limits LIMIT 1')
        c.execute('SELECT plan_id FROM pricing_offers LIMIT 1')
        c.execute('SELECT details,stage,version FROM enterprise_quote_requests LIMIT 1')
        c.execute('SELECT id FROM sales_enquiry_events LIMIT 1')
        c.execute('SELECT path FROM public_url_aliases LIMIT 1')
        c.execute('SELECT card_slug FROM card_url_settings LIMIT 1')
        role=c.execute('SELECT current_user').fetchone()[0]
        if role!='huddle_backend':raise RuntimeError('Use the dedicated huddle_backend role, not the project admin')
    print(json.dumps({'ready':True,'database':'connected','runtime_role':'huddle_backend'}))
except Exception as e:
    print(json.dumps({'ready':False,'database':'failed','error_type':type(e).__name__}));raise SystemExit(1)
