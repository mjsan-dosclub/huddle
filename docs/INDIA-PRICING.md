# India pricing rollout

The homepage, pricing page, signup summary and workspace upgrade screen consume
`/api/public/plans`. The platform owner's **Pricing → Published offers** selects
the immutable billing prices shown on those screens. Creating a billing price
does not publish it automatically. Publishing changes requires platform MFA,
a reason and the current offer version, and records an audit event.

## New offers

| Package | Monthly | Annual | Allowance |
| --- | --- | --- | --- |
| Free | ₹0 | ₹0 | Existing Free allowance |
| Pro individual | ₹149 | ₹1,499 | 1 member, 3 active cards |
| Pro workspace | ₹499 | ₹4,999 | 10 members, 50 active cards |
| Enterprise | Request a quote | From ₹999 per seat | 25-seat minimum, 5 cards per contracted seat |

Applicable taxes, physical NFC hardware and shipping are separate. Enterprise
is an annual contract. Its default minimum is ₹24,975 per year before tax.
Wallet, direct CRM, SAML/SCIM and Events remain unavailable.

## Preservation of existing billing

Migration 5 adds `pro-individual` and `pro-workspace` rather than editing the
legacy `pro` package. Existing plan definitions, prices, subscriptions and access
grants are untouched. This matters because legacy Pro's repository default is
10 cards, while the reviewed public site advertised 50. The new workspace
package explicitly grants 50 cards and avoids changing existing agreements.

Existing subscriptions retain their original provider mapping and management
flows. New online Enterprise checkout is rejected, including attempts using the
legacy Enterprise price ID. Legacy Enterprise prices remain available to the
operator for recording agreed offline contracts and reconciling existing billing.
No per-seat charging logic is implemented.

Enterprise quote requests require explicit contact consent, validation and rate
limits. They are saved for the elevated platform owner under Pricing. The page
shows the latest 100 requests. This flow sends no email automatically and does
not create a paid subscription. Agree a retention policy for these enquiries
before production use.

## Deployment prerequisites

These are rollout instructions, not a record of changes to production.

1. Back up the database. Apply the additive, checksummed
   `supabase/migrations/202610210005_india_pricing.sql` through
   `python scripts/db_migrate.py` before deploying this code. Existing migration
   files have not changed. Local SQLite uses `migrations/005_india_pricing.sql`.
2. Map the new prices to matching Razorpay plans before enabling checkout:
   `RAZORPAY_PLAN_PRO_INDIVIDUAL_MONTHLY`,
   `RAZORPAY_PLAN_PRO_INDIVIDUAL_ANNUAL`,
   `RAZORPAY_PLAN_PRO_WORKSPACE_MONTHLY`,
   `RAZORPAY_PLAN_PRO_WORKSPACE_ANNUAL`.
   Keep every existing mapping used by existing subscriptions.
3. Set `HUDDLE_PUBLIC_ORIGIN` when the workspace uses a separate app hostname.
   Enterprise quote links from workspace billing use that public origin.
4. Verify the homepage and monthly/annual pricing, individual signup, owner
   checkout, Enterprise enquiry and elevated owner inbox in staging.
5. Configure the agreed finite member/card limits through an organization access
   grant when fulfilling an Enterprise quote. Its published starting rate alone
   does not change any organization's entitlements.

The existing 14-day Pro trial remains the legacy Pro trial. This change does not
silently convert trials or existing customers into either new Pro package.

## Validation

Run `python -m unittest discover -s tests -v`,
`node --test tests/*.mjs` and the PostgreSQL suite described in
`scripts/test_postgres.py` against a disposable local database. Added tests cover
published price selection, stale edits, wrong-package/retired prices, consent,
private quote access, rate limits, individual checkout and quotas, legacy billing
preservation, and PostgreSQL runtime permissions.

## Sales enquiries and policy pages

Apply migration 6 (`202610210006_sales_enquiries.sql`) after migration 5. It adds
structured enquiry requirements to the existing private sales inbox. It does not
change tenant access or existing subscriptions. The backend retains only SELECT
and INSERT on enquiries; only elevated platform operators can read the inbox.
Enterprise and NFC enquiries share validation, contact consent, a honeypot and rate
limits. Hardware requests allow small quantities independently of Enterprise's
minimum. No email, order, payment or subscription is created by an enquiry.

Company pages: `/about`, `/contact`, `/terms`, `/privacy`, `/data-protection`,
`/refunds`, `/shipping`. Business details were supplied by the founder. The refund
policy excludes change-of-mind refunds after activation while preserving duplicate
or incorrect charge, non-delivery and mandatory legal remedies. These pages do not
claim Razorpay approval, certifications or universal DPDP compliance. Confirm the
public phone and named grievance contact if required by merchant verification.

`huddleapp.in` is the intended domain; adding a page does not configure DNS or HTTPS.
Connect it in Vercel, then update public/app/card origins to the actual chosen hosts.
Keep existing NFC links and authentication callbacks working during that change.
Razorpay plan mappings, webhook configuration and Resend setup remain separate.
