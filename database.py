"""SQLite development / PostgreSQL server adapter; no credentials reach browsers."""
import os,re,sqlite3

SCHEMA='huddle'

def postgres():return bool(os.environ.get('DATABASE_URL'))

def retryable(error):
    if not postgres():return False
    import psycopg
    return isinstance(error,(psycopg.errors.SerializationFailure,psycopg.errors.DeadlockDetected))

class Row(dict):
    def __getitem__(self,key):
        return tuple(self.values())[key] if isinstance(key,int) else super().__getitem__(key)

class Result:
    def __init__(self,cursor):
        self.rowcount=cursor.rowcount
        names=[col.name for col in cursor.description] if cursor.description else []
        self.rows=[Row(zip(names,row)) for row in cursor.fetchall()] if names else []
        self.offset=0;cursor.close()
    def fetchone(self):
        if self.offset>=len(self.rows):return None
        result=self.rows[self.offset];self.offset+=1;return result
    def fetchall(self):
        result=self.rows[self.offset:];self.offset=len(self.rows);return result
    def __iter__(self):return iter(self.fetchall())

def sql(query):
    """Translate only the internal SQLite parameter dialect, never user input."""
    if query in ('BEGIN','BEGIN IMMEDIATE'):
        return 'BEGIN ISOLATION LEVEL SERIALIZABLE' if query.endswith('IMMEDIATE') else 'BEGIN'
    if query.startswith('INSERT OR IGNORE INTO '):
        query=query.replace('INSERT OR IGNORE INTO ','INSERT INTO ',1)+' ON CONFLICT DO NOTHING'
    # Split SQL literals so quoted question marks and percent literals stay intact.
    parts=re.split("('(?:''|[^'])*')",query)
    return ''.join(part.replace('%','%%').replace('?','%s') if i%2==0 else part.replace('%','%%') for i,part in enumerate(parts))

class Postgres:
    def __init__(self):
        import psycopg
        # Transaction pooler compatibility: no prepared statements / session SET.
        self.raw=psycopg.connect(os.environ['DATABASE_URL'],autocommit=True,
            prepare_threshold=None,connect_timeout=10)
        self.active=False
    def execute(self,query,args=()):
        import psycopg
        try:
            if query in ('BEGIN','BEGIN IMMEDIATE'):
                self.raw.execute(sql(query));self.active=True
                self.raw.execute('SET LOCAL search_path TO huddle, pg_catalog')
                self.raw.execute("SET LOCAL statement_timeout='20s'")
                self.raw.execute("SET LOCAL idle_in_transaction_session_timeout='30s'")
                return Result(self.raw.execute('SELECT 1 WHERE FALSE'))
            if not self.active:self.execute('BEGIN')
            return Result(self.raw.execute(sql(query),args))
        except psycopg.IntegrityError as e:raise sqlite3.IntegrityError('Constraint violation') from e
    def commit(self):
        self.raw.commit();self.active=False
    def rollback(self):
        self.raw.rollback();self.active=False
    def close(self):self.raw.close()
    def __enter__(self):return self
    def __exit__(self,kind,value,tb):
        try:
            if kind:self.rollback()
            else:self.commit()
        finally:self.close()

def connection(path):
    if postgres():return Postgres()
    if os.environ.get('VERCEL'):raise RuntimeError('DATABASE_URL is required on Vercel; SQLite fallback is disabled')
    c=sqlite3.connect(path,timeout=15);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c

def limited(app,identity,group,maximum):
    """A shared fixed window survives cold starts; attempted requests always commit."""
    import hashlib
    stamp=app.now();window=stamp//900*900
    key=hashlib.sha256((os.environ['HUDDLE_ENCRYPTION_KEY']+':'+identity+':'+group).encode()).hexdigest()
    with connection(None) as c:
        count=c.execute('INSERT INTO rate_limits(key,window_start,hits,expires) VALUES(?,?,1,?) '
            'ON CONFLICT(key,window_start) DO UPDATE SET hits=rate_limits.hits+1 RETURNING hits',
            (key,window,window+1800)).fetchone()[0]
        c.execute('DELETE FROM rate_limits WHERE expires<?',(stamp,))
    if count>maximum:raise app.Problem('Too many attempts. Try again later.',429)
