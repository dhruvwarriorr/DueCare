# Phase 3 implementation and verification

Verified locally on 7 October 2026. Phase 3 code passes local automated checks using a fake Google provider, a fake AI provider, and PostgreSQL 18.

**Live acceptance has not been performed.** No Groq (or OpenAI/Gemini) key or model ID is configured, and no real model output has been evaluated. Hosted migration `0003` has not been applied. No automatic completion path is enabled. No deployment, commit, or push was performed.

## Implemented scope

| Requirement | Implementation | Local evidence |
| --- | --- | --- |
| Interpretation in the sync job | After each import, the same leased job enters an `interpret` stage. Records are processed oldest first; coursework and announcements come before submissions, and receipts after notices. Content is re-fetched for the step and not stored | All Gmail/Classroom tests run import and interpretation through `/sync-jobs/{id}/advance` |
| Sender block before AI | Block rechecked under the per-sender advisory lock in the applying transaction. A newly blocked sender minimizes its records and suppresses its open review items | A paused item from a newly blocked sender is never sent to AI; suppressed reviews cannot be resolved |
| LMS templates | `duecare/lms.py` covers submission confirmation, due soon, overdue, quiz opens/closes, digest rows, and `[LMS-Reminder]` tables. It uses labelled absolute IST dates and namespaced activity links (`lms:{host}:{module}:{id}`), never countdowns | All 11 distinct reference exports parse with correct titles, roles, and UTC times (e.g. EXP5 10:06, EXP6 23:59, E20 20:00–21:00) |
| AI extraction | `duecare/ai.py`: Groq chat completions (OpenAI-compatible, JSON mode) as primary by the student's choice, superseding the specification's OpenAI-primary provider; one repair attempt, then the Groq fallback model, then OpenAI/Gemini if configured. The prompt treats source text as untrusted evidence and allows only two task types with separate timing roles. Outputs are schema-validated. Subject/task IDs outside the candidate set are discarded; timetable-derived times need a valid owned slot of the same subject | Fake AI tests: invalid subject and foreign task IDs become a subject question; mail with no academic signal is never sent to AI; outage pauses only AI items |
| Academic targeting | `duecare/targeting.py` normalizes SY/second year, III/3, B + 2 = B2, `A-B-C-D` sets, and LMS course labels. Activity qualifiers override course audience; room codes are not batches; conditional eligibility is asked | Unit checks plus B2 lab OST accepted, B1 notice ignored with no task or review, B1-only activity in a broad course ignored |
| Subject resolution | Only owned subjects. An ambiguous theory/lab course name is asked; confirming can remember the LMS course label | EXP6 asks between DS theory and lab; the remembered label resolves later mail |
| Timing roles and unresolved schedules | Proposals go through the manual-task validation contract. Windows, alternatives, date-only tests, and AI questions go to Needs attention; accepting window-only keeps `dueAt` empty. A quiz close never overwrites an established fixed session | ESE 30 Nov–4 Dec accepted as unresolved; explicit 09:00–11:00 OST kept; COA login/reporting/start/end/location kept distinct |
| Reconciliation | Exact identity links notices, revisions, and receipts to one task. Older notices cannot roll back newer values. Manual overrides win (conflict asked). Similar titles/labels are asked, never merged. Quoted schedules are history. Reprocessing an applied revision adds no duplicate evidence | EXP6 reminder + overdue + two receipts produce one task with two distinct submission events; reference exports produce no duplicate tasks |
| Completion precedence | Under the task row lock: notices never clear completion; a newer student reopen survives older receipts; Classroom `TURNED_IN` completes (late too) and a newer `RECLAIMED_BY_STUDENT` reopens; `RETURNED` without turn-in is asked | Synthetic newer EXP6 reminder after completion stays completed; reopen survives reprocessing; IA2.14-style turn-in completes then reopens on newer unsubmission |
| Receipt validation and enablement | Template, configured sender, Gmail-observed DKIM+DMARC pass for the sender domain, addressed to the account, not forwarded, exact activity link to an existing task. Automatic completion only for `AUTO_COMPLETION_PATHS`; otherwise one Needs attention item per activity | Forwarded and spoofed receipts never complete; a disabled path asks once for two receipts; an unmatched receipt is skipped and matched after explicit reprocessing |
| Rules | Allowlisted conditions (source, sender, subject, kind, type, keyword, label), ordered; first relevance and first priority rule win; new tasks only. Natural-language preview is validated and not saved | Code-like fields and foreign subjects rejected; reorder conflict detected; workshop excluded; COA priority rule applied |
| Needs attention | `GET /review-items`, `POST /review-items/{id}/resolve` with accept/link/apply_update/keep_current/complete/reopen/delete_task/keep_task/dismiss. Rechecks sender block, current profile mismatch, and revision | Cross-user resolve 404; browser workflow resolves a subject question and confirms completion |
| Evidence, history, merge/undo, reassignment | `/tasks/{id}/evidence`; history actor (student vs source) with event reference. Merge hides the duplicate and moves evidence; undo restores. Different subjects or types cannot merge; reassigning a receipt moves completion | Merge/undo/reassign test; browser shows completion origin and evidence types |
| UI | Needs attention view with nav badge, Rules view, task-detail evidence/merge/move, dashboard banner, source filters, interpretation counts per connection. Also fixed: Classroom scope alias (`classroom.student-submissions.me.readonly`), card/form alignment, and the dev badge overlapping Sign out | Playwright at desktop and 390 px without horizontal overflow; screenshots inspected |

