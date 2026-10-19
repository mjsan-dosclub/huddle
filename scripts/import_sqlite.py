#!/usr/bin/env python3
"""Optional v0.6 SQLite import. Dry-run by default; preserves handles/NFC tokens."""
import argparse,base64,json,os,sqlite3,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg import sql
import object_storage

TABLES=['accounts','organizations','divisions','templates','users','cards','invitations','requests','audit','nfc_cards','activity','contact_exchanges','assets','wallet_passes','user_security','oauth_identities']

def run(source,apply=False):
    source=Path(source).resolve()
    # A consistent SQLite backup includes committed WAL contents without stopping the demo.
    with tempfile.TemporaryDirectory() as folder:
        original=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
        c=sqlite3.connect(Path(folder)/'snapshot.sqlite3');original.backup(c);original.close();c.row_factory=sqlite3.Row
        if c.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Source contains invalid relationships')
        if not c.execute('SELECT 1 FROM schema_migrations WHERE version=2').fetchone():raise RuntimeError('Upgrade the local source to schema 2 first')
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='subscriptions'").fetchone() and c.execute("SELECT 1 FROM subscriptions WHERE status!='FREE' OR mode!='none' LIMIT 1").fetchone():raise RuntimeError('This source contains billing history. Use a dedicated financial-data migration; the legacy importer will not discard it.')
        counts={table:c.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in TABLES}
        if not apply:
            print(json.dumps({'mode':'dry-run','rows':counts,'source_changed':False,'destination_changed':False}));return
        if c.execute('SELECT 1 FROM user_security WHERE secret IS NOT NULL OR pending_secret IS NOT NULL LIMIT 1').fetchone():
            configured=base64.urlsafe_b64decode(os.environ['HUDDLE_ENCRYPTION_KEY']);local=source.parent/'.security-key'
            if not local.exists() or configured!=local.read_bytes():raise RuntimeError('Preserve the existing local MFA encryption key before importing')
        assets=c.execute('SELECT storage_key FROM assets').fetchall()
        for row in assets:
            object_storage.object_path(row['storage_key'])
            path=source.parent/row['storage_key'].lstrip('/')
            if not path.is_file():raise RuntimeError('A source image is missing')
            if path.stat().st_size>3*1024*1024:raise RuntimeError('A source image exceeds the cloud 3 MB limit')
        if assets and not object_storage.remote():raise RuntimeError('Configure Supabase Storage before importing assets')
        with psycopg.connect(os.environ['MIGRATION_DATABASE_URL'],prepare_threshold=None) as dest:
            dest.execute('SELECT pg_advisory_xact_lock(721904610)')
            dest.execute('SET LOCAL search_path TO huddle, pg_catalog')
            if dest.execute('SELECT 1 FROM organizations LIMIT 1').fetchone():raise RuntimeError('Destination must be empty. Import before enabling registration')
            for table in TABLES:
                for row in c.execute('SELECT * FROM '+table):
                    columns=list(row.keys())
                    query=sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder() for _ in columns))
                    dest.execute(query,tuple(row))
            # Imports occur after schema deployment, so explicitly preserve legacy access.
            import time,secrets
            stamp=int(time.time())
            for org in c.execute('SELECT id FROM organizations'):
                tenant=org['id']
                dest.execute("INSERT INTO subscriptions(id,tenant_id,plan_id,status,mode,created,updated) VALUES(%s,%s,'free','FREE','none',%s,%s)",('import-sub-'+tenant,tenant,stamp,stamp))
                dest.execute("INSERT INTO entitlement_overrides VALUES(%s,%s,'enterprise','{}',%s,'legacy-import',%s,%s,NULL)",('import-grant-'+tenant,tenant,'90-day compatibility grant for legacy SQLite import',stamp,stamp+90*86400))
                dest.execute("INSERT INTO platform_audit VALUES(%s,'legacy-import',%s,'tenant.compatibility_grant',%s,'{}',%s)",('import-audit-'+tenant,tenant,'Legacy SQLite import with 90-day access grant',stamp))
            for table in ('audit','activity'):
                dest.execute(sql.SQL("SELECT setval(pg_get_serial_sequence({},'id'),COALESCE(MAX(id),1),COUNT(*)>0) FROM {}").format(sql.Literal('huddle.'+table),sql.Identifier(table)))
            for row in assets:object_storage.request('POST',row['storage_key'],(source.parent/row['storage_key'].lstrip('/')).read_bytes())
        c.close()
        print(json.dumps({'mode':'imported','rows':counts,'sessions':'revoked; sign in again','source_changed':False}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',help='Path to schema-2 huddle.sqlite3');parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();run(args.source,args.apply)
