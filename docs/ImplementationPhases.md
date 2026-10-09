# DueCare implementation phases

This plan groups the implementation into **four phases**. It organizes the approved requirements in [ProjectDocumentation.md](ProjectDocumentation.md); it does not introduce new product decisions. Phase 1 implementation and local verification are recorded in [Phase1Validation.md](Phase1Validation.md); hosted acceptance is still pending Supabase configuration. Phase 2 implementation and local verification are recorded in [Phase2Validation.md](Phase2Validation.md); live Google authorization and import acceptance are still pending Google Cloud configuration. Phase 3 implementation and local verification are recorded in [Phase3Validation.md](Phase3Validation.md); live AI provider, receipt-path, and Classroom state validation remain pending. The detailed specification remains authoritative for behavior, database fields, APIs, and evidence cases.

Complete each phase's acceptance checks before building dependent functionality. Local automated checks and live integration checks are separate evidence. No calendar estimates are assigned.

## Phase 1 — Foundation and the manual web app

**Outcome:** An eligible student can sign in, set up their academic context, and manage tasks without connecting a source.

### Implementation

- Scaffold the approved Next.js/TypeScript frontend and FastAPI backend, using the documented UI, validation, database, and testing libraries.
- Establish the browser → Next.js gateway → FastAPI → PostgreSQL request path, environment configuration, migrations, API schemas, and structured errors.
- Configure Supabase Google sign-in. Require verified Somaiya identity, enforce ownership, validate sessions, and implement server-managed cookies, session refresh, CSRF protection, and database isolation.
- Build onboarding with all six required academic fields. Preserve roll-number formatting. Google supplies identity; students enter their academic context.
- Build manual subject management with separate theory, lab, and tutorial subjects. Store one batch in the profile, applicable across every subject.
- Add optional manual weekly timetable slots with day, local start/end times, room/instructor, and revision checks. Do not show Valid from/Valid until inputs; preserve any existing stored bounds when saving.
- Implement manual task creation, editing, completion, reopening, and deletion, including priority and documented timing roles.
- Support exactly four task statuses: `due`, `completed`, `overdue`, and `missed`. Incomplete assignments become overdue; incomplete tests become missed at their applicable boundary. Online attempt windows expire at closing. Undated work remains due until completed.
- Build the responsive application shell, dashboard, searchable task list, calendar, task detail, profile, subject, and timetable screens. Include keyboard support and appropriate loading, empty, and error states.
- Establish task history and completion provenance so later imports cannot erase student decisions.

### Completion checks

- Eligible sign-in succeeds; personal-account login and cross-user access fail.
- Required onboarding fields, subject types, the single profile batch, and optional timetable work end to end.
- A student can manage manual tasks through the web UI, with persistent edits and correct status/timing behavior.
- Completion survives deadline passage. Reopening recalculates status according to task type and timing.
- Database migrations, ownership/session checks, and meaningful frontend/API tests pass.

## Phase 2 — Gmail and Classroom connections and reliable imports

**Outcome:** Students can authorize sources, map them to their manually added subjects, and resume imports without losing or duplicating work.

### Implementation

- Configure the Google OAuth application, enabled APIs, service permissions, consent configuration, and allowed callbacks.
- Separate Somaiya login from source authorization. Support additional personal Google source accounts after eligible login, without turning them into login identities.
- Implement connection, account identity verification, encrypted refresh-token storage, token refresh, and service-specific disconnection.
- Retrieve Gmail messages and Classroom courses, coursework, announcements, and the connected student's submission data using the documented read-only permissions.
- Implement explicit source-to-subject mappings. Source discovery must not automatically add subjects or introduce a separate onboarding course-selection step.
- Decode email MIME safely, distinguish authored content from quoted history, and preserve source identifiers and published/updated timestamps separately.
- Build source records, attachment references, account-scoped deduplication, durable checkpoints, retries, leases, and processing revisions.
- Implement active-browser syncing: login/open, eligible refocus, and **Sync now**. Use bounded requests, persist partial success, stop starting requests when hidden/closed, and resume on return. Allow one in-flight sync per connection.
- Build connection settings and sync progress/error UI. Keep unprocessed source content out of the accepted task list.
- Add sender inclusion and complete blocking early in the import path, including checks preventing queued or in-flight blocked results from applying.

### Completion checks

- Live Gmail and Classroom authorization, token refresh, source retrieval, and disconnect flows work.
- A personal source account can connect only through an authenticated eligible DueCare session.
- Subjects remain student-created and explicitly mapped; theory/lab/tutorial identities stay distinct.
- Pagination, incremental updates, duplicate prevention, partial results, interrupted imports, and concurrent-tab recovery work.
- Blocked senders produce no AI processing, tasks, reviews, updates, receipt handling, or activity; existing accepted tasks remain intact.
- Source tokens stay server-side and encrypted at rest.

## Phase 3 — Academic interpretation, review, and completion reconciliation

**Outcome:** Imported work becomes accurate tasks, with student review for unresolved information and reliable protection of completed work.

### Implementation

