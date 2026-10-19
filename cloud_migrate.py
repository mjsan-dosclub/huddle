"""Explicit, checksummed PostgreSQL migrations; never run in a web request."""
import hashlib,os
from pathlib import Path

def apply(url=None):
    import psycopg
    url=url or os.environ.get('MIGRATION_DATABASE_URL') or os.environ.get('DATABASE_URL')
    if not url:raise RuntimeError('Set MIGRATION_DATABASE_URL to the Supabase admin direct/session-pooler URL')
    with psycopg.connect(url,prepare_threshold=None,connect_timeout=10) as c:
        c.execute('SELECT pg_advisory_xact_lock(721904610)')
        c.execute('CREATE SCHEMA IF NOT EXISTS huddle')
        c.execute('CREATE TABLE IF NOT EXISTS huddle.deployment_migrations(version TEXT PRIMARY KEY,sha256 TEXT NOT NULL,applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
        for path in sorted((Path(__file__).parent/'supabase/migrations').glob('*.sql')):
            source=path.read_text();digest=hashlib.sha256(source.encode()).hexdigest()
            old=c.execute('SELECT sha256 FROM huddle.deployment_migrations WHERE version=%s',(path.stem,)).fetchone()
            if old:
                if old[0]!=digest:raise RuntimeError('Applied migration changed: '+path.name)
                continue
            c.execute(source,prepare=False)
            c.execute('INSERT INTO huddle.deployment_migrations(version,sha256) VALUES(%s,%s)',(path.stem,digest))
        c.execute('REVOKE ALL ON huddle.deployment_migrations,huddle.schema_migrations FROM huddle_backend')
    print('PostgreSQL migrations verified and applied.')

if __name__=='__main__':apply()
