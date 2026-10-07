# Phase 2 implementation and verification

Verified locally on 7 October 2026. Phase 2 application code is implemented and passes local automated checks against a fake Google provider and PostgreSQL 18. **Live Google acceptance has not been performed**: no Google Cloud OAuth client, Gmail API, or Classroom API has been configured or called by this implementation, and hosted migration `0002` has not been applied. No deployment, commit, or push was performed.

## Implemented scope

| Requirement | Implementation | Local evidence |
| --- | --- | --- |
| Separate source authorization | `POST /connections/authorize` and `/connections/callback` → `GET /connections/oauth/callback`; one-use 10-minute state bound to the signed-in student; PKCE S256; offline access; incremental scopes; per-service scope requests; redirect URI `WEB_ORIGIN/connections/callback` | Unauthenticated authorize rejected; another student's session cannot use the state; replayed state rejected; generic gateway path to the callback returns 404 |
| Additional personal source accounts | Verified Google ID token (official `google-auth`) identifies a `google_accounts` row; never touches Supabase identities | Personal `gmail.com` source connects; `auth.identities` unchanged |
| Encrypted token storage and refresh | `oauth_grants` with versioned Fernet keys (`SOURCE_TOKEN_KEYS`); access token cached encrypted; refresh under a row lock; re-encryption to current key; refresh token preserved when Google omits it | Tokens absent from responses and plaintext DB columns; v1→v2 rotation on refresh; revoked refresh marks every connection on the account `needs_reauth` |
| Service-specific disconnect | Cancels the active job; clears checkpoint; revokes the Google grant only when no other service on that account remains connected; preserves records and tasks; idempotent | Disconnecting Gmail keeps Classroom's shared grant; disconnecting the last service revokes; replay returns the same result |
| Missing permissions | Callback rejects partial scope grants; an otherwise unused grant is revoked | `PERMISSION_NOT_GRANTED`, grant revoked, no connection |
| Gmail retrieval | Official `google-api-python-client` (static discovery); 90-day `after:` list, then `history.list` from the stored history ID; expired history relists the gap; drafts and sent-only mail skipped | Multi-page initial import; incremental import fetches only new mail; history expiry produces no duplicates |
| Classroom retrieval | Course discovery (metadata only); for linked courses: own submissions (`courseWorkId=-`, `userId=me`), coursework, announcements; initial rules: 90 days, older work with future deadlines, older outstanding work; incremental by `updateTime` watermark | Old completed work excluded; old outstanding/future work included; old announcements excluded; unlinked course never read |
| Explicit subject mappings | `PUT/DELETE /subjects/{id}/classroom-mappings/{connectionId}/{courseId}`; one course can map to several subjects; subject kind recorded as context; no batch field | Discovery creates no subjects; theory and lab both linked to one course; unlink stops future coursework reads; disappearance marks mappings unavailable |
| Safe MIME decoding | `duecare/mail.py`: stdlib `email` with the default policy; encoded words/folding/charsets/transfer encodings; plain preferred unless HTML tables would be flattened; scripts/styles skipped; no remote loading; header mailbox separate from display name; authored/quoted/forwarded/signature/footer sections; attachment and link metadata only | Synthetic fixture covers encoded subject, HTML table rows (`B2 \| B115A`), script removal, blockquote history, signature/footer split, attachment metadata; all 22 reference exports decode |
| Source records and identity | `source_records`/`source_attachments`; account-namespaced provider IDs (`gmail:{sub}:{id}`, `classroom:{sub}:{course}:{resource}:{id}`); sent/received/published/updated times separate; content hash; revision increments on changed content; no full bodies or descriptions stored | Reference exports: 22 files → 11 distinct messages; each `copy` export marked a duplicate occurrence; the two EXP6 receipts remain distinct; edited coursework becomes revision 2 |
| Checkpoints, leases, retries | `sync_jobs` with one active job per connection (partial unique index); lease per advance request; Google calls outside transactions; each unit commits results plus checkpoint only if lease and job revision are unchanged; backoff 15 s doubling to 30 min | Interrupted request resumes from committed checkpoint; held lease returns 409; expired lease is taken over; concurrent advances fetch each body once; temporary failure waits, then resumes without duplicates |
| Active-browser syncing | `SyncProvider`: starts on open, refocus (server enforces the 15-minute rule; unfinished jobs always resume), and **Sync now**; stops starting requests while hidden; 409 → observe the other tab's job; partial results refresh after each request | Vitest: no requests while hidden, resume with `focus` on return; Playwright: sync starts after connection and completes in the browser |
| Request duration | 90-second work budget per advance; gateway timeout 140 s for advance; route `maxDuration = 150` | Configured; deployment behavior is Phase 4 |
| Sender inclusion and complete blocking | `sender_preferences` (exact, normalized address); block checked from metadata before any body fetch and again under a per-sender advisory lock when committing; new block minimizes unprocessed records (no title/body/attachments, 30-day expiry); unblocking affects future mail; explicit Gmail reprocess reconsiders blocked/ignored mail | Blocked body never fetched; block added while a body fetch is in flight cannot commit content; existing tasks preserved; reprocess restores after unblock |
| Unprocessed content kept out of tasks | Imported records stay `awaiting_interpretation`; no task creation path from sources | No tasks after Gmail and Classroom imports (API and browser) |
| Connection UI | Sources screen: connect buttons, per-connection status/permissions/progress/errors, Sync now, reconnect, disconnect dialog, Gmail reprocess, Classroom course linking, sender preferences; dashboard Sources panel; Settings link; subject cards show linked courses | Playwright workflow at desktop and 390 px without horizontal overflow; screenshot inspected |

