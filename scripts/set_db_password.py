#!/usr/bin/env python3
"""Set the dedicated backend password interactively without printing it."""
import getpass,os
import psycopg
from psycopg import sql

password=getpass.getpass('New huddle_backend database password (24+ characters): ')
if len(password)<24:raise SystemExit('Use at least 24 characters.')
confirm=getpass.getpass('Confirm password: ')
if password!=confirm:raise SystemExit('Passwords do not match.')
with psycopg.connect(os.environ['MIGRATION_DATABASE_URL'],prepare_threshold=None) as c:
    c.execute(sql.SQL('ALTER ROLE huddle_backend PASSWORD {}').format(sql.Literal(password)))
print('Backend password set. Store it only in the Vercel DATABASE_URL secret.')
