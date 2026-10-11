# DueCare mobile

The DueCare app for Android and iOS, built with Flutter. It is a second client for the same FastAPI API and account as the web app: the same Somaiya Google sign-in, tasks, reviews, rules, sources and timetable, with the same answer-sheet design (`apps/web/DESIGN.md`).

## What it covers

- **Sign-in** with the verified `@somaiya.edu` Google account in the system browser. Signing in also grants the read-only Gmail and Classroom access, as on the web.
- **Week**: the next-due band with a countdown, summary counts, "new since your last visit", a seven-day strip with status ticks, the day's due items and classes, and a month view.
- **Tasks**: search, status bubbles, more filters, date or priority sort, paging, one-tap done with Undo, bulk complete/reopen/move/delete, and task details with sources, change history, edit and delete.
- **Review** (Needs attention): every issue type with its actions, including subject and timing answers and faculty approval.
- **More**: subjects with weekly timetables, timetable upload (PDF or scheduler screenshots, draft review, dry-run summary, confirm), activity, profile and onboarding, KT notices, deadline reminders, privacy operations, account deletion, Sources (sync, reprocess, disconnect, Classroom course links, approved faculty, sender preferences), rules (plain sentence or builder) and sign-out.
- **Offline**: the last saved lists show at once on launch and while the server is unreachable, with a banner. Data reloads only when the server's change stamp moves, which is the same mechanism as the web.
- **Reminders**: notifications a day and an hour before each due task, scheduled on the phone. They fire offline and are rebuilt whenever the app sees tasks change.

## How it talks to the API

The phone calls the API directly, not through the Next.js gateway:

1. `POST /api/v1/mobile/auth/start` returns the Supabase Google URL (PKCE) and a one-use state. Supabase returns to `duecare://auth/callback` (`MOBILE_REDIRECT_URL`).
2. `POST /api/v1/mobile/auth/callback` with `{state, code}` returns an opaque session handle. This is the same encrypted server-side session the web keeps in an HTTP-only cookie. Redeeming a code needs the state too, which only this app holds.
3. Every request sends `Authorization: Bearer <handle>`. The handle is kept in the iOS Keychain or Android Keystore (`flutter_secure_storage`). Writes send an `Idempotency-Key`.
4. `POST /api/v1/mobile/auth/logout` ends the session. `POST /api/v1/mobile/account-deletion` follows an account deletion with its resume token after the login is gone.

On Vercel, `vercel.json` routes `/api/v1/mobile/*`, and `/api/v1/*` requests carrying a bearer token, straight to the API service. Browser traffic still goes through the gateway.

## Code layout

```
lib/
  main.dart, app.dart     start-up, theme, signed-in / signed-out / deleting
  config.dart             API origin (API_URL) and the sign-in deep-link scheme
  core/                   API client, session, query cache, IST time, models, timetable draft logic
  state/                  shared services, sync controller, reminders, quick complete
  ui/                     theme tokens (Palette), shared widgets, task rows and due items
  screens/                one file per screen
test/                     unit tests (time, deadlines, rules, timetable draft, API, cache) and widget tests
```

`core/query.dart` is a small query cache modelled on the web's TanStack Query. It provides keyed queries, invalidation by root key, paging and persistence, so screens follow the same reload rules as their web counterparts.

## Setup

Install Flutter 3.47 or later (`brew install --cask flutter`). Android builds need the Android SDK (Android Studio, or `brew install --cask android-commandlinetools`). iOS builds need Xcode and CocoaPods.

### Backend configuration (once per environment)

1. In `apps/api/.env`, set `MOBILE_REDIRECT_URL=duecare://auth/callback`. If it is empty, mobile sign-in is off.
2. In Supabase, go to **Authentication → URL Configuration → Redirect URLs** and add `duecare://auth/callback`.
3. Restart or redeploy the API.

### Run locally

Start the API (see the root README), then start the app:

```bash
cd apps/mobile && flutter run
```

