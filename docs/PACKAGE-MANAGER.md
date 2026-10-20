# Central package policies and Android 0.8.1

## Source of truth

The private `plans.entitlements` JSON is the sole runtime source for ownership, card, seat, admin and feature allowances. Migration 4 seeds ownership defaults once, only if missing. No ownership quota values remain in runtime Python/JavaScript/Java. Null means unlimited. Existing tenant grants continue to override only their existing card/seat/admin keys.

Platform owners use Super Admin → Package manager. Every save requires the existing elevated platform session/MFA, a reason and matching package version. Updates preserve price records and payment contracts, increment the package version and write before/after definitions to the platform audit. Ordinary Owners, Admins and Members cannot call this API. Changes apply to new requests; existing records are never automatically deleted.

## Migration and permissions

Apply `supabase/migrations/202610200004_package_policy.sql` with the checksummed migration runner before deploying the new application. It adds the ownership setting and grants the backend UPDATE on only `plans.name`, `plans.version`, and `plans.entitlements`. INSERT/DELETE, plan ID changes and platform-admin grant mutation remain prohibited. SQLite applies its paired migration automatically. Production requires this explicit migration; requests do not run cloud migrations. Missing ownership settings fail closed.

## Invitation capacity

Every invitation reserves both a member seat and a card. Web and native state expose an explanatory invitation-capacity status to organization administrators. Invite and invitation-management menus remain reachable; when full they show current usage and a notice instead of a submission form. Existing pending invitations can still be inspected/revoked. All create, import and acceptance paths continue to validate quotas in server transactions; concurrent/stale clients cannot bypass enforcement.

## Android design

Native full-screen swipe/tap welcome scenes replace the boxed layout. They use HUDDLE cream, red and peach, large text and layered business-card/leaf drawings. A compact arrow and plain Skip remain accessible alternatives to gestures. The connection splash animates an illustrative one-person scenario (200 cards/year ≈ 0.33 kg paper at 85 × 55 mm, 350 gsm), not measured personal activity or a carbon claim. No timed loading delay is added. System bars remain available. Physical-device visual/NFC validation is still required.