## Checks performed

- **49 Pytest cases passed**: 18 Phase 1, 19 Phase 2, 12 Phase 3.
- **5 Vitest checks passed.**
- **4 Playwright workflows passed** through the real gateway and FastAPI/PostgreSQL. The new workflow covers the subject question, reprocessing, completion confirmation, task evidence, and rules.
- **Migration round-trip passed**: `upgrade head → downgrade 0002 → upgrade head → downgrade base → upgrade head`. 20 application tables, all with enabled and forced RLS.
- **Production build, TypeScript, ESLint, and Ruff passed.** `npm audit --omit=dev` reports zero vulnerabilities.
- Browser tests now use a separate Next.js build directory (`.next-e2e`) so they can run beside a developer's dev server. The generated test config pins AI keys empty so tests never call real providers.

## Not established (evidence gaps)

1. **Live AI quality.** Faculty-mail cases (E02, E03, E05–E07, E10–E12, S12–S23) are exercised only through faked model output that encodes the expected interpretation. Configure model IDs and evaluate them against redacted fixtures before release.
2. **Live receipt path.** Enable `lms_assignment_receipt` only after confirming live Gmail authentication results, recipient ownership, and activity association for real receipts.
3. **Live Classroom states.** Enable `classroom_turned_in` only after checking real own-submission state history and `dueDate`/`dueTime` handling.
4. **Missing examples.** Test-submission confirmations and withdrawal/resubmission emails still have no supplied examples; such mail goes to review rather than automatic completion.
5. **Phase 4 work.** The activity inbox, imported-data deletion/suppression/restore, physical purge of expired metadata, and deployment remain Phase 4.

## Sign-in access change

At the student's request, Gmail and Classroom read-only access is now requested during Google sign-in instead of separate Connect buttons. Supabase's provider tokens are verified with Google's tokeninfo endpoint (audience and account), then stored encrypted. Locally tested with fake tokens (`test_sign_in_grants_gmail_and_classroom_without_separate_connect`). Not yet tested live:

- Whether the hosted Supabase project forwards `access_type`/`prompt` to Google.
- Whether it returns `provider_refresh_token`.

## Operational note

Apply migration `0003` before running this code against the hosted database. Until then, endpoints that read the new tables (overview, interpretation, Needs attention) fail.
