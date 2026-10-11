# DueCare mobile

The DueCare app for Android, built with Flutter (iOS is out of scope for now). It is a second client for the same FastAPI API and account as the web app: the same Somaiya Google sign-in, tasks, reviews, rules, sources and timetable, with DueCare's colours and status rules (`apps/web/DESIGN.md`) laid out as a native phone app: a bottom navigation bar, large collapsing titles, rounded cards and sheets, swipe actions and long-press selection.

## What it covers

- **Sign-in** with the verified `@somaiya.edu` Google account in the system browser. Signing in also grants the read-only Gmail and Classroom access, as on the web.
- **Week**: a greeting, the next deadline with a countdown, counts, "new since your last visit", a swipeable seven-day strip with status dots, the day's due items and a class timeline (with "Now"), and a month calendar.
- **Tasks**: search, status chips, a filter sheet, date or priority sort, infinite scroll, swipe right to mark done (or reopen) and left to delete, long-press to select several for done/reopen/move/delete, and task details with sources, change history, edit and delete.
- **Review** (Needs attention): every issue type with its actions, including subject and timing answers and faculty approval.
- **More**: subjects with weekly timetables, timetable upload (PDF or scheduler screenshots, draft review, dry-run summary, confirm), activity, notifications, profile and onboarding, KT notices, privacy operations, account deletion, Sources (sync, reprocess, disconnect, Classroom course links, approved faculty, sender preferences), rules (plain sentence or builder) and sign-out.
- **Offline**: the last saved lists show at once on launch and while the server is unreachable, with a banner. Data reloads only when the server's change stamp moves, which is the same mechanism as the web.
- **Notifications** (More → Notifications):
  - *Deadline reminders* at the lead times the student picks (1 week to 30 minutes before), for all work or only tests and high-priority work. They are scheduled on the phone, so they fire offline; "precise timing" uses Android's exact alarms when allowed.
  - *Daily summary* of what is due that day, at a chosen time.
  - *Instant updates* by push: new work, changes, items needing review, work marked done from a submission, and sync problems, each with its own switch.
  - *Quiet hours*, during which notifications arrive silently, and a test button.

## Push notifications

Pushes go through Firebase Cloud Messaging and carry no task content: only which kinds of event happened. The app wakes up, fetches the details with its own session, and shows a notification by name ("New: DBMS ER diagram · due 12 Oct, 5:00 pm"), grouping several. Every push also rebuilds the phone's reminder schedule, so work changed on the web never leaves a stale reminder. A push for an account that has signed out of the phone is ignored.

On the server, the background worker's `push` job (migration `0007`) watches each registered phone's account for new activity and task changes. It waits about 15 seconds for a sync burst to settle (two minutes at most), sends one message per phone, forgets tokens Google reports as unregistered, and backs off while FCM is unavailable. Choices live in `notification_settings`, and phones in `push_devices`. Both are owner-only under row-level security and are removed with the account.

To turn push on:

1. Create a Firebase project and add an Android app with package `app.duecare.mobile`.
2. Server: in Firebase **Project settings → Service accounts**, generate a private key. Put the JSON (one line or base64) in the API's `FCM_SERVICE_ACCOUNT`, apply migration `0007` (`uv run alembic upgrade head`) and redeploy.
3. App: create the ignored file `apps/mobile/firebase.json` with the Android app's values from **Project settings → Your apps**:

   ```json
   {"FIREBASE_API_KEY": "…", "FIREBASE_APP_ID": "1:…:android:…", "FIREBASE_SENDER_ID": "…", "FIREBASE_PROJECT_ID": "…"}
   ```

   Then build with `--dart-define-from-file=firebase.json`. No `google-services.json` is needed.

Without these, the app still schedules reminders and the daily summary, and shows updates when it is opened. The Notifications screen says when instant updates are not set up.

The configured DueCare Firebase project is `duecare-mobile-31712` (sender ID `407819843148`), with Android app `1:407819843148:android:29483290e339db73f4e6e9`. This checkout's ignored `firebase.json` contains the build values. The API uses the dedicated `duecare-fcm` service account with the Firebase Cloud Messaging API Admin role; its private key is kept outside source control, and `FCM_SERVICE_ACCOUNT` is a production Secret in Vercel. Builds must still include `--dart-define-from-file=firebase.json`; an older APK built without it cannot register for push.

