# HUDDLE

**Digital business cards. Better introductions. Lasting connections.**

HUDDLE helps individuals and teams share their identity through a link, QR code or optional NFC card. Recipients open the card in their browser—no app or account required.

[Explore HUDDLE](https://huddle-alpha-ruby.vercel.app/) · [Card templates](https://huddle-alpha-ruby.vercel.app/templates) · [Pricing](https://huddle-alpha-ruby.vercel.app/pricing)

## What you can do

- **Create and share cards:** Choose a template, manage card personas and add contact details, WhatsApp and UPI blocks.
- **Manage your team:** Organize divisions, invite members in bulk and keep branding consistent with approved templates and field controls.
- **Keep connections:** Capture contact exchanges with consent, review networking activity and export leads on eligible plans.
- **Use NFC:** Assign, reassign or deactivate card links; write and verify compatible tags with the native Android admin app.
- **Run the platform:** Manage organizations, packages, usage limits, pricing and human-readable audit history from Super Admin.

Organizations have separate data and Owner, Admin and Member permissions. Plan features and limits are managed centrally.

## Built with

Python/Flask, JavaScript, HTML and CSS. Vercel hosts the web application; Supabase provides PostgreSQL and private image storage. Local development supports SQLite. The Android app uses native Java views and NFC APIs.

## Project status

HUDDLE is under active development. Web cards, team management and the Android test app are available. Razorpay billing requires provider configuration; email delivery and Google sign-in also need configured providers. Apple/Google Wallet passes, direct CRM sync and an iOS app remain planned.

## Guides

- [Deployment and local setup](docs/DEPLOYMENT.md)
- [Subscriptions and platform operations](docs/MONETIZATION.md)
- [Central package management](docs/PACKAGE-MANAGER.md)
- [Super Admin interface](docs/SUPER-ADMIN-UX.md)
- [Android app and build instructions](android/README.md)

Application source lives in the root Python modules and `static/`; database changes in `migrations/` and `supabase/migrations/`; automated checks in `tests/`.
