# HUDDLE 0.7 — platform operations and monetization

This release is additive to the existing Flask/Python, vanilla-JavaScript and PostgreSQL architecture. It does not replace account authentication, tenant membership, NFC links, or private storage. No ORM is introduced.

## Access boundaries

`accounts` are global login identities. `users` remain tenant memberships with Owner/Admin/Member roles. A separate `platform_admin_grants` row authorizes operator access. Public signup cannot create that grant, and the backend database role cannot write the grants table. The application never turns a tenant Owner into a platform administrator.

`/super-admin` and `/api/platform/*` return 404 to unprivileged users. Provisioned operators use their normal account session to enroll a separate platform authenticator, then enter their password and a fresh TOTP code for ten-minute elevation. The platform MFA secret is encrypted with the existing server encryption key; replay counters are enforced. Operator sessions have a separate HttpOnly, SameSite=Strict cookie. Password changes revoke both tenant and operator sessions. Platform MFA has a controlled CLI recovery process rather than an email bypass.

Support access is deliberately read-only inspection, not an Owner login. It is tied to the actual operator, requires a reason, expires after ten minutes, and exposes roster names/roles and aggregate tenant/billing information. It excludes lead contents, account credentials, MFA secrets and invitation tokens. Every support opening, view and explicit close is audited. Tenant mutations remain available only through explicit, audited operator endpoints.

Platform audit records are append-only to the runtime database role (SQLite triggers in development, PostgreSQL privilege revocations in production). Database administrators can still alter the database; this is not an externally immutable compliance ledger.

## Schema 3

- `platform_admin_grants`, `platform_security`, `platform_sessions`: independent operator authorization, encrypted authenticator enrollment and short-lived elevation.
- `plans`: versioned entitlement definitions.
- `plan_prices`: immutable price amounts/intervals; create another price for changes. Only availability can be edited. Existing subscriptions retain their original price.
- `subscriptions`: organization-owned plan/price, provider identity, mode, lifecycle status, period end, grace and reconciliation timestamps. Multiple historical attempts are retained.
- `entitlement_overrides`: scoped, expiring access grants/custom quotas; reason and operator attribution required.
- `billing_events`: signature-verified webhook metadata, payload hash, unique provider event ID per mode, processing outcome. Raw payment payloads are not retained.
- `payments`: recorded captured gateway payments or explicitly recorded offline receipts, with unique references per mode.
- `billing_notices`: durable in-app renewal-failure notices. Email delivery is not enabled by this release.
- `platform_audit`, `support_sessions`: operator actions and support inspection history.

All tenant financial records have `tenant_id` foreign keys. Payment-to-subscription relations use a composite tenant foreign key. New PostgreSQL tables have RLS enabled and remain in the private `huddle` schema; public/anon/authenticated roles have no access. The trusted backend still enforces tenant predicates and operator guards.

## Current commercial baseline

| Capability | Free | Pro | Enterprise |
|---|---|---|---|
| Active cards, including personas | 1 | 10 | Custom/unlimited |
| Active members | 1 | 10 | Custom/unlimited |
| Owners/Admins | 1 | Up to 10 within seat quota | Custom/unlimited |
| Company contact details, standard QR, WhatsApp/UPI | Yes | Yes | Yes |
| Custom colours/logo and branded QR | No | Yes | Yes |
| Two-way lead capture and CSV export | No | Yes | Yes |
| Bulk CSV/XLSX invitations | No | Yes | Yes |
| Remove HUDDLE footer | No | No | Yes |
| Wallet eligibility | No | Yes | Yes |
| Actual Wallet passes | Not operational | Not operational | Not operational |

Initial prices: Pro INR 499/month or INR 4,999/year; Enterprise INR 2,499/month. These are baseline configured amounts, not a claim that tax is calculated or collected. Annual Enterprise pricing is not invented. Platform operators may create a new price and retire old checkout prices. A new price needs an exact Razorpay plan environment mapping before it can be purchased.

All organizations created after migration start Free. Owners may start a one-time 14-day Pro trial. Organizations already present when migration 3 is applied receive an explicit 90-day Enterprise compatibility grant. This preserves existing operations during rollout without treating those grants as paid subscriptions.

Quotas include pending, unexpired invitation reservations. Accepting an invitation consumes its reservation in the same transaction that creates the default card. Card/seat/admin creation checks serialize on the organization row and run in the existing serializable transaction. Concurrent conflicts return 409 and can be retried. Existing per-user twenty-persona safety cap remains.

When a plan expires, existing cards/leads are preserved, public card links continue working for active organizations, custom public branding/QR and new lead capture are gated, and over-limit card edits are blocked. Owners can deactivate excess cards without deleting them. Existing leads remain readable, while paid CSV exports are blocked. Reactivating a card consumes quota again. Administrative suspension/pausing blocks tenant sessions and public cards independently of billing status.

## Razorpay behavior

Configure the key pair, mode, webhook secret and plan mappings using Vercel Production secrets/config. Never place key secrets in the frontend. `RAZORPAY_MODE=test` is the default, but checkout remains disabled without all credentials. Test-mode subscriptions cannot grant paid access when runtime mode switches to live, and test revenue never contributes to MRR.

Checkout is Owner-only. The server resolves the selected immutable price, fetches the mapped gateway plan and verifies amount/currency/interval before creating a subscription. The frontend presents the gateway-issued hosted checkout link in a dialog; no third-party Checkout script or changed CSP is necessary. A client success callback cannot activate a plan. Existing subscriptions must be reconciled/canceled before starting another. Switching active plans is intentionally not an automatic proration flow.