## How it talks to the API

The phone calls the API directly, not through the Next.js gateway:

1. `POST /api/v1/mobile/auth/start` returns the Supabase Google URL (PKCE) and a one-use state. Supabase returns to `duecare://auth/callback` (`MOBILE_REDIRECT_URL`).
2. `POST /api/v1/mobile/auth/callback` with `{state, code}` returns an opaque session handle. This is the same encrypted server-side session the web keeps in an HTTP-only cookie. Redeeming a code needs the state too, which only this app holds.
3. Every request sends `Authorization: Bearer <handle>`. The handle is kept in the Android Keystore (`flutter_secure_storage`). Writes send an `Idempotency-Key`.
4. `POST /api/v1/mobile/auth/logout` ends the session. `POST /api/v1/mobile/account-deletion` follows an account deletion with its resume token after the login is gone.

On Vercel, `vercel.json` routes `/api/v1/mobile/*`, and `/api/v1/*` requests carrying a bearer token, straight to the API service. Browser traffic still goes through the gateway.

## Code layout

```
lib/
  main.dart, app.dart     start-up, theme, signed-in / signed-out / deleting
  config.dart             API origin (API_URL) and the sign-in deep-link scheme
  core/                   API client, session, query cache, IST time, models, timetable draft logic
  notifications/          choices, reminder/summary planning, notification display, push handling
  state/                  shared services, sync controller, quick complete
  ui/                     theme tokens (Palette), DueCare icons, shared widgets, task rows and due items
  screens/                one file per screen
tool/mark.py              renders the launcher, splash and notification icons from the mark's geometry
test/                     unit tests (time, deadlines, rules, timetable draft, API, cache) and widget tests
```

`core/query.dart` is a small query cache modelled on the web's TanStack Query. It provides keyed queries, invalidation by root key, paging and persistence, so screens follow the same reload rules as their web counterparts.

## Mark and icons

The app's mark is an answer bubble with a printed D, half filled in rose the way a student marks an answer. `Logo` and `MarkPainter` in `lib/ui/widgets.dart` draw it in the app; `tool/mark.py` draws the same 100-unit geometry for the adaptive launcher icon (with a monochrome layer for themed icons), the Android 12 splash and the status-bar notification icon. After changing the geometry, regenerate every asset:

```bash
uv run --with pillow python tool/mark.py android/app/src/main/res android
```

In-app icons come from `lib/ui/icons.dart`: one family on a 24-unit grid with a 1.7 rounded stroke, built from the answer sheet (bubbles, ruled lines, pencil, eraser). `filled: true` gives the selected state used in the navigation bar. System controls such as back, close, chevrons and the overflow menu stay Material, so Android behaves as people expect. The web app's logo is unchanged.

## Setup

Install Flutter 3.47 or later (`brew install --cask flutter`) and the Android SDK (Android Studio, or `brew install --cask android-commandlinetools`).

### Backend configuration (once per environment)

1. In `apps/api/.env`, set `MOBILE_REDIRECT_URL=duecare://auth/callback`. If it is empty, mobile sign-in is off.
2. In Supabase, go to **Authentication → URL Configuration → Redirect URLs** and add `duecare://auth/callback`.
3. Restart or redeploy the API.

### Run locally

Start the API (see the root README), then start the app:

```bash
cd apps/mobile && flutter run
```

Debug builds use `http://10.0.2.2:8000`, the host computer as the Android emulator sees it. To use another API, pass `--dart-define=API_URL=https://your-host`, for example to test on a physical phone against a computer on the same network.

### Release builds

```bash
cd apps/mobile && flutter build appbundle --dart-define=API_URL=https://duecare-xi.vercel.app --dart-define-from-file=firebase.json
```

Before publishing:

- Android release signing reads `android/key.properties` (`storeFile`, `storePassword`, `keyAlias`, `keyPassword`). Without this ignored file, local release builds use the debug key. Configure your upload key before publishing.
- The application ID is `app.duecare.mobile`.
- Google Play requires a privacy policy URL and data-safety answers. The app reads Gmail and Classroom through the API, and the restricted `gmail.readonly` scope needs Google verification before a public release (see the root README).

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

- Reminders are scheduled from what the app last saw and refreshed when a push arrives. Android can delay delivery or stop it after the app is force-stopped; opening the app refreshes its data and reminders again.
- Home-screen widgets are not included.