Debug builds use `http://10.0.2.2:8000` on the Android emulator and `http://127.0.0.1:8000` on the iOS simulator. To use another API, pass `--dart-define=API_URL=https://your-host`, for example to test on a physical phone against a computer on the same network.

### Release builds

```bash
cd apps/mobile && flutter build appbundle --dart-define=API_URL=https://duecare-xi.vercel.app
```

```bash
cd apps/mobile && flutter build ipa --dart-define=API_URL=https://duecare-xi.vercel.app
```

Before publishing:

- Android release signing reads `android/key.properties` (`storeFile`, `storePassword`, `keyAlias`, `keyPassword`). Without this ignored file, local release builds use the debug key. Configure your upload key before publishing.
- iOS needs your Apple team selected in Xcode (Runner → Signing & Capabilities). The bundle identifier is `app.duecare.mobile`, and the Android application ID matches.
- Google Play and the App Store require a privacy policy URL and data-safety answers. The app reads Gmail and Classroom through the API, and the restricted `gmail.readonly` scope needs Google verification before a public release (see the root README).

## Tests

### Real Google sign-in (interactive)

With the production mobile callback configured, run this from `apps/mobile`:

```bash
flutter drive --no-dds --keep-app-running --driver=test_driver/mobile.dart \
  --target=integration_test/real_sign_in_test.dart -d emulator-5554 \
  --dart-define=API_URL=https://duecare-xi.vercel.app
```

Do not pass `DEV_SESSION`. To exercise a fresh Google login, sign out in the normal app first. A person completes Chrome setup, Google sign-in and consent in the emulator. The test waits up to 12 minutes, then checks the returned session with authenticated `/api/v1/me`, reloads secure storage, and confirms that the sign-in screen closes. If a session is already saved, it verifies session restoration after restarting instead. It calls the real backend and can connect Gmail/Classroom sources; it is separate from the synthetic suite below.

After a successful login, add `--dart-define=REQUIRE_SAVED_SESSION=true` to require the saved session on the next app launch. This fails immediately if restoration is missing, without opening Google again. Keep `--keep-app-running`: without it Flutter's driver stops and uninstalls the test app, deleting its session and invalidating a subsequent persistence check. Install the normal APK with `adb install -r` afterward for manual use without deleting app data.

```bash
cd apps/mobile && flutter analyze && flutter test
```

The tests run without a network or device. Widget tests drive the app against a fake API on a phone-sized screen and turn off font downloads (`fetchFonts = false`).

### Android emulator integration tests

The device tests use the synthetic API on port 8001 and the isolated test database on port 55432. Start that database and provision it using the root README's test setup, then start the fixture API from `apps/api`:

```bash
uv run uvicorn tests.e2e_server:app --host 127.0.0.1 --port 8001 --no-access-log
```

From the repository root, seed the disposable account and generate an ignored debug configuration:

```bash
uv run --project apps/api python scripts/seed-mobile-test.py
```

Start an Android emulator, then run from `apps/mobile`:

```bash
flutter drive --no-dds --driver=test_driver/mobile.dart \
  --target=integration_test/workspace_test.dart -d emulator-5554 \
  --dart-define-from-file=../../.local/mobile-debug-defines.json
```

The seed script refuses databases outside the local test database and accounts outside the synthetic fixture. Rerun it before each device test to reopen the review question. Run the API suite before seeding; those tests share the isolated database. Keep the fixture API running throughout the device tests. The offline phase injects a transport failure, then restores real HTTP against that API.

Screenshots are saved under `.local/mobile-qa/`. The session in the debug configuration is only for the synthetic account; never commit that file or use it for a release build. The emulator's notification permission can be granted in advance with `adb shell pm grant app.duecare.mobile android.permission.POST_NOTIFICATIONS` after the app is installed.

See [the Android test report](../../docs/MobileTesting.md) for the verified flows and remaining device checks.

## Known limits

- Reminders are scheduled from what the app last saw. Work that arrives while the app stays closed gets reminders the next time it opens. Server push (Firebase/APNs) would close that gap, but it needs a Firebase project and Apple push credentials, so it is not wired up.
- Home-screen widgets are not included.
