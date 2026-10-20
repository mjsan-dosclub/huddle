#!/usr/bin/env python3
"""Controlled provisioning for an EXISTING account; no default founder credential."""
import argparse,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server,platform_admin

def main():
    p=argparse.ArgumentParser();p.add_argument('--email',required=True);p.add_argument('--revoke',action='store_true');p.add_argument('--reset-mfa',action='store_true');p.add_argument('--reason',required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
    if len(args.reason.strip())<10:p.error('Supply an audit reason of at least 10 characters.')
    if os.environ.get('DATABASE_URL') and not os.environ.get('MIGRATION_DATABASE_URL'):p.error('Use the administrative MIGRATION_DATABASE_URL, not the runtime backend role.')
    if os.environ.get('MIGRATION_DATABASE_URL'):os.environ['DATABASE_URL']=os.environ['MIGRATION_DATABASE_URL']
    with server.connection() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT id FROM accounts WHERE email=? AND disabled IS NULL',(server.email(args.email),)).fetchone()
        if not row:raise SystemExit('No enabled account exists. Register the intended identity first.')
        if not args.apply:print('Dry run: existing account found. Use --apply to provision/revoke platform access or reset its MFA.');return
        aid=row['id'];actor='administrative-cli'
        if args.revoke:
            c.execute('DELETE FROM platform_admin_grants WHERE account_id=?',(aid,));action='platform.grant_revoked'
        elif args.reset_mfa:
            if not c.execute('SELECT 1 FROM platform_admin_grants WHERE account_id=?',(aid,)).fetchone():raise SystemExit('No platform grant exists.')
            c.execute('DELETE FROM platform_security WHERE account_id=?',(aid,));action='platform.mfa_reset'
        else:
            c.execute('INSERT OR IGNORE INTO platform_admin_grants VALUES(?,?,?,?)',(aid,server.now(),actor,args.reason));action='platform.granted'
        c.execute('DELETE FROM platform_sessions WHERE account_id=?',(aid,));platform_admin.audit(server,c,actor,action,reason=args.reason,details={'account_id':aid})
    print('Platform access operation recorded. No password was created or displayed.')

if __name__=='__main__':main()
