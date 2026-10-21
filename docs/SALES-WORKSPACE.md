# Sales enquiries and follow-up

Public Enterprise and NFC enquiries appear under **Super Admin → Sales enquiries**,
separate from Pricing. Existing enquiries are preserved and start at New. Migration
7 adds a received event dated from the original request; it does not invent past
calls or support interactions.

## Workflow

- New → Opened → Contacted / Follow-up / Demo requested → Won or Lost.
- Opening an enquiry records its first opened event through an explicit write API.
- Log a call, email, WhatsApp exchange, meeting or internal note with an outcome,
  comment, stage and next date. This records activity; it does not send messages.
- Follow-up and Demo stages require a next date. Closing Won/Lost clears that date.
- A won enquiry does not automatically create an organization, order or subscription.
- Assignment and activity changes use optimistic versions and append history with
  the acting account. Stale updates return 409 rather than overwriting another user.
- Timeline pages contain 50 events; Older/Newer navigation preserves access to history.

## Access

Elevated Super Admin manages all enquiries and sales access. In **Sales enquiries → Sales team**, create an internal login with name, work email and an initial password (12–256 characters). The administrator may require a password change on next sign-in; this is selected by default. No customer signup, organization, card, paid seat or subscription is created.

Colleagues sign in at `/sales/login`. They can read, update and export only assigned enquiries. They cannot assign enquiries, manage other colleagues, billing or packages. The header includes Change password and Sign out. A required initial password change blocks enquiry APIs until completed. Password changes require the current staff password and sign out every staff session. Super Admin can reset a colleague's staff password, with a reason and the same optional next-sign-in change requirement. A reset does not reactivate removed access.

Sales passwords are separate from customer passwords, even when the same email already belongs to a customer. An account identity row supports existing assignment/audit foreign keys, but internal credentials and sessions use separate private tables and a distinct HttpOnly, SameSite=Strict cookie (Secure in production). Sessions last eight hours and carry the credential version; reset, self-change and access revocation invalidate existing sessions. Passwords are hashed using the application's salted PBKDF2 implementation and are excluded from API results, lists and audit details. Provisioning or resetting a platform administrator's identity through this interface is blocked. Platform team-management actions still require elevated platform MFA.

Older sales grants can continue using their existing customer session until an administrator creates internal credentials for that email. After that, sales access requires the separate internal login. Existing customer passwords, MFA and customer sessions are unaffected. No real colleague is automatically provisioned by a migration.

### Sharing instructions

Copy instructions is the default. After creation/reset, the administrator may explicitly include the initial password in the copied text. That password remains only in the current page's temporary state; the server does not return or retain it in plaintext. Closing/navigating removes the one-time sharing view. Later copies contain the sign-in URL/email and say the password is provided separately; forgotten passwords require a reset. Nothing opens or sends a WhatsApp message automatically.

Email delivery is displayed as a disabled later option and rejected by the API. No email is sent in this release, including when Resend is configured for customer invitations. Enabling staff instruction emails requires a separate delivery workflow and review.

## Filters and export

Search contact/company/email; filter stage, type, assignee, received date (UTC) and
follow-up due state. Dates displayed and entered for activities use the viewer's
local timezone and are stored as epoch timestamps. Lists are paginated at 25 rows.
Export includes all matching records up to 5,000, not just the visible page. Larger
exports require narrower filters. Exports enforce the same assignment scope,
neutralize spreadsheet formula prefixes and record a count/scope audit event.
Due state is a visual/filter feature; scheduled notifications are not implemented.

## Release

Apply all pending migrations with the checksummed runner before deploying. Migration 7 adds the sales workflow. Migration 9 adds private staff credentials/sessions, narrow credential UPDATE and session DELETE permissions; credential records cannot be deleted by the runtime.
It grants limited workflow-column UPDATE on enquiries, sales-grant SELECT/INSERT
and restricted UPDATE, and event SELECT/INSERT. Events have no backend UPDATE or
DELETE privilege. All new tables use private-schema access and RLS; tenant Owners
and ordinary accounts cannot call sales APIs without a separate sales grant.
Local SQLite uses the paired migration. No existing enquiry or subscription is deleted.

## Support tickets — discussion only

Keep sales enquiries and customer problems as separate records with a shared
activity concept. A future support ticket should link an organization/contact,
issue category, severity, owner, status and resolution, with explicit support-role
permissions and internal/customer-visible note boundaries. Do not turn sales
contact consent into consent for support marketing, or give support users billing
and platform powers. Ticket intake, SLAs and customer replies are not built here.

## Enquiry form experience

NFC-specific fields are hidden and disabled until Physical NFC cards is selected
on the Enterprise form. The dedicated NFC form starts with that requirement
selected. Hidden fields are not validated or submitted as hardware preferences.
After successful submission the form is replaced with a focused confirmation,
reference and Home / Send another enquiry actions. Failed requests keep the inputs
available. Sending another enquiry resets conditional fields to their defaults.
