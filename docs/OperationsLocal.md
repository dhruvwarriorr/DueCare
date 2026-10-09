# Local operation and recovery

DueCare currently runs at `http://localhost:3000`, with its API at `http://127.0.0.1:8000`. The database is the configured Supabase development project. Local-only refers to the web deployment; Google, Supabase and the configured AI provider remain external services.

## Start and check

Keep server-only settings in `apps/api/.env` and `apps/web/.env.local`. The web gateway's `GATEWAY_SECRET` must match the API. Both `WEB_ORIGIN` values must be exactly `http://localhost:3000`. Use the restricted runtime login for `DATABASE_URL`; use the privileged migration connection only for `MIGRATION_DATABASE_URL`. Hosted connections require TLS. Do not expose `duecare` or `duecare_internal` through the Supabase Data API.

From the API directory, apply migrations before starting changed code:

```sh
cd apps/api
uv run alembic current
uv run alembic upgrade head
uv run uvicorn duecare.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log
```

In another terminal, from the repository root:

```sh
npm run dev
```

Check `/health` for the process and `/ready` for runtime access to the migrated tables. A healthy process with an unsuccessful readiness request is not a working database-backed app. OAuth settings remain configured in Google Cloud and Supabase; the source callback is `http://localhost:3000/connections/callback`, while Supabase login uses its own provider callback followed by DueCare's `/auth/callback`.

The default API and Next development request log settings avoid raw request URLs, which can contain OAuth codes or sender addresses. App errors return a request ID and safe code. Do not enable full SQL parameter logging, HTTP-body logging, token logging or request URL logging in a proxy. Share the request ID, safe error code and failing operation when diagnosing a problem.

## Source privacy controls

| Student action | Result | Resume/recovery |
| --- | --- | --- |
| Disconnect in Sources | Sync cancellation and disconnected state commit immediately; tasks/evidence remain. Revoke Google access if no other connection uses the grant. | If Google is unavailable, open Settings and Resume the pending disconnect. Reconnection waits for this operation to finish. |
| Delete imported data in Settings | Remove the connection's imported records, reviews, evidence and source history. Preserve manual work, student edits and other-source support. Keep authorization separate from data deletion. | Saved progress survives page reload or request interruption. Open Settings and Resume. Source sync is blocked until completion. |
| Restore import | Mark a minimal suppression identifier eligible again. | Then explicitly choose Reimport on the matching active source. Deleted content is fetched again from Google within the normal history window; no backup restore occurs. |
| Reimport | Cancel the previous job, reset the source watermark, reconsider stored records and create an import job. | Open Sources to drive/follow the saved job. Suppression and sender blocks still apply. A disconnected source must first be reconnected. |

Source deletion processes one task and up to 25 of its evidence links per request, then up to 10 source records per request. These are internal work chunks, not product limits. Each chunk and checkpoint commit together. Counters count finalized tasks, even if evidence removal takes several requests. Source evidence removed by privacy deletion also invalidates merge-undo snapshots that contained it.

Deleted activities retain only owner-scoped hashed account/service and identity values plus timestamps/restore state. The UI displays a deletion identifier and time rather than retaining deleted titles or mail excerpts. Suppression follows the same Google account across reconnects. Restore cannot race with a pending deletion. Previously cached write results containing erased data return `410 RESULT_ERASED`; refresh and use a new explicit operation rather than replaying that erased response.

## Account deletion

Choose Delete account in Settings and type `DELETE`. The gateway saves the recovery capability in an HTTP-only cookie and navigates to `/privacy/deletion`. The browser continues saved stages while visible:

1. Freeze ordinary workspace API requests and cancel all sync jobs.
2. Revoke one source grant at a time. A temporary Google failure saves `waiting_retry` and allows Resume.
3. Purge up to 100 owned rows from one table per request, in dependency order; remove pending source OAuth states.
4. Remove native Supabase Auth sessions, identities and the user, then remove DueCare sessions. This final stage and completion receipt commit atomically.

The private SQL function performs only checkpoint-authorized self-deletion. Runtime cannot issue general Auth writes; browser roles cannot execute the function. This design complements the API's native-session checks: deleting an Auth user alone does not invalidate an already issued stateless JWT immediately, as explained in [Supabase's user-management documentation](https://supabase.com/docs/guides/auth/managing-user-data).

The capability remains in this browser so refresh/retry works after the login is removed. Only its hash is stored in the private checkpoint table, and the browser-facing JSON omits the raw token. Another authenticated browser can recover the pending capability while the native account exists. If the original capability is lost after completed Auth removal, the old workspace cannot be reopened; deletion has already completed.

Completed receipts contain no user ID, email or source content; they retain the job ID, capability hash, completion time and status for 30-day retry recovery. Later application activity cleans up expired receipts. Unfinished checkpoints remain until completion. Do not rotate the session encryption key while a deletion is pending; it protects sessions and derives recoverable deletion capabilities. Keep required old source-token key versions until stored credentials have been re-encrypted or removed.

Account deletion affects DueCare and its authorization grants. It does not delete Gmail messages, Classroom coursework or submissions from Google.

## Retention and interrupted processing

Accepted evidence/history remains until its task/source/account is deleted. Irrelevant or blocked source metadata expires after 30 days, is hidden immediately, and is physically purged in bounded batches during later app activity. Linked evidence is retained. Expired review items cannot be opened or resolved. Sender blocking minimizes unlinked records and clears their review/event content while preserving existing accepted tasks.

Sync resumes from its saved job on app open or refocus. A request already contacting Google may finish; its applying transaction rechecks ownership, cancellation and privacy state. One owner's application writes serialize with a transaction-scoped privacy lock. Temporary provider failures save backoff; `needs_reauth` requires renewed consent. No background scheduled sync or cron deletion worker is required for this local release.

## Migration and operational recovery

Revision `0004` adds three owned tables, one private account-deletion checkpoint table, indexes and a restricted self-deletion function. The existing development project is upgraded. Readiness fails if required tables are absent.

Test rollback only on the **disposable** database configured in `.local/test-config.json`. The tested `0004 → 0003 → 0004` round-trip drops and recreates privacy/activity data; it is not a recovery procedure for real user data. Real recovery needs a database backup and a reviewed forward repair. Never downgrade the hosted project to fix an application error. Preserve active deletion checkpoints and encryption-key versions during upgrades.

To reproduce validation, follow the disposable PostgreSQL provisioner and test commands in [README](../README.md). Tests use synthetic identities and providers, with AI keys pinned empty. Browser tests use ports 8001/3001 and a separate `.next-e2e` output directory. Passing these tests is separate from live Google/AI acceptance.

## Future public release

The student deferred public deployment. Before it is enabled, choose actual frontend/API projects and HTTPS domains; configure exact callbacks/origins and secure cookies; validate pooling, runtime/migration privileges, proxy logging and duration budgets; evaluate AI output and completion evidence live; and satisfy the production OAuth/data-handling requirements for the scopes actually used.

Provider quotas can change and are separate from DueCare's pagination/work budgets. Use the project's actual Google quota dashboards and the [Gmail quota documentation](https://developers.google.com/workspace/gmail/api/reference/quota) and [Classroom quota documentation](https://developers.google.com/workspace/classroom/limits). Surface observed throttling and outages through source state and Activity. Do not describe hosting/provider capacity as unlimited or impose new product caps through operational documentation.