- Apply academic targeting before accepting tasks: fixed KJSSE/BTech and branch code/full name where relevant, class/year, semester, division, batch, subject, and subject kind.
- Ignore confirmed wrong-cohort work. Send ambiguous or insufficient applicability to student review. Evaluate mixed-cohort message sections separately and support otherwise applicable all-batch notices.
- Recognize `lms-kjsse@somaiya.edu` and relevant faculty/student-added senders without treating sender inclusion as proof of academic applicability or submission validity.
- Implement structured OpenAI extraction, validation/repair, Gemini fallback, and recoverable failures. Treat message and attachment contents as evidence, never executable instructions.
- Detect included assignments and tests from Gmail and actionable Classroom announcements. Distinguish reference materials, sample questions, separate deliverables, numbered assessments, and group-work instructions.
- Preserve reporting/login/start/end and upload opening/closing times separately. Interpret relative lab/class references only from valid manual timetable context. Review conflicting, tentative, or insufficient times instead of inventing dates.
- Reconcile exact duplicates, explicit source revisions, older quoted information, and linked stream/coursework representations. Route uncertain similarity and unexplained conflicts to review.
- Implement ordered relevance/priority rules, with confirmed structured previews for natural-language rules. Hard sender blocks and academic applicability checks remain authoritative.
- Build **Needs attention**, source evidence, task change history, student corrections, merge/undo, and explicit reprocessing.
- Validate email submission templates, authenticated sender evidence, student ownership, and exact activity/task association before enabling automatic completion for each supported path.
- Validate live Classroom own-submission behavior, including genuinely newer withdrawal/resubmission evidence. One group member's upload cannot automatically prove another student's completion.
- Enforce completion precedence atomically: manual or validated submission completion survives due/overdue reminders, digests, countdowns, late-submit warnings, and deadline passage, regardless of reminder age.
- Reopen only for the documented explicit student action or validated newer withdrawal/resubmission requirement. Separate receipts for one activity remain distinct evidence events without creating duplicate tasks.

### Completion checks

- Redacted fixtures cover all catalogued reference cases and the acceptance scenarios in specification sections 5 and 6.
- Wrong division/batch work is ignored; incomplete context is reviewed; room codes are not mistaken for batch codes.
- Different theory/lab/tutorial work and independent deliverables do not merge merely because titles or course codes resemble each other.
- Online quizzes remain due through the attempt window and become missed at closing when incomplete.
- Completed tasks remain completed under reminder replay and concurrent reminder/completion writes.
- Spoofed, forwarded, unsupported, unmatched, and other-student evidence cannot auto-complete tasks.
- Automatic completion is enabled only for paths that pass both fixture validation and the corresponding live checks. Missing test-receipt or withdrawal examples remain explicit validation gaps.
- AI outages preserve successful results and allow affected items to resume later.

## Phase 4 — Privacy, complete workflows, and web release

**Outcome:** The complete web product passes release checks and can be deployed with documented recovery procedures.

**Current execution scope, confirmed 7 October 2026:** localhost only. Complete the web workflows, privacy, automated checks and local recovery documentation now. Public Vercel deployment, production domains and Google production approval are deferred until the student requests public release. [Phase4Validation.md](Phase4Validation.md) records local completion separately from those future release gates.

### Implementation

- Complete the activity inbox with read/unread state and links for new tasks, revisions, reopening, reviews, and connection/sync issues.
- Finish disconnect, imported-data deletion, restore/reimport, and account deletion workflows. Preserve student-created work, student edits, and tasks supported by other sources according to the specification.
- Implement deleted-import suppression, retained evidence/history, 30-day expiry of irrelevant diagnostics, logical expiry, and later activity-driven physical cleanup.
- Finish responsive screens, accessibility, themes, filters, and all empty/loading/error/retry states across connected and manual workflows.
- Configure separate frontend/backend Vercel projects, database pooling and migration access, callback URLs, origins, cookies, request duration/work budgets, model IDs, and versioned token-encryption keys.
- Verify deployment behavior with real callbacks, sessions, source requests, database access, and bounded sync requests. Document provider quotas and actual operational failures without adding product caps.
- Complete required Google production verification and applicable user-data/security requirements for the selected source permissions and data handling.
- Run automated integration/end-to-end checks and live acceptance separately. Document results, unresolved blockers, sanitized diagnostics, migration/rollback procedures, and recovery from interrupted processing/deletion.

### Completion checks

- All specification acceptance scenarios pass, including mobile-browser use, session revocation, ownership isolation, reconciliation, privacy, and recovery.
- Disconnect/deletion/restore operations are resumable and idempotent; future sync does not silently recreate deleted tasks.
- The deployed frontend and backend work together with live Google authorization and verified own-submission behavior.
- Production provider approvals and required security checks are complete before public release; a local passing suite alone does not establish release readiness.
- No credentials or private source content appear in application logs or test fixtures unnecessarily.
- Release configuration and operational documentation are complete, with remaining limitations clearly stated.

## Execution and scope

- Work in order: **Phase 1 → Phase 2 → Phase 3 → Phase 4**. Add the migrations and tests needed by each phase as it is implemented; privacy and ownership controls apply from the first phase.
- The existing specification's seven milestones are consolidated here: milestones 1–2 map to Phase 1, milestone 3 to Phase 2, milestones 4–5 to Phase 3, and milestones 6–7 to Phase 4.
- Keep unresolved product or evidence decisions explicit. Ask the student before introducing features or changing approved behavior.
- The native mobile application stays in future scope after the web release; it is not a fifth implementation phase in this plan.
- Do not automatically commit or push repository changes.