All new owner tables (`google_accounts`, `oauth_grants`, `connections`, `source_courses`, `subject_mappings`, `source_records`, `source_attachments`, `sender_preferences`, `sync_jobs`) have enabled and forced RLS and composite same-owner foreign keys. `duecare_internal.oauth_states` is runtime-only.

## Checks performed

- **37 Pytest cases passed** (18 Phase 1 + 19 Phase 2) against PostgreSQL 18 with the non-owner, non-bypass runtime role.
- **5 Vitest checks passed** (3 Phase 1 + 2 sync-driver visibility checks).
- **3 Playwright workflows passed** through the Next.js gateway and real FastAPI/PostgreSQL path, including the new sources workflow using a fake Google provider installed only by `tests/e2e_server.py`.
- **Migration round-trip passed** on a separate disposable database: `upgrade head → downgrade 0001 → upgrade head → downgrade base → upgrade head`; 15 application tables, all with enabled and forced RLS; the single-active-job index is present.
- **Production Next.js build, TypeScript, ESLint, Ruff lint/format passed.** `npm audit --omit=dev` reports zero vulnerabilities. This local build used Node 26, not the pinned Node 24; CI uses `.nvmrc`. No Python vulnerability audit tool is configured.
- `scripts/local-test-db.py` now creates the `anon`/`authenticated` roles the Auth SQL hardening revokes from; previously a fresh provisioning run failed. It also writes synthetic source settings so tests never read a real `.env`.
- The CI workflow is renamed to `.github/workflows/verify.yml` (“Local verification”). It has not run on GitHub.

## Pending live Phase 2 acceptance

These require the Somaiya-owned Google Cloud project and real accounts:

1. Create/configure the OAuth client (redirect `…/connections/callback`), enable Gmail and Classroom APIs, configure external consent and test users. Set `GOOGLE_OAUTH_CLIENT_*` and `SOURCE_TOKEN_KEYS` in the API environment. Apply migration `0002` to the hosted database.
2. Live Gmail and Classroom authorization, ID-token verification, refresh-token issuance/omission behavior, token refresh, and revocation on disconnect.
3. A personal source account connecting only through an eligible DueCare session, and Workspace policy acceptance for the Somaiya account as a source.
4. Live Gmail pagination, history-based incremental import, and history expiry; actual `raw` decoding of current college mail.
5. Live Classroom course listing, coursework/announcement ordering by `updateTime`, own-submission states and history, `dueDate`/`dueTime` UTC handling, and access loss.
6. Provider quotas and rate-limit responses under real imports.

## Phase boundary

Phase 2 does not interpret source content, apply academic targeting, call any AI provider, create or update tasks from sources, validate receipts, or create review/activity items. Those belong to Phase 3 and 4. Expired blocked/ignored metadata is hidden from counts; physical purge, imported-data deletion, and restore are Phase 4. Gmail reprocessing in Phase 2 reconsiders only blocked and ignored mail; Classroom reprocessing re-reads linked courses without watermarks.
