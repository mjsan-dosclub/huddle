# Super Admin workspace

The console shares the logged-in HUDDLE fonts and colour tokens. A light cream/peach overview banner and Super Admin marker distinguish platform-wide controls. Account controls and Lock console are in the top-right disclosure menu.

## Navigation

- `/super-admin`: business overview; calculation notes are collapsed.
- `/super-admin/organizations`: searchable, paginated organization table.
- `/super-admin/organizations/:id`: dedicated management page with Overview, Access & package, Billing and Support sections.
- `/super-admin/packages`: compact package table.
- `/super-admin/packages/:id`: General, Usage limits and Features tabs. Switching tabs keeps entered values; hidden invalid fields are revealed before validation feedback. Package version checks remain enforced.
- `/super-admin/pricing`: billing prices; creation and availability editing use dedicated pages. Fractional INR values are preserved.
- `/super-admin/audit`: human-readable activity table with search, date filters and pagination. Details show before/after package values; raw technical data is behind a disclosure.

## Audit history

Audit events record the actor, action, organization, reason and time. The API now resolves operator email and organization name, adds action labels and supports searching by their readable labels. The default view pages through all retained records, 25 at a time. Date filters change only the view. No retention schedule, archive job, purge or deletion controls were added. Existing append-only protections remain in place.

## Safety and verification

Platform grants, independent MFA, session duration, support read-only restrictions and tenant boundaries are unchanged. No database migration is needed. All edits during browser QA used an isolated sample database; no customer package, price, payment or access was changed. Browser QA covered navigation, direct links, browser Back, package tabs/save, access grants, audit search/diffs, fractional price creation/retirement, support inspection/closure, desktop and 390px layouts.
