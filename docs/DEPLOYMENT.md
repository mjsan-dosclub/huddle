# Vercel + Supabase deployment

Repository: https://github.com/mjsan-dosclub/huddle

This guide creates a new installation. No Supabase/Vercel projects have been created or charged by preparing this repository. Use the optional import section if you want the local demo data; otherwise start with an empty database and create your first organization through signup.

## 1. Create Supabase

1. Create a Supabase project in your preferred region. Keep its database password in a password manager.
2. Open **Connect** and copy the **Session pooler** admin connection string (port 5432) for migrations. Include `?sslmode=require`; percent-encode special characters in passwords.
3. On your local migration machine, install Python 3.12 and run `pip install -r requirements.txt` inside the repository. Set `MIGRATION_DATABASE_URL` privately in your shell to the admin URL; do not paste it into chat or commit it.
4. Run `python scripts/db_migrate.py`. It applies the two checksummed files in `supabase/migrations` transactionally and creates the private `huddle` schema, tables, access policies, `huddle_backend` role and private `huddle-assets` Storage bucket. Do not paste individual files into SQL Editor without a transaction or bypass the migration ledger.
5. Run `python scripts/set_db_password.py` and enter a new 24+ character password for `huddle_backend`. This is a separate credential from the project admin password.
6. Copy the **Transaction pooler** URL (port 6543). Change its username to `huddle_backend.PROJECT_REF` and its password to the backend password. This becomes Vercel's `DATABASE_URL`. Keep `sslmode=require`. Do not copy the admin URL into Vercel.
7. Find your project URL and legacy **service_role** key under the project's API settings. The Storage adapter uses this server-only JWT. Do not use a publishable/anon key and never put the service-role key in frontend code.

Do not add `huddle` to the project's exposed Data API schemas. Keep `huddle-assets` private and add no anonymous/authenticated Storage policies. API routes proxy assets after checking tenant ownership or explicit public visibility. The backend role has access to application rows; per-tenant and member authorization remains in the tested API. This deployment does not migrate accounts into Supabase Auth.

## 2. Import the repository in Vercel

Choose the Vercel Function region near your Supabase database to reduce latency.

1. Create a Vercel project by importing `mjsan-dosclub/huddle`, branch `main`.
2. Root directory: repository root (`.`). Framework: **Flask** (auto-detected). Python: **3.12**. No frontend build/output directory override is needed. `app.py` exports the Flask app and `vercel.json` configures its single Function.
3. Choose your project hostname and set these **server-only environment variables** before deploying:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Dedicated `huddle_backend` transaction-pooler URL with TLS |
| `SUPABASE_URL` | `https://PROJECT_REF.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-only legacy service-role JWT for Storage |
| `SUPABASE_STORAGE_BUCKET` | `huddle-assets` |
| `HUDDLE_ENCRYPTION_KEY` | Permanent base64url-encoded random 32 bytes |
| `PUBLIC_BASE_URL` | `https://YOUR_PROJECT.vercel.app` initially |

Generate the encryption key privately, for example with `python -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'`. Store it securely; changing it prevents existing TOTP secrets from decrypting. If importing the local database, preserve the existing key instead (section 4).

`MIGRATION_DATABASE_URL` belongs only on your migration machine. `VERCEL` is set by the platform. Missing mandatory values produce a configuration-required 503; the cloud handler never silently falls back to SQLite or local image storage.

4. Deploy and open `/api/health`; expect application `HUDDLE`, version `0.6.1`. Missing/unreachable database or missing migrations must be resolved before signup.
5. Open `/app/signup`, create the first organization and verify its Owner account. Configure MFA in account security.

Use a separate Supabase project and encryption key for preview/staging. Do not attach production database/Storage credentials to untrusted PR previews. The first Vercel import may create a failed deployment while settings are incomplete; redeploy after setting the environment.

## 3. Optional mail, Google and custom domains

- Invitations: set `RESEND_API_KEY` and `RESEND_FROM` with a verified sender domain, then redeploy. No email is sent until configured; invitations remain visible to authorized administrators.
- Google web login: set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from an OAuth web client. Register exactly `https://YOUR_APP_ORIGIN/api/auth/google/callback` and your intended app origin in Google's settings. Native Android Google login remains deferred.
- Add all custom domains to the **same** Vercel project before setting routing variables:

