# HUDDLE

Multi-tenant digital business cards, team governance, NFC assignments and consented contact exchange. Version 0.6.1 prepares the existing application for Vercel Functions with Supabase PostgreSQL and private Storage.

**Deployment guide: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).** No cloud resources, real credentials or user database are included. The first deployment needs a Supabase project, database migrations and Vercel environment settings.

## Structure

```text
app.py                  Flask/WSGI entrypoint for Vercel
server.py               Shared web/native API, tenant predicates and RBAC
security.py             Existing password, Google OIDC and tenant MFA logic
surfaces.py              Marketing, application and recipient routing
database.py              SQLite/PostgreSQL adapter and distributed rate limits
object_storage.py        Private Supabase Storage adapter
static/                  Landing, admin UI, shared card renderer, recipient PWA
migrations/              SQLite development migrations
supabase/migrations/     Versioned PostgreSQL schema, access controls and bucket
scripts/                 Explicit migration, import, diagnostics and PG test tools
android/                 Native Android admin/NFC source (no WebView)
tests/                   Regression and deployment-adapter tests
.github/workflows/ci.yml SQLite and real PostgreSQL checks
```

## Local development

Python 3.12 and `pip install -r requirements.txt` are required. Environment variables are not embedded in the browser. Copy `.env.example` only if needed; never commit real values.

For a disposable SQLite demo, leave `DATABASE_URL` and `SUPABASE_URL` unset, then run:

```sh
python server.py --demo --host 127.0.0.1 --port 8765
```

Demo credentials: `admin@hello.example` / `HelloDemo!2026`. These are seeded only with the explicit `--demo` flag; Vercel never seeds them.

For the production request handler locally, initialize the database explicitly, then use `flask --app app run`. An empty cloud database accepts organization signup and assigns the creator Owner. Existing authentication is retained; **Supabase Auth is not used**. Supabase provides PostgreSQL and private object storage. The database runtime role is trusted, and API session, RBAC and tenant predicates enforce isolation; anonymous Supabase clients receive no table/storage access.

## Routes

- `/`, `/pricing`, `/features`, `/templates`: marketing.
- `/app/login`, `/app/signup`, `/app/dashboard/*`: local/single-domain application.
- `/c/:handle`: public cards; `/n/:token`: stable NFC redirects.
- Optional same-project hosts: marketing `huddle.co.in`, application `app.huddle.co.in`, recipients `c.huddle.co.in`. Configure origins only after DNS/HTTPS are ready.

Do not publish NFC cards with a LAN IP or a disposable Vercel preview hostname. A URL already written to a tag cannot be changed by migrating its database record.

## Validation

```sh
python -m unittest discover -s tests -v
# Disposable localhost PostgreSQL only; this resets the huddle schema.
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/postgres \
TEST_ALLOW_RESET=1 python scripts/test_postgres.py
```

Do not point the PostgreSQL test command at a real project. It intentionally rejects non-local URLs. CI uses an isolated PostgreSQL service and no deployment credentials.

## Release limits

Images are limited to 3 MB and workbooks to 2 MB to fit Vercel's base64 request limit. Existing Android 0.6 clients can still connect but should update for the matching client-side image limit. The recipient PWA caches static resources only; profiles and contact exchange need connectivity. Wallet signing, CRM sync, SCIM, billing and native Google OAuth are not implemented. Google web login and Resend require provider configuration. Physical NFC writing must be checked with real hardware.


Platform operations and billing (0.7): see [the implementation and rollout guide](docs/MONETIZATION.md). New organizations are Free; pre-existing organizations receive a 90-day compatibility grant. Founder access is separately provisioned, never granted by signup.
