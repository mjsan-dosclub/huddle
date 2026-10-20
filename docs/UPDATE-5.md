# HUDDLE Update 5

Ownership runtime constants and the 0.8.0 welcome layout below are historical; see [Package manager](PACKAGE-MANAGER.md) for the current database-backed configuration and Android 0.8.1.

## Organization ownership

Enforced server-side at `create_org`, including API registration and authenticated creation. Allowances are centralized in `billing.OWNED_ORGANIZATION_LIMITS`: Free 2, Pro 5, Enterprise 20. The highest currently effective plan in an active owned organization determines the account allowance. Membership invitations do not count or lend paid access. Each new organization starts Free with its own card/member quotas. Suspended organizations still count; existing organizations are preserved and remain switchable when active after an allowance expires. Account-row locking and serializable PostgreSQL mutation transactions prevent concurrent check/create races. No schema migration is required.

## Environmental scenario

Replaces the money-saving slider with adjustable people, paper cards per person/year and NFC replacement cards avoided per person/year. Formula: paper cards × 0.085 m × 0.055 m × 350 g/m² / 1000 = kg paper. Tree equivalent uses the rough 24 trees/tonne printing-paper figure in *Sustainable Materials: With Both Eyes Open* (Allwood/Cullen; source linked in UI). Applying it to card stock is explicitly illustrative; not a verified trees-saved, stock-specific, carbon or lifecycle measurement. Plastic is counted separately as hypothetical replacements avoided by reusing an existing NFC card, without a plastic mass or tree conversion. NFC manufacture and digital infrastructure are excluded.

## Current availability

Invited corporate Members can sign in, edit permitted card fields and use native Android views or the responsive website. Organization field locks and all existing tenant boundaries remain enforced. The website is not an installable/offline PWA; iOS can use the responsive website today.

Apple Wallet and Google Wallet endpoints remain configuration-required scaffolds, not working passes. Production rollout needs actual pass generation, Apple pass certificates/IDs or Google issuer/service account, provider validation and signed pass tests.

Android 0.8.0 adds native red/cream branding, a real workspace-loading state, first-run swipeable/skip-enabled intro and replay under App settings. The package ID and development signing identity are preserved. NFC hardware testing remains a physical-device step.