The webhook checks HMAC-SHA256 over the raw request body before JSON parsing. It deduplicates `X-Razorpay-Event-Id` per mode. For subscription events, it fetches current gateway state before changing access so delayed deliveries cannot roll an active subscription back to an old event snapshot. Generic payment events can resolve their subscription through the invoice. A signed event and server-fetched notes/plan can recover an externally created subscription whose local response/transaction failed. Owner reconciliation also examines the latest 100 gateway subscriptions for this tenant; older exceptional orphan cases require operator investigation rather than blind retry.

`created/authenticated` do not grant access. `active` grants access through the gateway period end. `pending` receives a fixed three-day grace window anchored to the signed event time when available; subsequent retries do not extend it. `halted`, `paused`, `completed`, and expired/canceled periods resolve to Free. Scheduled cancellation retains access through the purchased period. Provider-owned retry behavior remains with Razorpay. In-app failure notices are stored; Resend notifications remain deferred.

Recorded gateway payments must be verified captured INR payments associated with a signed `subscription.charged` event. Offline receipts are entered by an elevated operator, with a unique payment reference and audit reason; no money movement occurs. Access-only overrides do not create revenue. MRR counts current active live/offline recurring contracts, normalizes annual amounts over 12 months, and excludes tests, trials and grants. Churn is labeled an operational estimate because pre-release historical snapshots do not exist.

## Routes

- Tenant: `/app/dashboard/billing` (or `/dashboard/billing` on the app host).
- Owner API: `GET /api/billing`, `POST /api/billing/trial`, `/checkout`, `/reconcile`, `/cancel`; `GET /api/billing/receipts`.
- Public catalogue: `GET /api/public/plans`.
- Provider: `POST /api/webhooks/razorpay`.
- Operator: `/super-admin`, `/api/platform/access`, `/mfa/setup`, `/mfa/confirm`, `/elevate`, `/logout`, `/overview`, `/tenants`, `/audit`, `/prices`, `/support`.
- Tenant operations: `/api/platform/tenants/{id}` with POST `/status`, `/override`, `/reconcile`, `/offline-payment`.

Billing writes retain membership MFA elevation requirements. Core API enforcement covers web and native clients; the Android APK has not been rebuilt with a native billing screen. Tenant Owners use the web billing screen for commercial account management.

## Release and founder bootstrap

1. Back up production; review migration `supabase/migrations/202610190003_monetization.sql`. Apply it with the administrative migration credential **before** deploying 0.7. Do not modify already-applied migrations 1 or 2. `cloud_migrate.py` records checksums and runs migrations under an advisory lock.
2. Confirm 90-day grants exist for pre-existing organizations, new tables have RLS, and the backend cannot modify platform grants/audit history.
3. Deploy 0.7 and verify health reports schema 3/version 0.7.0, ordinary Owners receive 404 on platform routes, and new registrations resolve to Free.
4. The designated founder account must already exist, and its ownership must be confirmed through the intended user's login. This document does not create an account or password. No production grant has been applied by development.
5. From a trusted administrative machine with `MIGRATION_DATABASE_URL` set privately, run the dry run, then apply:

```sh
python scripts/platform_admin.py --email founder@yourdomain.example --reason 'Initial HUDDLE founder provisioning'
python scripts/platform_admin.py --email founder@yourdomain.example --reason 'Initial HUDDLE founder provisioning' --apply
```

6. Sign in normally with that account, open `/super-admin`, enroll platform MFA yourself, and save an authenticator backup privately. No default founder password exists.
7. Set Razorpay **test** credentials and exact INR plan mappings. Configure `/api/webhooks/razorpay` for subscription lifecycle events including authenticated, activated, charged, pending, halted, paused, resumed, cancelled and completed, plus payment failures. Test captured payment, replay, delayed delivery, renewal failure/grace and cancellation. Do not enable real collection before this acceptance check.
8. Switching live requires matching live plan IDs, live key pair, a distinct webhook secret and a live-mode webhook configuration. Resend and custom domains remain separate pending setup.

Controlled recovery: `scripts/platform_admin.py --email ... --reason 'Verified operator recovery ...' --reset-mfa --apply` revokes elevation and removes platform MFA for reenrollment. `--revoke --apply` removes the global grant and operator sessions. These require the administrative credential and should be performed only after identity verification.

## Explicitly unfinished services

Real Razorpay test-account checkout/webhook delivery has not been exercised without credentials; transport and transitions are covered by fixtures. GST tax invoices, taxes/credit notes/refund accounting, automated offline contract renewal, full plan-change proration, Wallet signing, CRM sync, SAML/SCIM, geofencing, Events, and renewal-failure emails are not implemented. Payment CSVs are receipts, not GST invoices. Live collection is not enabled.

Provider references: https://razorpay.com/docs/webhooks/validate-test/ ; https://razorpay.com/docs/api/payments/subscriptions/create-subscription/ ; https://razorpay.com/docs/webhooks/subscriptions/

Legacy SQLite imports receive the same 90-day access preservation after import. Sources containing trial/payment/subscription history are rejected by the legacy importer; use a dedicated financial-data migration rather than silently dropping that history. Platform grants and authenticator enrollment are not imported by that legacy tool.
