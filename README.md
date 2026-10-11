# DueCare

Your academic week, in one place. DueCare brings assignments and tests from Gmail, Google Classroom and your own notes alongside your class timetable.

Built for KJSSE BTech students using a verified `@somaiya.edu` Google account.

[Open the web app](https://duecare-xi.vercel.app) · [Android downloads](https://github.com/dhruvwarriorr/DueCare/releases)

## Android app

Download the `DueCare-<version>.apk` asset from a published GitHub release, open it on your Android phone, and allow installation from your browser or file manager if prompted. Sign in with your Somaiya Google account. The app uses the same account and data as the website.

The first release is being prepared as a draft. Draft assets become available to readers after the release is published; a private repository also requires repository access.

## Features

- A weekly view of deadlines and classes, with a month calendar.
- Tasks from Gmail and Classroom, plus tasks you add yourself.
- Subjects and timetables, entered manually or imported from PDFs and scheduler screenshots.
- Review questions when an import needs your input, with source history and completion reconciliation.
- Android deadline reminders, a daily summary and optional push notifications.
- Offline viewing of saved work, source controls and account deletion.

Google access is read-only. Sign-in and source access depend on the configured Google consent and university policies.

## Repository layout

| Path | Contents |
| --- | --- |
| `apps/web/` | Next.js website and same-origin API gateway |
| `apps/api/` | FastAPI service, database migrations and authorization SQL |
| `apps/mobile/` | Flutter Android app and icon generator |
| `docs/` | Local documentation, ignored by Git |
| `scripts/` | Signed Android release packaging |
| `supabase/` | Supabase configuration |

## Development

Use Node 24, Python 3.13 with uv, Flutter 3.47.7 and PostgreSQL 18. Copy the app-specific `.env.example` files and configure your own credentials before running services.

```sh
npm ci
uv sync --project apps/api --frozen
```

Start the API with `uv run --project apps/api uvicorn duecare.main:app --reload --host 127.0.0.1 --port 8000`, then run `npm run dev` in another terminal. Apply database migrations and configure Google/Supabase authorization before signing in.

See [Android setup](apps/mobile/README.md) for the mobile app. Run `scripts/build-android-release.sh` to build a signed APK after configuring its permanent signing key.

Detailed project documentation stays local and is ignored by Git. Environment files, signing keys, Firebase build configuration, generated binaries and private reference material are also excluded from source control. APKs belong in GitHub Releases rather than the source tree.