```text
HUDDLE_PUBLIC_ORIGIN=https://huddle.co.in
HUDDLE_APP_ORIGIN=https://app.huddle.co.in
HUDDLE_APP_HOST=app.huddle.co.in
HUDDLE_CARD_HOST=c.huddle.co.in
HUDDLE_CARD_ORIGIN=https://c.huddle.co.in
PUBLIC_BASE_URL=https://c.huddle.co.in
```

Only use domains you control. Follow Vercel's displayed DNS records rather than guessing them. Keep `/c/:handle` and `/n/:token` supported on the canonical public base. The card host also accepts `/:handle`; generated links retain `/c/` for backwards compatibility. Session cookies stay host-only: sign in on the canonical app hostname and set the Android server address to that hostname. Old LAN/NFC URLs need rewriting on tags or continued redirects from an old **reachable** domain.

## 4. Optional local-data import

Keep the existing installation available until cloud acceptance is complete. Do not commit its `data` folder, images, signing key, SQLite files or `.security-key`.

1. Back up the source directory using your normal secure backup method. Use a schema-2 `huddle.sqlite3` from the 0.6 release; retain its sibling `media` folder.
2. Run `python scripts/import_sqlite.py /absolute/path/to/huddle.sqlite3` to print counts only. Dry-run changes neither source nor destination.
3. If it contains MFA enrollments, set `HUDDLE_ENCRYPTION_KEY` to the base64url encoding of the **existing** raw `.security-key`, through a private shell/key manager. The importer verifies this matches the sibling source key. Never generate a replacement for existing enrollments.
4. Configure admin `MIGRATION_DATABASE_URL` and Supabase Storage variables locally. Before allowing new signups, run the same command with `--apply` against an **empty destination**. It preserves account/member/card IDs, public handles, NFC tokens, leads and MFA. It copies tenant-owned images to the private bucket. Sessions, challenges, OAuth handshakes and rate-limit counters are not imported; users sign in again.
5. Database insertion is transactional. A failed object upload rolls database insertion back; already-uploaded objects may remain unreferenced and can be cleaned later. A failed import does not rewrite the local source.
6. Assets must fit the new 3 MB limit. Resize/re-upload oversized images in a copy of the local installation before importing; do not modify content-addressed files directly.

## 5. Acceptance and operations

- On a migration machine with runtime env configured, `VERCEL=1 python scripts/preflight.py` checks configuration and database access without printing credentials. It does not replace a real Storage upload test.
- Check desktop/mobile landing, `/templates`, signup/login, two organizations, organization switching, Member restrictions, leads/export, company logo upload, QR logo rendering and MFA login/recovery.
- In Android, update Server to the canonical HTTPS app origin, sign in, refresh employees, prepare/write/read-back a writable NDEF tag and open its URL on a separate recipient phone. A physical tap opens a browser; no recipient app is required.
- Verify a second organization cannot load private images or mutate the first organization's cards, members, leads or NFC records.
- Keep Vercel logs free of secrets; the API logs exception types, never request bodies. Rotate the backend database password and Storage service-role key through your provider settings when required. Preserve the MFA encryption key securely.
- PostgreSQL migrations run explicitly before code deployment, never during requests or build. Use Supabase database backups and a separate Storage-object backup strategy. Vercel code rollback does not roll back database migrations or uploaded files.

The repository was tested locally with PostgreSQL, SQLite and a real browser. Supabase-managed Storage, transaction-pooler credentials, DNS, HTTPS, live Google OAuth, mail delivery and the actual Vercel deployment require acceptance after the projects exist.

## Provider documentation

- [Flask on Vercel](https://vercel.com/docs/frameworks/backend/flask)
- [Vercel Function limits](https://vercel.com/docs/functions/limitations)
- [Supabase PostgreSQL connections](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supabase Storage](https://supabase.com/docs/guides/storage)


## HUDDLE 0.7 rollout

See [MONETIZATION.md](MONETIZATION.md) before deploying the monetization release. Apply migration 3 before code rollout, provision the designated founder account separately, and enroll platform MFA. Razorpay remains disabled until credentials and plan mappings are configured. Resend remains deferred.
