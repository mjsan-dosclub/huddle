# Public card URLs

Customers can choose a card name in **My card → Set public URL**, **Card personas → Public URL**, or an administrator's team member editor. Owners and Admins can also change the shared organization URL in that dialog.

The canonical format is `/c/{organization}/{card-name}`, such as `/c/touchmark/mohanraajg`. Another organization can use the same card name. Two cards in one organization need different names, such as `mohanraajg-sales` and `mohanraajg-events`. Availability checks provide suggestions; they do not reserve a name. Saving atomically claims it.

New names use 3–60 lowercase ASCII letters, digits or single hyphens. System names are reserved. Existing generated names remain until edited. Names are routing labels; immutable card IDs and active organization membership continue to enforce access. A readable name is not verification of a person's identity or trademark ownership.

## Ownership and old links

Migration 8 registers every existing short link and its namespaced counterpart without changing `cards.slug`. This internal legacy field remains stable for older clients. Current web state and share APIs return the canonical namespaced address. Existing signup short handles remain globally unique aliases; this release does not add a new short-alias marketplace or globally exclusive personal name.

Every saved path is permanently reserved to the same tenant/card ID. Renaming a card or organization adds new aliases and preserves all old ones. Public resolution goes directly from an alias to the card ID, without redirect chains. Saving an old name for its original card is allowed; transferring it to another card or organization is not. The backend cannot UPDATE or DELETE alias and namespace reservations. Hard deletion/reassignment of these records is not an application feature; any future erasure workflow must retain non-identifying tombstones before removing ownership records.

Removed members, unpublished cards, disabled templates and suspended organizations remain unavailable at **every** alias. An NFC tag's explicit managed reassignment still changes that tag's destination; it does not transfer the former employee's URL. Create a new member/card for a replacement employee instead of reusing the old member's identity. Organization join slugs use the current organization namespace; communicate a new join slug after renaming.

## Boundaries and consistency

Authenticated availability and rename APIs scope the card to the active organization first. Members edit only their own cards. Admins cannot edit another Owner's URL; Owners can. Only Owners/Admins change the organization namespace. Existing authenticator elevation rules apply. Updates carry the expected current path/namespace and reject stale edits. Unique database constraints and transactional reservations prevent concurrent claims; conflicts roll back the complete operation. Validation and rate limits run server-side.

QR exports, NFC redirects, public cards, vCard URLs, contact exchange, activity, manifests, email signatures and meeting backgrounds resolve aliases and use the current canonical destination. Wallet providers remain configuration-dependent scaffolds; no wallet issuance is added here. Public canonical metadata identifies the current URL. Old card pages still open with the new canonical model and contact actions.

## Deployment

Apply paired schema migration 8 before deploying. PostgreSQL tables are private with RLS and backend-only policies. The runtime receives SELECT/INSERT on reservations and settings, UPDATE only on settings.card_slug, and organization slug update. Namespace/alias bindings cannot be transferred by the runtime. The optional SQLite importer preserves schema-8 reservations or backfills them for older sources. No existing subscription or public card is deleted.

Tests cover cross-organization duplicate names, within-organization conflicts and suggestions, concurrent claims, old aliases after card/organization rename, stale updates, invalid and encoded paths, unpublished/suspended/removed states, member permissions, QR/vCard/manifest/share routing, and PostgreSQL runtime privileges.
