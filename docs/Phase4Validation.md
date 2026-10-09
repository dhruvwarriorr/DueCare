# Phase 4: local implementation and verification

Verified on 7 October 2026. The requested scope is **localhost only**, as confirmed by the student. The remaining web workflows are implemented and locally verified. Public deployment and production Google approvals are deferred; this document does not certify them.

## Delivered workflows

| Requirement | Behavior | Evidence |
| --- | --- | --- |
| Activity inbox | New tasks, edits/source revisions, reopening, new reviews, and sync failures create content-free notifications in the triggering transaction. Cursor pagination, read/unread filters, unread navigation count, and revision-checked read state. Open links to the task, exact review, or Sources. | API ownership/read tests; mobile browser read/unread and task navigation. |
| Fresh sync results | Each bounded sync step invalidates task, evidence, history, review, activity, subject and connection caches. New reviews appear after reprocessing without a manual page reload. | Full browser interpretation/reprocessing workflow. |
| Disconnect | The disconnected state and cancelled sync jobs commit before contacting Google. Tasks and source evidence remain. A shared Google grant is revoked only when its last connection disconnects. Temporary Google failure leaves a saved retry operation. | Existing shared-grant tests; new outage and resumability integration tests. |
| Delete imported data | Separate confirmation in Settings. A saved operation stops source sync, removes that connection's evidence, reviews, source-derived history and records, and drops merge snapshots containing erased source data. Source-only unedited tasks are removed; student-created tasks, student edits and tasks supported by other sources remain. Edited source-only tasks become manual. | API preservation/isolation tests; browser confirms one removed task and one retained task with its note. |
| Deleted-import suppression | Account/service namespace and activity identity are hashed. Suppression survives reconnecting to the same Google account. Known digest activities are suppressed separately. Applying/replaying an import checks suppression before changing a task. Cached mutation responses containing erased task/source data are tombstoned. | Delete/replay, per-activity suppression, cached-response erasure, and explicit restore/reimport tests. |
| Restore and reimport | Restore makes a suppressed activity eligible; it does not recover a backup or create a task. Explicit Reimport resets the source checkpoint and reconsideration revisions, subject to the normal import history window. An active privacy operation blocks restoration, reimport and reconnection to the affected Google account. | API gates and reimport tests; browser restore without silent task recreation. |
| Account deletion | Typed DELETE confirmation freezes the workspace, cancels sync, revokes source grants, purges owned data in saved steps, then removes native Supabase Auth records and app sessions. A server-only capability cookie resumes deletion after session removal. An authenticated second browser can recover a pending checkpoint. | Synthetic native Auth deletion, cross-student preservation, forged-capability rejection, Google outage/retry, browser cookie secrecy and reload recovery. |
| Retention | Unlinked expired source records are hidden immediately and physically purged during later application activity. Linked accepted evidence remains until deletion. Active deletion checkpoints never expire; completed account-deletion receipts are anonymized and eligible for cleanup after 30 days. Expired reviews cannot be opened or resolved. | Bounded cleanup, linked-evidence retention and expired-review tests. |
| Local privacy/security | Owned tables enforce forced RLS; no general Auth write access is granted to runtime. The private self-deletion function checks owner context and the durable auth-stage checkpoint. Default API access URLs and Next.js development request URLs are not logged; unexpected errors log type/request or job ID without private SQL parameters/source content. | SQL privilege/RLS checks, self-deletion gate and logging redaction test. |
| Browser experience | Activity and privacy screens follow the existing UI, support mobile width, labeled controls, keyboard-accessible dialogs, empty/loading/error/retry states, and persisted light/dark appearance. Privacy controls are available before onboarding is complete. Source cards link pending privacy operations to Settings. | Desktop and 390px Chromium workflows; screenshot inspected; TypeScript and ESLint. |

## Automated results

- **65 API tests passed** against real disposable PostgreSQL 18 and the restricted runtime role. Google, Supabase token exchange and AI adapters are synthetic in these tests.
- **5 frontend unit tests passed.**
- **7 Chromium browser workflows passed** through the actual Next.js gateway, FastAPI and PostgreSQL: manual workspace, gateway security, connected sources, interpretation/review/rules, mobile activity/themes/privacy, account deletion, and imported-data deletion/restore.
- TypeScript, ESLint, Ruff checks/formatting and the optimized Next.js build passed.
- `npm audit --omit=dev`: zero reported vulnerabilities at verification time.
- Disposable migration recovery `0004 → 0003 → 0004` passed. All **23** application tables have enabled and forced RLS.
- The upstream FastAPI TestClient adapter reports an HTTPX deprecation warning; it does not fail the tests.

## Existing development database and running app

Migration **0004** is applied to Supabase project **obubxunyrripyyedhwbt**. Read-only verification confirmed the revision, new table access, forced RLS, restricted `duecare_app` role, and denial of self-deletion-function execution to `anon` and `authenticated`. The function owner has the required managed Auth table deletion privileges. No real student account or imported data was deleted during verification.

The existing app answered HTTP 200 at:

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/ready` (includes the new migrated tables)
- `http://localhost:3000/sign-in`
- `http://localhost:3000/privacy/deletion`

This proves process, page and migrated-database availability. It does not prove a fresh real Google login or live provider acceptance.

## Evidence still required for public release

The current local environment has Groq configuration and both `lms_assignment_receipt` and `classroom_turned_in` enabled. Configuration was inspected without exposing keys and was left unchanged. **This implementation pass did not certify either live automatic-completion path.** The fixture tests establish completion precedence and validation logic, not the correctness of real provider evidence.

Before a public release, evaluate real model output on approved redacted samples; verify current real Gmail authentication/recipient/activity association and real Classroom own-submission/withdrawal behavior; complete Google production OAuth approval and applicable user-data/security requirements; then verify the chosen production origins, callback URLs, cookies, database pooling and request budgets on the actual deployment. Unsupported test-submission and withdrawal email templates remain review cases.

Mobile verification here used desktop Chromium with a 390px viewport. Safari, Firefox and physical-device acceptance were not performed. No Vercel deployment was created. Native mobile apps remain future scope. See [local operations and recovery](OperationsLocal.md).

No commit or push was performed.
