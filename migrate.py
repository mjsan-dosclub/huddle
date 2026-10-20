"""Versioned migration. Legacy database remains untouched; SQLite backup precedes import."""
import json, sqlite3, secrets, time
from pathlib import Path

def apply(app):
    import database
    if database.postgres():
        from cloud_migrate import apply as apply_cloud
        apply_cloud();return
    app.DATA.mkdir(parents=True,exist_ok=True);(app.DATA/'media').mkdir(exist_ok=True)
    with app.connection() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript((app.ROOT/'migrations/001_multitenant.sql').read_text())
        if c.execute('SELECT 1 FROM schema_migrations WHERE version=1').fetchone():
            apply_surfaces(app,c);return
        legacy=app.DATA/'hello.sqlite3'
        if legacy.exists() and not c.execute('SELECT 1 FROM organizations').fetchone():
            old=sqlite3.connect(legacy);old.row_factory=sqlite3.Row
            backup=app.DATA/('hello-before-huddle-'+str(int(time.time()))+'.sqlite3')
            with sqlite3.connect(backup) as dest:old.backup(dest)
            try:
                brand=json.loads(old.execute("SELECT value FROM settings WHERE key='company'").fetchone()[0])
                tenant=app.uid();brand['analytics_salt']=secrets.token_hex(32)
                c.execute('INSERT INTO organizations VALUES(?,?,?,?,?,?)',(tenant,brand['name'],'workspace-'+tenant[:8],'active',app.dump(brand),app.now()))
                for table in ['divisions','templates']:
                    for r in old.execute('SELECT * FROM '+table):c.execute('INSERT INTO '+table+' VALUES(?,?,?,?,?)',(r['id'],tenant,r['name'],r['data'],r['created']))
                card_ids={}; first_owner=True
                for r in old.execute('SELECT * FROM users ORDER BY created'):
                    aid=app.uid();profile=json.loads(r['data']);role='owner' if r['role']=='admin' and first_owner else 'admin' if r['role']=='admin' else 'member'
                    if role=='owner':first_owner=False
                    c.execute('INSERT INTO accounts VALUES(?,?,?,?,?)',(aid,r['email'],r['password'],r['created'],None))
                    c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?)',(r['id'],tenant,aid,role,profile.get('division_id') or None,app.dump(profile),r['active'],r['created'],r['disabled']))
                    cid=app.uid();card_ids[r['id']]=cid
                    c.execute('INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(cid,tenant,r['id'],profile.get('template_id') or brand['default_template'],'Executive',r['slug'],app.dump({**profile,'email':r['email']}),'{}',1,r['active'],r['created'],app.now()))
                tables={r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in ['invitations','requests','audit']:
                    if table not in tables:continue
                    for row in old.execute('SELECT * FROM '+table):
                        r=dict(row)
                        if 'data' in r:
                            d=json.loads(r['data']);d['role']='admin' if d.get('role')=='admin' else 'member';r['data']=app.dump(d)
                        r['tenant_id']=tenant;cols=list(r)
                        c.execute('INSERT INTO '+table+' ('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',tuple(r[k] for k in cols))
                if 'nfc_cards' in tables:
                    for r in old.execute('SELECT * FROM nfc_cards'):
                        if r['user_id'] in card_ids:c.execute('INSERT INTO nfc_cards VALUES(?,?,?,?,?,?,?,?,?)',(r['id'],tenant,card_ids[r['user_id']],r['token'],r['label'],r['tag_hash'],r['active'],r['created'],r['written']))
                if 'activity' in tables:
                    for r in old.execute('SELECT * FROM activity'):
                        if r['user_id'] in card_ids:c.execute('INSERT INTO activity VALUES(?,?,?,?,?,?,?,?,?)',(r['id'],tenant,r['user_id'],card_ids[r['user_id']],r['kind'],r['source'],r['visitor'],r['label'],r['created']))
                for p in (app.DATA/'media').glob('*.png'):
                    c.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)',(app.uid(),tenant,'migration','/media/'+p.name,'public',app.now()))
                if c.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Legacy import has invalid relationships; transaction rolled back.')
                print('HUDDLE migration complete. Legacy sessions revoked; division administrators mapped to Member without expanded access.',flush=True)
            finally:old.close()
        c.execute('INSERT INTO schema_migrations VALUES(1,?)',(app.now(),))
        apply_surfaces(app,c)

def apply_surfaces(app,c):
    if c.execute('SELECT 1 FROM schema_migrations WHERE version=2').fetchone():
        apply_monetization(app,c);return
    c.executescript((app.ROOT/'migrations/002_auth_surfaces.sql').read_text())
    columns={r[1] for r in c.execute('PRAGMA table_info(sessions)')}
    for name,definition in [('mfa_tenant','TEXT'),('mfa_at','INTEGER NOT NULL DEFAULT 0'),('authenticated_at','INTEGER NOT NULL DEFAULT 0')]:
        if name not in columns:c.execute('ALTER TABLE sessions ADD COLUMN '+name+' '+definition)
    for org in c.execute('SELECT id,data FROM organizations').fetchall():
        import json
        brand=json.loads(org['data']);default=c.execute('SELECT data FROM templates WHERE tenant_id=? AND id=?',(org['id'],brand['default_template'])).fetchone()
        policy=json.loads(default[0]) if default else {'visible_fields':app.FIELDS,'locked_fields':['name','title','email'],'enabled':True,'personal_links_allowed':True}
        for name,layout,accent in [('Executive Charcoal','executive','#242a29'),('Mint Neon','mint','#b7f264'),('Vibrant Sunset','sunset','#ed795e')]:
            data={**policy,'layout':layout,'accent':accent}
            c.execute('INSERT INTO templates VALUES(?,?,?,?,?)',(app.uid(),org['id'],name,app.dump(data),app.now()))
    c.execute('INSERT INTO schema_migrations VALUES(2,?)',(app.now(),))
    apply_monetization(app,c)


def apply_monetization(app,c):
    if not c.execute('SELECT 1 FROM schema_migrations WHERE version=3').fetchone():c.executescript('BEGIN IMMEDIATE;\n'+(app.ROOT/'migrations/003_monetization.sql').read_text()+'\nCOMMIT;')

if __name__=='__main__':
    import server
    apply(server)
    print('Migration complete.')
