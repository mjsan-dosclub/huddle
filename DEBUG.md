# Deployment debug checklist

- Missing configuration: inspect Vercel environment variable names, then redeploy. Values are intentionally never echoed by preflight.
- Database unavailable: verify the dedicated backend username, encoded password, pooler host, TLS and applied migrations. Use session pooler for migrations, transaction pooler for runtime.
- Images unavailable: verify the private Storage bucket and server-side service-role key. Unpublished images need an authenticated session in the same organization.
- Invitation mail: verify Resend's sender domain and delivery status. Bulk onboarding sends one batch request (up to 100 valid rows), with no email sent in demo mode. A request failure can leave provider delivery uncertain; inspect provider logs before retrying.
- Concurrent modification: a 409 asks the client to retry after PostgreSQL prevents a conflicting update. Never assume a failed request produced a session.
- MFA decrypt error after import: preserve the existing encryption key; do not replace it with a newly generated key. Recovery codes remain a separate recovery path.
- Android connectivity: use the canonical HTTPS application origin, sign in and refresh employees. localhost on the phone does not refer to your computer. NFC URLs must resolve from recipients' networks.
- Physical NFC validation, actual Supabase Storage, DNS/HTTPS and provider credentials require post-deployment acceptance.
