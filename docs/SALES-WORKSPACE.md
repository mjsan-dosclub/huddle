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

Elevated Super Admin manages all enquiries and sales access. In Sales enquiries →
Sales team, enter an existing colleague's HUDDLE login email and a reason. This
creates sales-only access, not a platform administrator. No invite email is sent.
The colleague signs in at `/sales` and can read, update and export only assigned
enquiries. They cannot assign enquiries, manage sales grants, billing or packages.
Normal session, organization membership and MFA checks continue to apply. Revoking
sales access immediately blocks this sales workspace; assignments remain for admin
reassignment. No sales colleagues are provisioned by the migration.

## Filters and export

Search contact/company/email; filter stage, type, assignee, received date (UTC) and
follow-up due state. Dates displayed and entered for activities use the viewer's
local timezone and are stored as epoch timestamps. Lists are paginated at 25 rows.
Export includes all matching records up to 5,000, not just the visible page. Larger
exports require narrower filters. Exports enforce the same assignment scope,
neutralize spreadsheet formula prefixes and record a count/scope audit event.
Due state is a visual/filter feature; scheduled notifications are not implemented.

## Release

Apply `202610210007_sales_workflow.sql` with the checksummed runner before deploying.
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
