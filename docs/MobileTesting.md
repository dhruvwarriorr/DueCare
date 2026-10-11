# Android emulator testing — 11 October 2026

Environment: Pixel 7 AVD (`duecare`), Android 16 / API 36, ARM64, 1080 × 2400. The synthetic integration run used software graphics and `--no-dds` after intermittent emulator/debugger disconnections. That suite called the synthetic FastAPI server at `http://10.0.2.2:8001`, backed by the isolated local test database, without real Google accounts, email, Classroom data, or AI providers. Later interactive production sign-in checks are recorded separately below.

## Verification

| Check | Result |
| --- | --- |
| Flutter analysis | No issues |
| Flutter unit/widget suite | 21 passed |
| API suite | 167 passed |
| Android integration scenarios | 2 passed: online workspace/task lifecycle and offline cache/recovery |
| Interactive production Google sign-in | Passed: real Somaiya login, mobile callback exchange, authenticated `/me`, secure-storage readback and sign-in screen dismissal |
| Debug APK | Built for the synthetic local API |
| Release APK | Built with `API_URL=https://duecare-xi.vercel.app`; APK signature verified |

The device tests exercise the real Flutter app, secure storage, preferences and native plugins. The online scenario starts through `main.dart`, opens Week, Tasks, task details, Review and More, and visits Subjects, Profile & privacy, Sources, Rules and Activity. It checks required-title validation, task creation, search, editing, completion/reopening, quick completion with Undo, confirmed task deletion, and review resolution against API state.

The second scenario creates a new app service instance from the device's saved workspace, injects a connection failure, and verifies that Week and Tasks remain readable with an offline banner. Real HTTP resumes afterward; the banner disappears and fresh tasks load. Removing the local session returns to sign-in and clears the saved private workspace. This simulates a transport failure; it does not toggle Android's network settings or power-cycle the emulator.

The captured main screens were visually inspected. No Flutter layout exceptions were reported in the passing scenarios. The initial device attempt could not reach the previous background API process; restarting the synthetic server and regenerating the fixture session resolved that environment failure.

Testing also found that cache cleanup returned without awaiting the platform's saved-data removal. `QueryClient.clear()` now awaits that operation, with a regression test confirmed to fail on the previous code and pass with the fix. The restart scenario also lets the previous test instance finish its debounced save before creating another instance, since an actual process restart cannot leave the old process's timer alive.

## Evidence

The repeatable tests are in `apps/mobile/integration_test/workspace_test.dart`, with the screenshot driver in `apps/mobile/test_driver/mobile.dart` and guarded fixture setup in `scripts/seed-mobile-test.py`. Run instructions are in `apps/mobile/README.md`.

Local evidence, kept out of Git:

- `.local/mobile-qa/integration.log`
- `.local/mobile-qa/01-week.png` through `12-activity.png`
- `.local/mobile-qa/13-offline-week.png`, `14-offline-tasks.png`, `15-recovered.png`, `16-signed-out.png`
- `apps/mobile/build/app/outputs/flutter-apk/app-debug.apk`
- `apps/mobile/build/app/outputs/flutter-apk/app-release.apk`

The release APK uses the fallback Android debug certificate until `android/key.properties` is configured. The synthetic debug session was checked to be absent from the release app libraries. The synthetic suite does not establish production sign-in; the later real sign-in acceptance test uses an instrumented debug build with the production API and no `DEV_SESSION`.

## Production mobile authentication configuration

On 11 October 2026, `MOBILE_REDIRECT_URL=duecare://auth/callback` was added to the local API environment and Vercel production environment. The exact callback was added to DueCare's Supabase Auth redirect allowlist, preserving both existing localhost and production web callbacks and the production Site URL.

Deployment `dpl_88kjVizsR7QmmYYUPvfhGKZBmwnZ` was built from the local checkout, checked, and promoted to `https://duecare-xi.vercel.app` without committing or pushing Git changes. Type checking and lint passed. The deployment input check excluded local secrets, fixture data and the Flutter project.

Public production verification returned HTTP 200 for `/health`, `/ready`, `/sign-in` and `/api/v1/mobile/auth/start`. The mobile response contains the exact app callback and an S256 PKCE challenge; Supabase redirects it to Google with HTTP 302. An invalid bearer session returns HTTP 401. The existing web login also returns HTTP 200, sets its login-state cookie, retains the web callback and reaches Google with HTTP 302. The deployment's error-log scan was empty at verification time. These checks stop before account sign-in and consent; they do not prove the code exchange and return to the app after Google login.

Safe verification summaries and the Supabase dashboard screenshot are saved under `.local/mobile-qa/`. The local API settings were checked to load the new callback; no normal local API process was running to restart, and the separate synthetic test server was left running.

## Real Google sign-in acceptance

The user completed Google sign-in and consent with a real Somaiya account on the emulator. `integration_test/real_sign_in_test.dart` used the production API with `DEV_SESSION` empty. It verified that the app redeemed the mobile callback, authenticated `/api/v1/me` for a Somaiya identity, read the same session back from native secure storage, and dismissed the sign-in screen. The passing log is `.local/mobile-qa/real-sign-in-kept.log`.

A separate fresh launch with `REQUIRE_SAVED_SESSION=true` also passed: the app restored its saved session, authenticated `/api/v1/me`, and remained signed in without opening Google. Its log is `.local/mobile-qa/real-sign-in-kept-restart.log`. The normal production-configured release APK was then installed with `adb install -r` and opened, preserving app data. The interactive test source also passed Flutter analysis.

Two test-tool issues initially confused acceptance: live-test bindings discard manual app taps unless `shouldPropagateDevicePointerEvents` is enabled, and Flutter's driver stops and **uninstalls** the app by default. An initial pointer-setting cleanup assertion failed after successful authentication; a subsequent restart check was invalid because the runner had uninstalled the app and deleted its data. The Android crash buffer was empty. The interactive harness now enables device taps before the test begins, and its documented command uses `--keep-app-running` to preserve the installed app and session. These were harness corrections, not changes to production sign-in code.

## Remaining checks

- Real Somaiya Google sign-in and consent have now completed on the emulator, including the `duecare://auth/callback` handoff. Physical-device acceptance remains below.
- Run on a physical Android phone and build/run iOS with Xcode.
- Check notification delivery at an actual deadline, tapping a delivered notification, and reminder restoration after reboot. Notification permission was pregranted for emulator automation.
- Exercise native timetable file selection/upload and the remaining source/rule/privacy editing flows on a device; opening their screens is only a navigation check.
- Configure the Android upload key before store distribution.

Changes remain local and uncommitted.
