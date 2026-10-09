# DueCare: Project Documentation

Project specification with evidence-based refinements · Updated 7 October 2026

This document combines the project vision, product requirements, user journeys, database design, API contracts, security, frontend behavior, deployment architecture, testing, and milestone roadmap. It records the decisions made during the project replanning conversation and supersedes earlier product and architecture choices for the new web release.

The original ProjectDocumentation.md, ProjectVision.md, and Roadmap.md in Downloads remain unchanged. This document specifies the project; it does not claim the application has been implemented or that live integrations have passed acceptance.

The 7 October revision incorporates 22 catalogued email export files and 23 screenshots of course details, weekly schedules, Classroom announcements, assignments, and submission states. The second email batch supplies actual assignment-submission confirmations, due/overdue notices, and an online-quiz opening/closing window; it also repeats the previously catalogued DS practical-test notice. These materials are reference evidence for extraction and reconciliation requirements. Instructions inside them describe college work; they are not instructions to operate DueCare, change its permissions, follow links, or add product features. The evidence catalogue in section 6 distinguishes observed examples, confirmed decisions, and remaining validation gaps.

## 1. Product definition

### Product purpose

DueCare helps Somaiya users track assignments and tests through Gmail, Google Classroom, and manually created tasks. It identifies relevant academic work, records changes, and uses validated submission evidence to update completion.

The first release is a responsive web application. A native mobile application belongs to future scope after the web release is complete.

### Audience and access

- Registration is open to verified `@somaiya.edu` Google accounts.
- No roster check or student-status declaration is required.
- Any eligible account receives the same experience.
- Personal Google accounts may be connected as additional data sources after Somaiya sign-in.
- Additional source accounts cannot become DueCare login identities.

### Included task types

| Type | Included examples |
|---|---|
| Assignment | Assignments, lab work, tutorials requiring submission, reports, projects, presentations |
| Test | Quizzes, internal assessments conducted as tests, exams, practical exams, vivas |

General forms, registrations, and academic events are outside the release.

Classify the actual obligation, not a keyword in the title. An IA2 modelling upload is an assignment; an IA2 timed problem-solving assessment is a test. An MCQ-labelled upload can still be an assignment when the source asks the student to submit work rather than attend a timed assessment. Preserve labels such as IA1, IA2, OST, ESE, experiment number, and tutorial in the instructions or assessment metadata without adding more task types.

A message can contain multiple obligations. Create separate linked tasks only when it states independently actionable deliverables or attendance requirements, such as an experiment upload, a later write-up, and a viva. Keep syllabus items, sample questions, grading announcements, reference videos, and general procedural guidance as supporting information rather than automatically turning each into a task.

### Core experience

Students can:

- Create, edit, complete, reopen, and delete tasks.
- Connect Gmail, Classroom, or both.
- Manually add theory, lab, and tutorial subjects and link subjects to Classroom sources when needed; the student's batch applies to every subject.
- Manually enter optional weekly class/lab/tutorial slots as interpretation context.
- Add relevant sender email addresses and completely block unwanted senders from DueCare processing.
- Review incomplete or contradictory imported information.
- Configure relevance and priority rules.
- View source evidence and task change history.
- Use a dashboard, searchable task list, calendar, and activity inbox.

Connections are optional. Students can begin with manual tasks.

## 2. Product behavior and processing rules

### Sign-in and onboarding

1. Sign in with Google using a verified Somaiya account.
2. Display the Google-provided name, email, and photo as read-only identity information when available.
3. Require these six manually entered academic fields so academic targeting can be checked explicitly. Institution is always `KJSSE` and programme is always `BTech`; neither is editable. Admission year is not collected:

| Field | Input |
|---|---|
| Branch | Fixed dropdown of short codes; store both `branchCode` and its canonical full `branchName` |
| Class/year | Fixed dropdown: FY, SY, TY, LY |
| Current semester | Number |
| Division | Text |
| Batch | Text; entered once and applicable to every theory, lab, and tutorial subject |
| Roll number | Text, preserving letters and leading zeros |

The branch dropdown displays the following supplied abbreviations. Full names are canonical server-derived values, retained alongside the code for AI context, task academic context, and explicit recipient-cohort matching:

| Code | Full name |
|---|---|
| COMPS | Computer Engineering |
| IT | Information Technology |
| AIDS | Artificial Intelligence & Data Science |
| CSBS | Computer Science & Business Systems |
| VLSI | Electronics Engineering (VLSI Design & Technology) |
| CCE | Computer & Communication Engineering |
| EXTC | Electronics & Telecommunication Engineering |
| EXCP | Electronics & Computer Engineering |
| MECH | Mechanical Engineering |
| RAI | Robotics & Artificial Intelligence |
| CIVIL | Civil Engineering |

The API accepts only these branch codes. It derives the full name, fixes KJSSE/BTech, and rejects attempts to edit institution/programme, supply a full-name override, or collect admission year. Existing department values matching a supplied abbreviation or full name are normalized; unknown legacy values require the student to choose a branch. Canonical values replace the legacy department/admission-year keys on the next profile save. The existing JSON/API key `generalBatch` continues to store the single student batch; its visible label is **Batch**.

Explicit recipient branch targeting accepts either a code or its full name. Confirmed other-branch work is ignored, unresolved branch targeting requires review, and a minor's offering department or sender's department alone is not a recipient mismatch. The word “it” in ordinary prose must not be classified as the IT branch. Admission cohort mentions in reference notices remain evidence only; unknown admission-cohort or admission-route eligibility requires review.

4. Complete onboarding.
5. Offer optional source connections.
6. Let the student manually add subjects and identify each as theory, lab, or tutorial. Use the batch already entered in the profile for all subject-related processing. Offer optional manual weekly timetable entry for those subjects; it is not another onboarding requirement.

Google sign-in supplies identity information. It does not supply the student's academic profile or complete college history. DueCare history means the subjects, tasks, submissions, and changes tracked within the application.

### Manually added subjects and the student's batch

Subjects are always created by the student. Connecting Classroom or receiving an email must not automatically create a subject, enroll the student in one, or add subjects through a course-selection step.

- The add/edit subject form contains only Subject name and Subject kind (`theory`, `lab`, or `tutorial`). Course code, aliases, academic term, and class/section code are not form inputs. Existing matching metadata is preserved when editing a subject. Student academic context comes from the profile.
- The timetable form exposes day, start/end times in IST, room/location, and instructor. Valid from and Valid until controls are removed. Existing stored validity bounds are retained on save; new UI-created slots have no date bounds.
- Theory, lab, and tutorial subjects are separate records, even when they share a base name or subject code. A shared confirmed course code can identify related components without merging their work, mappings, or timetable slots.
- Store exactly one student batch in the profile. That batch applies to every subject, including every lab.
- Keep class/year, semester, division, and batch as distinct profile values. Subjects inherit this academic context; they do not define or override student batch membership.
- Do not request a batch when adding a subject or store per-subject batch membership. Batch targeting stated in an assignment is source information to compare with the single profile batch.
- Read the current profile batch during processing instead of copying membership into subject records. A profile batch edit changes the context for all subjects together; previously ignored items still require explicit reprocessing.
- Students may manually link an existing subject to Classroom course metadata. Source metadata helps mapping but does not create subjects.
- When an imported item cannot be matched to an existing manually added subject, place it in Needs attention and ask the student to add or choose a subject.
- Preserve optional academic-term labels and source class/section codes when the student confirms them. A subject code, a college class code, and a Classroom course ID are different identifiers; do not substitute one for another.
- Subject aliases can cover observed naming differences, such as WDL versus the Classroom label WPL, after student confirmation. Faculty name or sender alone is not enough to associate work: the same teacher can teach a theory subject and an unrelated lab.
- Explicitly enrolled minor and elective subjects can have broader or different course-offering departments. Compare the intended recipient cohort with the student's profile; do not reject an enrolled minor merely because the offering department differs from the student's major.

The user confirmed separate manually added tutorial subjects after reviewing the supplied course details. Their instructor, class/section code, room, time, and assignment context must not be collapsed into the theory subject's details. For example, Discrete Maths theory and Discrete Maths tutorial can share course code 16U2604 while using different class codes and instructors. Both inherit the same general student batch.

AI must receive this context before applicability assessment, extraction, matching, or receipt association: fixed institution/programme, branch code and full name, class/year, semester, division, the student's single batch; manually added subject IDs, names, aliases, kinds, confirmed class codes and term context; relevant manually entered weekly slots; and existing source mappings. It must distinguish theory, lab, and tutorial work and compare all assignment batch targeting against that same profile batch.

For example, Database Theory and Database Lab are separate subjects, but a student whose profile batch is B1 belongs to B1 for both. An assignment addressed exclusively to B2 must be ignored regardless of which subject it concerns.

### Task model

A manual task requires only a title and type. Subject and deadline are optional.

Optional task information includes:

- Original task instructions.
- Personal notes.
- Estimated effort in minutes.
- Priority override.
- Source links and attachment metadata.
- Assessment and deliverable labels, such as IA2, Experiment 4, query demonstration, or write-up.
- Reporting, attendance, and submission timing where the source distinguishes them.
- Venue, relevant syllabus, permitted tools, and preparation instructions stated by the source.

Tasks have exactly four statuses: `due`, `completed`, `overdue`, and `missed`. The user explicitly added `missed` after supplying online-quiz examples; this supersedes the earlier three-status decision. It is a stored/API status, not merely a display label.

- `due`: incomplete work whose applicable cutoff has not arrived, including work without a precise cutoff.
- `completed`: work completed manually or through validated submission evidence.
- `overdue`: an incomplete **assignment** whose submission cutoff has arrived.
- `missed`: an incomplete **test** whose applicable cutoff has arrived; an online attempt-window quiz uses its closing time.

Compute the effective incomplete status from task type, timing mode, the accepted cutoff, and current time whenever tasks are read or displayed. At `now >= dueAt`, an incomplete assignment is overdue and an incomplete test is missed. With no precise cutoff, it remains due. A completed task remains completed after the cutoff. Reopening or an accepted timing correction recalculates due/overdue/missed within those type-specific rules.

The database/API status enum supports all four values; overdue is valid only for assignments and missed only for tests. Persist the status snapshot during ordinary application processing and writes, while responses always compute the effective value rather than relying on a stale snapshot. No scheduled job is required merely for a status to change with time.

Completed tasks are excluded from due, overdue, and missed views/counts. Needs attention remains a separate review queue, not a fifth task status.

Tests without completion evidence become missed at their applicable cutoff and remain incomplete until the student completes or deletes them. A fixed-session test uses its confirmed start; an online quiz offering only an attempt window uses the window's closing time, as confirmed by the user. An opening time alone is not that quiz's missed cutoff.

Completion belongs to the specific obligation. Uploading an experiment does not automatically complete its viva or a separately requested final write-up. Taking a test, receiving a marks announcement, opening coursework, attaching a file, or passing the scheduled date does not by itself supply completion evidence.

### Dates and priority

Use `Asia/Kolkata` throughout the product.

- Store precise timestamps in UTC.
- Respect explicit source time zones when interpreting timestamps.
- For a genuinely date-only deadline, use 23:59 IST and clearly label that the source supplied only a date.
- Do not present the defaulted time as a confirmed exam start time.
- Show undated tasks in a dedicated view.

#### Timing roles and precision

| Information | Meaning and handling |
|---|---|
| `dueAt` | Assignment submission cutoff; fixed-session test start; or online attempt-window closing time, according to established timing mode |
| `submissionOpensAt` | Opening of an upload window; does not replace the closing deadline |
| `availabilityOpensAt` / `availabilityClosesAt` | Online quiz availability bounds; distinct from physical reporting/start/end or an individual attempt duration |
| `loginByAt` | Required login/check-in time, when separately stated |
| `reportingAt` | Required arrival/reporting time, distinct from test start |
| `startsAt` / `endsAt` | Actual attendance/test interval; preserve both when available |
| `dateWindowStart` / `dateWindowEnd` | A range within which an individual slot will later be assigned; date values, not an invented precise deadline |
| Tentative alternatives | Proposed dates or times that have not yet been selected; retain the alternatives in review |
| `durationMinutes` | Explicit duration; a calculated end time is marked derived and retains its calculation inputs |
| Source publication/update time | When a notice was sent, published, or edited; never a task deadline solely because it is the newest timestamp |

Additional rules:

- A test's reporting or login time must not be silently substituted for its start time. Display these roles together. Deadline-based status and priority continue to use `dueAt`; earlier arrival requirements are visible task instructions.
- For an online quiz that specifies only an attempt window, the user chose the closing time as the incomplete-status cutoff. Keep opening/closing fields separate, set `timingMode` to `attempt_window`, and use `availabilityClosesAt` for `dueAt`. Do not claim the student began an attempt when the window opened or that the attempt duration equals the full availability interval.
- A quiz closing notice can describe an online availability bound for a fixed-session classroom test. In that case, retain the independently confirmed classroom start/end and the availability close as different roles; a generic closing notice does not silently change the established timing mode.
- For an assignment with a date-only closing deadline, the existing 23:59 IST default is permitted and labelled. A date-only exam notice requires review of the missing start time; do not display 23:59 as the exam start. A student may confirm the test with its date retained and no precise status cutoff until the time is known.
- A window such as 30 November–4 December means the student's test falls somewhere in that interval. Do not choose the first day, turn the last day into a submission deadline, or claim that the test lasts the entire interval. Keep the proposed item in Needs attention; if accepted before the individual slot is known, retain the range and leave `dueAt` unset.
- “During any lecture in the week” does not select one lecture. “Tentatively 23rd/30th” does not select one date. Unresolved choices remain in review.
- Interpret relative text using the source author's publication time and stated timezone, not import time. Preserve the phrase and the resolved basis for phrases such as “today,” “next week,” and “before the next lab.” Quoted text uses its own earlier message date.
- Treat Indian numeric dates as day/month/year when the surrounding source and chronology establish that convention. If two readings remain plausible, ask through Needs attention rather than forcing a locale guess.
- An explicit exam time takes precedence over a weekly reference slot. If a notice says 09:00–11:00 but the reference lab is 11:00–13:00, retain the explicit exam time and expose the discrepancy in the evidence timeline. Do not rewrite the weekly timetable or the student's batch.
- Availability of a weekly schedule does not establish that every week has a class, or that a test follows ordinary class times. Holidays, changed sessions, tentative notices, and multiple matching slots still need explicit evidence or student review.
- Keep a precision/basis per timing field: source-exact, source-date-only, source-window, explicitly derived, timetable-derived, or student-entered. These are provenance labels, not trust scores.

#### Manually entered weekly timetable context

The user confirmed this feature for the first web release. Students can add/edit/remove weekly slots for their manually added theory, lab, and tutorial subjects. Slots are optional context, not recurring assignment/test tasks.

Each slot records:

- The existing owned subject ID.
- Day of week and local start/end time in Asia/Kolkata.
- Optional room/location and instructor label.
- Optional valid-from/valid-until dates so an old term's schedule is not used for a new term.
- The current subject/semester/term context at entry, without copying or overriding student batch membership. If date bounds are omitted, the slot is current-context information and cannot automatically carry forward after that semester/term changes.
- A stable slot ID and the subject/timetable revision used for interpretation.

One subject can have multiple weekly slots. The student enters batch only once in the profile; the timetable editor has no batch membership or override field. Saving a slot does not populate missing academic profile values, create a subject, import an attachment, or generate class-attendance tasks.

Use timetable context only when the candidate is already academically applicable and the correct manually added component is established:

1. Resolve the date or week from the actual notice and its publication time.
2. Find valid slots for that subject/component in the resolved period. Do not match the theory timetable for a lab/tutorial obligation.
3. If a notice explicitly says the assessment uses the regular session's timing and exactly one valid slot matches, a time derived from that slot may be accepted. Mark the field `timetable-derived`, retain the source phrase and slot/revision reference, and display its basis.
4. If the notice merely says “during the lab,” the slot establishes a session window, not necessarily an exact test start. Keep the precise start unresolved unless the notice or student confirms it. Multiple matching slots, unknown validity, tentative alternatives, and “before/by lab” start-versus-end ambiguity require review.
5. An explicit assessment time or venue in the notice takes precedence over ordinary weekly context. Keep discrepancies visible rather than changing the weekly slot automatically.

Timetable edits affect future interpretation. They cannot silently move accepted exam dates/times or override manual task corrections. Explicit reprocessing may produce a proposed revision for previously derived fields; preserve the old basis and review any conflict. A profile-batch edit changes applicability across all subjects but does not rewrite their entered hours.

The timetable is an interpretation reference within Subjects. It does not add scheduled syncing, reminders, automatic course history, or tasks for every class meeting.

#### Automatic subject linking

Imported assignments and tests are linked to the student's subjects without asking ("Which of your subjects is this for?" is no longer a review).

- Order: a confirmed LMS course label; then an exact code, alias or name, or matching short form/initials ("DS_B_ODD_26-27" → Data Structures, "COA", "dbms"). Theory versus lab is decided by the work's wording: experiments, practicals, journals and write-ups go to the lab; quizzes, IA and class tests to the theory. Only then one AI call per message picks among the student's subjects, and it may return only supplied subject IDs.
- Classroom items stay within the course's linked subjects. Work matching none of the student's subjects is created without a subject and shown as such. The task records how its subject was chosen (`subjectLink`: name, ai or none), task detail shows it, and editing the task changes it.
- A configured but failing AI pauses the item and retries later; with no AI configured, unmatched work is created without a subject.
- Classroom courses are linked automatically after discovery: by name or short form, or by a conservative AI match that leaves generic names such as "Maths III" unlinked. A course serving both the theory and the lab of one subject is linked to both. Links show as "auto" on the Sources page. A course the student unlinks is never linked again automatically, and courses are reconsidered when the subject list changes.
- Subject questions left from before this change are re-interpreted on the next sync, and the created task settles them.

#### KT notices

Settings offers **Show KT notices** (default) or **Ignore KT notices**. KT (ATKT/backlog) notices concern only students re-taking a failed subject: KT exam timetables, forms, fees and results.

- The extraction marks an item `ktOnly` only when it is just for KT students. The backend also marks items whose title, Gmail subject or Classroom title says so plainly (ATKT, "KT exam/form/result/students", "backlog exam"). It never marks items naming regular students too, or a bare "KT", which may be a teacher's initials.
- With Ignore selected, a KT-only Gmail or Classroom item that matches no existing task is ignored like a targeting mismatch: no task, review, completion change or activity, and the record keeps the minimized reason `kt_notice`. Tasks already tracked keep receiving updates.
- The choice applies to newly processed items. **Reprocess** on a source reconsiders earlier ones under the current setting.

#### Timetable upload

Students can fill weekly slots from their college timetable instead of typing them (Subjects → **Upload timetable**). This is an explicit student upload; it does not read Gmail or Classroom attachments.

- Input: exactly two supported kinds, both read without AI. Either the department's timetable PDF (up to four pages), or up to four screenshots of the Somaiya roster scheduler's Week view (PNG, JPEG or WebP). Files are limited to 10 MB each and 20 MB in total. Mixed uploads are rejected, and so are scanned PDFs without text, with guidance towards the two supported kinds.
- Generated PDFs are read from their own text and ruling lines, without AI. Each cell's weekday comes from the day header and its time span from the rows it covers, so merged multi-hour lab cells keep their full interval. Rows read top to bottom, so `12:00-1:00` is 12:00–13:00.
- Department timetables that exist only as a picture or a scanned PDF are read without AI too. Ruling lines are found in the pixels, and the table is cut into its smallest cells; cells are joined where the line between them is missing, which recovers merged labs and batch sub-columns. Each cell is read with Tesseract, then mapped through the same weekday/time logic as a generated PDF. The fixed structure repairs OCR gaps: unread day headers are filled from their neighbours, and hour labels are rebuilt by majority vote over the one-hour rows. Missing batch labels are restored from their column position, and look-alike characters in room codes are fixed (`82078` → `B207B`). Low-confidence cells are flagged for checking. A cropped picture without its time column is rejected.
- Scheduler screenshots are read from pixel geometry with local Tesseract OCR. Grey ruling lines give the seven day columns and 30-minute rows. Hour labels anchor the clock, and each class is a solid coloured block whose top and bottom give its times. OCR reads only small crops: day headers, hour labels, and each block's course code and name. The page scrolls, so screenshots may overlap and arrive in any order. Pieces of one class are joined by weekday, colour and overlapping time. Classes still cut off are flagged so the student checks their times, and time ranges no screenshot shows are reported. Scheduler entries are already the student's own classes, so batch filtering does not apply.
- Lab and tutorial sessions are printed as side-by-side batch columns in one time block (`B1 WDL…`, `B2 DBMS…`) or as numbered groups (`DA_1`, `DA_2`). The profile batch decides batch-labelled rows; other batches stay visible as not included. Numbered groups and one course printed in several rooms at once are explicit student choices, never guessed. A timetable whose header names another class year or division is excluded visibly unless the student includes it.
- Subject links: an exact name/code/alias match with a compatible component is preselected. A batch session is a lab or tutorial; a whole-class cell is theory. Same-course siblings (the lab of an exactly matched theory subject), matching initials, and AI suggestions are only suggestions the student accepts. AI receives course labels, component hints and the student's subject list, and may return only supplied subject IDs.
- Missing subjects: each course card offers **Create subject from this**, prefilled with the printed name, kind and course code; the student can edit them first. Creating links all of that course's slots. The printed label is saved as an alias when the name differs. A subject with the same normalized name and kind is never created twice: the form offers the existing one (or a suggested match), and the API rejects duplicates with `409 DUPLICATE_SUBJECT`, including renames.
- Electives (`E-`), honours (`H-`) and minors are grouped by course family, so `E-ACC`, `E-ACC_1…_5` and `H-CSFTUT`/`H_CSF` are one course each. A checklist offers each family; families matching the student's subjects start ticked, and unticked families are left out visibly. Class-wide placeholders such as `Minor -- --` or `EL -- --` stay included with a note to link the student's own minor or elective. A course taught in parallel by several teachers (e.g. SDT, E-ACC, E-Dev) becomes one choice of teacher for the week, because each teacher keeps the same group; per-time-block room choices remain when teachers are not printed.
- Review: the original page is shown beside an editable draft. Every included slot needs a subject and valid times before saving; unresolved rows can be fixed or explicitly excluded. Breaks are listed as non-classes.
- Saving: a dry run shows additions, already-saved duplicates, updates and removals (replace mode) and overlaps. One transaction then saves all selected subjects after rechecking the profile and subject revisions. Overlaps and removals need explicit acknowledgement. Retries reuse the idempotency key.
- Retention: uploaded files, extracted text and drafts are not stored; multipart temporary files are removed after the request. Confirmed slots record `origin` (`timetable_import`, reading method, time). Refreshing the page discards an unconfirmed draft.

Classroom's `dueDate` and `dueTime` represent UTC values. Convert the API values to IST before displaying them; a date-only UI screenshot is not proof that the API lacks a time. `creationTime`, `updateTime`, and `scheduledTime` identify publication/editing behavior, not test attendance. [Classroom coursework fields](https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork)

Effective priority follows this precedence:

1. Student override.
2. First matching priority rule.
3. Deadline-based default.

| Deadline condition | Default priority |
|---|---|
| Overdue assignment, missed test, or cutoff within 24 hours | Critical |
| Within 3 days | High |
| Within 7 days | Medium |
| Later or undated | Low |

### Gmail import

- Scan only Gmail from the last 30 days, newest first, including during incremental sync and reprocessing.
- Read recent mail before draining incremental history; keep the same cutoff when history expires.
- Interpret committed mail concurrently with import and add tasks/deadlines as results arrive. Previously accepted older tasks and evidence remain saved.
- When AI is unavailable or rate limited, keep imported Gmail/Classroom records and keep the sync job pending until automatic retry. Respect the provider retry delay; report the pending interpretation separately from successful downloading.
- Use pagination and resumable processing without imposing a total message cap.
- Use `lms-kjsse@somaiya.edu` as a primary user-provided assignment-notification sender.
- Also process relevant faculty and department mail about quizzes, tutorials, internal assessments, and other included assignment/test work; do not restrict detection to the primary sender.
- Prefilter college, faculty, department, and validated academic-system senders.
- Apply the student's complete sender blocklist before fetching message bodies or sending content to AI.
- Allow student-defined sender inclusion to improve academic-mail relevance, subject to the mandatory academic-targeting check below.
- Remember exact faculty addresses after automatic academic acceptance or student acceptance. Offer Approve faculty in Needs attention, Tasks, Overview, and task details, with approval management in Sources. Approved faculty can supply missing audience context; explicit class/semester/division/batch mismatches and nonacademic filters remain effective. Faculty approval never assigns a subject or proves submission.
- Exclude competition-cell mail, exhibitions, promotional training programs, and student registrations, including `projectcompetitioncell.engg@somaiya.edu`.
- Extract assignments, tests, relevant changes, and submission events.
- Process necessary message text temporarily; retain source metadata and minimal evidence excerpts.
- Store attachment names, links, and metadata only.

A student-added sender can affect relevance. It cannot bypass class/semester/division/batch checks or automatically become an approved sender for submission completion.

The primary sender is now represented by announcement, due/overdue, digest, quiz-availability, and assignment-submission-confirmation examples. The EXP6 and ITVC receipt formats can be specified from the supplied files; authenticated live ingestion and task/recipient association still require validation. No withdrawal or test-submission-confirmation email has been supplied.

#### Reminder mail is not completion-state authority

DueCare reads academic due/overdue emails as source notices; this does not add a DueCare reminder-delivery feature.

- A notice labelled due, overdue, closing soon, late, or “days to go” describes scheduling. It is not proof that the student has not submitted.
- Extract exact dates from labelled fields such as `When`, `DUE`, `OPENS`, and `CLOSES`. Negative or approximate countdown text is not a reliable timestamp or task status.
- If the notice establishes relevant new work, it may create an incomplete assignment/test after all subject and academic checks pass. Its due/overdue/missed status is computed from task type, accepted cutoff, and current time, not copied from the email label.
- If the matching task is already completed, the notice cannot change its status, create an overdue duplicate, or trigger reopened/new-due activity. This applies even when the notice is sent or imported after confirmation.
- Do not create a Needs attention item solely because a reminder disagrees with confirmed completion. Record a minimal eligible-source association/reason in history if useful. Genuine identity or deadline ambiguity can be reviewed without clearing completion.
- A message saying the student can still submit late is not a withdrawal, rejection, or explicit requirement to submit again.
- An email digest is parsed per listed activity. A generic digest title or one irrelevant row cannot decide the status or applicability of all rows.

Reminder dates also retain their role. A quiz's online closing time is not automatically its classroom start or end. The supplied COA and Discrete Maths closing notices must not overwrite the separately established attendance times.

#### Email decoding and thread interpretation

1. Decode RFC email headers and MIME text safely, including folded subjects, encoded words, character sets, and transfer encodings. Prefer a usable plain-text part; otherwise convert HTML text and tables into bounded structured text without loading remote resources or executing content.
2. Preserve the header sender mailbox separately from a quoted or displayed author, recipient-group context, message sent time, Gmail occurrence metadata, and referenced thread identity. A copied sender name is not authenticated sender evidence.
3. Separate the current authored section, quoted earlier messages, tables, signatures, subscription footers, and attachment references. Do not remove all quoted text: it can hold the unchanged test date or original task identity needed to interpret a later room update.
4. Build candidate obligations and field-level updates. Use current authored changes first, then retain non-conflicting earlier details for the same established obligation. The current sentence about login does not erase an earlier confirmed test start.
5. Preserve table relationships while interpreting academic targeting. Room identifiers such as B115A and B116A are venues, not student batch labels. Select the row applicable to the student's batch; never combine rooms from other rows.
6. Apply the mandatory applicability check per candidate and section before detailed extraction or association. A quoted Division A roster cannot supply dates for a Division B student.
7. Ignore signatures, disclaimer text, unsubscribe instructions, unrelated links, and reference-only material as task triggers. Retain only necessary academic instructions for accepted tasks.

Exported filenames are not source identity. Two supplied DS email exports have the same Message-ID and decoded selected body even though their filenames differ. Deduplicate using account-scoped provider identifiers and established message identity; changed quoted content or a similar subject is not enough to declare two distinct messages identical.

An EML file is reference evidence. Its headers can show apparent authentication results but cannot substitute for validation against the live Gmail response and trusted receiving infrastructure. Do not use an arbitrary forwarded or locally edited Authentication-Results header to authorize completion.

### Sender inclusion and complete mail blocking

Students can manage exact sender email addresses in the application:

- **Include sender:** consider mail from that address for academic task detection, even when it falls outside the normal sender prefilter. Inclusion improves relevance; it does not make every message academic or prove that the work belongs to the student.
- **Block sender:** ignore all mail from that address in DueCare processing, including task announcements, changes, submission receipts, and previously queued items. Do not send its content to AI or create tasks, review items, updates, or activity from it.
- Extract the actual sender mailbox address from the message header, normalize case and whitespace, and match the complete address. Do not match display names or collapse distinct mailbox addresses using guessed aliases.
- A block takes precedence over sender inclusion, built-in sender references, natural-language rules, and existing-task evidence processing. Blocking the primary assignment sender has the same complete effect.
- Consult current sender preferences when advancing jobs and before applying results; newly blocked mail cannot be committed from an older queued or in-flight extraction.
- Suppress unresolved review items from a newly blocked sender so they cannot be approved while the block is active. Preserve tasks and changes already accepted; blocking does not retroactively delete student work.
- Store only minimal sender/message identifiers and an ignored reason for blocked items, without message bodies or evidence excerpts. Apply the existing 30-day expiry to this processing metadata.
- Unblocking affects future processing. Previously ignored mail is reconsidered only through explicit reprocessing.

Blocking applies within DueCare; it does not delete mail or prevent delivery in Gmail. The UI must explain that a complete block also stops automatic completion from that sender's submission receipts.

### Import decision order

1. Read source metadata and apply the complete sender blocklist for Gmail. Blocked mail stops here.
2. Check normal sender eligibility or the student's included-sender preferences, then identify whether the item is potentially an included assignment, test, or related update. Clearly unrelated mail is ignored.
3. Compare candidate academic work with the student's class/year, semester, division, single batch, and theory/lab/tutorial subject context before creating a task or applying an update.
4. Ignore confirmed academic-targeting mismatches. Route insufficient or ambiguous targeting to Needs attention. Only confirmed applicable work proceeds to detailed extraction, matching, duplicate handling, and validated submission processing.
5. Apply remaining task relevance and priority rules within those boundaries, then persist accepted results and evidence idempotently.

The targeting check can use a bounded AI interpretation of the relevant text, but its input must already contain the student's academic context. No task may be created first and checked for academic applicability afterward.

### Classroom import

Read:

- Available Classroom course metadata for linking to manually added subjects.
- Coursework for Classroom sources explicitly linked to those subjects.
- The connected account's own submissions.
- Announcements relevant to assignments or tests.

Students manually add their subjects first. Classroom connection does not add subjects or trigger course selection. Students may then link an existing subject to an available Classroom course. Newly discovered Classroom courses remain source metadata until explicitly linked to a manually added subject.

Initial import includes:

- Coursework updated within the last 90 days.
- Older work with future deadlines.
- Older outstanding incomplete work.

Removing a subject's Classroom mapping stops future syncing through that mapping and preserves existing tasks. Source disappearance or loss of access produces a source notice without changing completion status.

Classroom source mappings must retain theory/lab/tutorial context and use the student's batch for applicability checks. They cannot define an alternative student batch. A source course may supply work for more than one manually added subject; resolve each item using subject kind and profile context rather than treating a Classroom course as a single automatically created subject.

#### Assignment and announcement reconciliation

- Import actionable announcement text as well as structured coursework. The supplied DBMS examples place test dates, upload instructions, and later changes in the stream, so reading coursework alone would miss obligations.
- Classify actual intent instead of copying the provider's work type into DueCare's two task types. Preserve the provider work type as source metadata.
- Match structured coursework by account, course ID, and coursework ID. Labels such as `IA2.14`, `IA2.15`, and Experiment 4 are identifiers, not decimal dates; neighbouring numbers are separate work until evidence establishes otherwise.
- A stream card saying “posted a new assignment” and the corresponding coursework resource describe the same item when the source link/identifier establishes that relation. Avoid duplicate tasks for the stream card, Gmail notification, and coursework.
- Process edited resources using their source revision/update time. Editing on 23 September does not make 23 September the deadline.
- Resource links, title, relevant description, and available material metadata are sufficient for reference-only supporting material. Do not add attachment downloading, document parsing, OCR, video viewing, or extra Drive access to recover missing schedules or questions.
- Keep reference-material links attached to a relevant task where available. A sample paper, tutorial video, experiment list, or rubric does not independently establish a new obligation or actual semester/batch targeting.
- The current REST resource catalogue does not expose ordinary classroom-comment reading. Do not promise extraction of details visible only in UI comments. Use available announcement/coursework text or Gmail evidence; if necessary information is only in a comment or an inaccessible attachment, require student review. [Classroom REST resource catalogue](https://developers.google.com/workspace/classroom/reference/rest)

### Relevance and profile matching

The first academic check compares each candidate assignment/test with the student's fixed institution/programme, branch code and full name, class/year, semester, division, subject kind, and batch. The profile batch is the sole student batch value used for every subject and source. Do not infer a different batch for a lab, subject, or Classroom mapping.

Use three processing outcomes, separate from task statuses:

| Academic targeting | Processing outcome |
|---|---|
| Confirmed applicable | Continue extraction and matching against the student's manually added subjects |
| Confirmed different class, semester, division, batch, or other academic context | Ignore; do not create a task, review item, completion change, or activity event |
| Missing, ambiguous, or conflicting information that prevents deciding applicability | Needs attention; ask the student before creating a task or applying the disputed update |

A message explicitly intended for another batch or division must be ignored by AI. A message explicitly addressed to all relevant divisions/batches is not a mismatch. Use trusted source mappings or previously confirmed task context when they establish applicability; absent text alone is not proof of a mismatch or proof of a match.

Normalize labels without inventing membership:

- Division B plus batch 2 can correspond to the combined source label B2. Retain the original text and the normalization basis. A naked “2” without established division context cannot resolve an otherwise ambiguous batch.
- SY and second year, and semester III and 3, can be equivalent labels. Academic year 2026–27, admission year 2025, calendar year 2026, and current semester 3 remain different values.
- `DS_B_ODD_26-27` can supply course, division, and term context; it is not a deadline. A group label describing a cohort can support context after student confirmation, but delivery to a mailing list alone is not proof of the student's exact batch or enrolment in every mentioned subject.
- “SY all” in an explicitly mapped minor course is broader targeting rather than a division mismatch. Evaluate the enrolled subject and actual intended audience together.
- Admission-route exceptions such as diploma entrants versus transfer students are not implied by admission year, roll number, or Google identity. When such eligibility is decisive and unknown, route that candidate to review. Do not add an admission-route field or infer the answer.

The new ITVC examples use the combined course audience `A-B-C-D_SY_ODD_26-27`. Interpret the divisions as the set A, B, C, and D, which includes Division B; do not reject it because the first token is A or rewrite the student's division. Course-level audience, activity-level audience, and batch qualifiers are separate observations. An explicit B1-only or other-class qualifier on an activity takes precedence over a broader course-level audience that includes B2.

Store normalized observed targeting as optional sets/qualifiers with their source section and evidence basis: class/year, semester, divisions, batches, term, and subject/component. Absence of a batch label is unknown, not a universal-batch declaration; previously confirmed task/source context may establish applicability. If it cannot, require review. Generic greetings, delivery to the student, and a familiar sender do not bypass this check.

Apply this same filtering to assignment announcements, test notices, reminders, digest rows, receipt association, and updates. An irrelevant receipt cannot complete a different student's or batch's same-named task. If a message explicitly excludes the current class/batch, ignore it without creating a task or review item. If only part of a digest belongs to another cohort, ignore that part and preserve the applicable rows.

Assess targeting per assignment/test or clearly separated message section. If one email contains work for several batches, ignore the sections confirmed for other batches and process only the applicable sections; do not merge their instructions or deadlines. A mismatch must be supported by explicit targeting that excludes the student. Unclear abbreviations, conflicting labels, or an uncertain subject match require review rather than a guessed exclusion or inclusion.

Sender inclusion, priority rules, and manually linked Classroom subjects cannot override a confirmed academic mismatch or silently rewrite student context. Missing or ambiguous targeting cannot be auto-accepted through an include rule.

Review must show the observed class/semester/division/batch, the student's relevant profile values, and the missing or contradictory details. The student can confirm applicability, change the automatically linked subject, or dismiss the item. A student confirmation applies to that item and is retained in its history; it must not silently change the academic profile or batch. Recheck blocks and current academic context before applying the resolution.

Do not infer missing academic profile values, including the batch. Store only minimal source identifiers and a mismatch reason for ignored academic work; apply the existing expiry for irrelevant processing metadata. Reconsider ignored items after profile or batch changes only through explicit reprocessing.

### Completion and reopening

Validated submission confirmation or an explicit student completion decision marks the matched assignment/test completed and removes it from due, overdue, and missed views. This confirmed completion takes precedence over all generic due/overdue mail, including newer mail.

#### Completion precedence and permitted reopening

The backend enforces this rule independently of AI extraction: an accepted completed task cannot transition to due, overdue, or missed because of a deadline notice, overdue label, countdown, digest, late-submission warning, source edit, or passage of time.

| Existing decision/evidence | Incoming event | Result |
|---|---|---|
| Student marked the task completed | Due/overdue reminder, before or after that decision | Stay completed; do not create duplicate work or a status-conflict review |
| Validated matching submission confirmation completed the task | Newer due/overdue notice or digest | Stay completed; generic notice has no reopening authority |
| Completed task | Deadline changes or the date passes | Stay completed; reconcile timing separately without clearing completion |
| Completed task | Another validated receipt for the same activity | Stay completed; record distinct receipt evidence idempotently |
| Incomplete task, even after its deadline | Validated matching submission confirmation | Complete; lateness does not prevent completion or add another status |
| Completed task | Explicit student reopen action | Reopen; derive due/overdue/missed from task type and the accepted cutoff |
| Completed task | Genuinely newer validated unsubmission/withdrawal or explicit task-specific resubmission requirement | Use the existing reopening rules; uncertain evidence requires review, never a guessed reopen |
| Student reopened after an earlier receipt | Replay of that old receipt or a generic reminder | Preserve the student's newer decision |

The latest source publication/edit timestamp wins for conflicting source-derived dates and details on the same established task. Preserve manual edits, event authority, identity, ownership, academic applicability and completion precedence. A permitted reopen must be tied to actual unsubmission or a new explicit obligation, not inferred from an overdue subject line. Deadline-only changes cannot reopen an assignment or test.

#### Gmail evidence

Automatic completion requires:

- A recognized final-submission receipt format.
- A validated academic-system sender.
- A sender that is not on the student's complete blocklist.
- Trusted sender-authentication evidence.
- Submission-confirmation wording from a validated template, rather than due/overdue or saved-draft wording.
- Appropriate connection and recipient ownership checks.
- Academic applicability established from the receipt or trusted existing task/source context, with no confirmed class/semester/division/batch mismatch.

A visible sender address alone is insufficient. Forwarded receipts and unsupported formats require review.

The supplied assignment receipts use the wording “You have submitted an assignment submission,” a course/activity breadcrumb, an activity-status link, and a list of submitted files. Recognize these as candidate confirmation templates for EXP6-BST and ITVC IA2. A template need not contain the literal word “final”; validation must establish what the template confirms. A file list alone, an upload notification without confirmed submission semantics, or a reminder is insufficient.

Compare activity links as source identifiers without visiting them. Namespace the relevant activity ID by source account, host, and activity resource type; retain the existing course/term/subject context and owner checks. This can associate a receipt with a reminder even when titles differ in punctuation or wrapping. A matching link is an association signal, not authentication or proof that the current student is the owner.

The two EXP6 confirmation exports are different messages, dated 25 September and 6 October, for the same activity, with different file metadata. Preserve both evidence events; do not deduplicate them solely by title or activity ID, and do not create a second assignment. A receipt sent after the deadline still completes matched work.

The supplied receipts do not state an independent precise submission transaction timestamp. Preserve the receipt's source occurrence time and its known timestamp basis; do not present the email header's sent time as a separately verified actual upload time. Do not download submitted files.

When several existing tasks are plausible matches, AI selects from the supplied candidate IDs. The backend rejects IDs outside that candidate set or outside the user's ownership, and rejects suggestions across subjects, task types or assessment numbers. Explicit course names and known short forms take precedence over an extracted subject suggestion. AI items must quote an exact excerpt from the current source, so lookup tasks cannot become invented obligations in another message.

Verified LMS assignment and quiz receipts automatically complete the exact matching task. Recognized Moodle quiz confirmations must explicitly confirm submitted answers and that the answers were saved, with an exact quiz activity link; generic test notifications never prove completion.

A verified receipt also completes duplicate notices with the same resolved course, obligation type and exact assessment name after course words and IA quiz/test synonyms are normalized. Different concrete LMS activity IDs remain separate. Generic titles such as “Quiz” alone never establish this fallback identity. Saved verified receipts are reconciled when matching work appears later, without another AI request. A test with no verified receipt or own Classroom turn-in remains incomplete until the student marks it completed; deadline passage does not prove attendance.

When no suitable existing task exists, retain the unmatched receipt metadata and automatically requeue it when its exact task is created or linked. Gmail retries remain within the last 30 days. This allows newest-first interpretation without losing a receipt that arrived before its task.

#### Classroom evidence

- `TURNED_IN` completes the task.
- Genuinely newer validated explicit unsubmission/withdrawal or task-specific resubmission requirements can reopen it; generic due/overdue messages cannot.
- Graded returned work remains completed.
- Ambiguous returned work goes to Needs attention.

Classroom exposes distinct submission states; DueCare must interpret the state together with available submission details. [Classroom submission states](https://developers.google.com/workspace/classroom/reference/rest/v1/SubmissionState)

#### Manual corrections

- Students may manually complete or reopen work.
- Unchanged source evidence cannot undo a manual correction.
- Genuinely newer final submission evidence can complete reopened work.
- Announcements, all generic due/overdue notices regardless of their age, and stale unsubmitted source states cannot reopen completed work.
- Reopened work is due before its cutoff; after the cutoff, an assignment is overdue and a test is missed. No status beyond the approved four is introduced.

Students can reassign receipt evidence and undo merges. Recalculate affected tasks from remaining evidence and manual decisions, preserving the change history.

#### Own-submission and group-work boundaries

For Classroom, use the connected account's own submission ID, state, and available state history. `NEW` or `CREATED` is incomplete; attaching a file does not prove turn-in. A newer `RECLAIMED_BY_STUDENT` is explicit unsubmission evidence. Distinguish a state transition from an unrelated resource edit. Preserve the existing rules for returned work and manual corrections. [Submission states](https://developers.google.com/workspace/classroom/reference/rest/v1/SubmissionState), [Student submission resource](https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork.studentSubmissions)

The supplied IA2.14 screenshot shows Turned in, while Experiment 8 shows Assigned with a Mark as done action. These are useful expected-behavior references; live API state mapping remains to be tested. The Classroom home message that nothing is due soon is not evidence that all assignments are completed.

When the teacher asks one person per group to upload:

- Preserve that instruction and the task's group-work context.
- Do not assume a teammate's upload has completed this student's obligation, or request access to classmates' submissions to check it.
- Complete automatically only from evidence belonging to the connected student and the matched obligation. Students can manually confirm group completion, with the confirmation recorded as a manual decision.
- A single receipt cannot complete every related report, presentation, experiment, and viva merely because they share an assessment label.

#### Work that is no longer required

A newer applicable notice can withdraw a viva or another requirement. Record the notice as a proposed task update in Needs attention. The student can remove the obsolete task using the existing deletion/suppression flow or retain it for their own purpose. Do not mark it completed merely because it was withdrawn, and do not add another task status. A broad statement that marks will be released is not a withdrawal or submission receipt.

### Duplicates and conflicts

- Merge exact, context-safe source identifiers or task links automatically only when subject kind and batch context are compatible.
- Namespace identifiers by service and account context.
- Present similarity-based duplicate candidates for student review.
- Ignore incoming work with a confirmed academic-targeting mismatch. For ambiguous targeting, request clarification. For competing source-derived dates/details on the same applicable work, use the latest source publication/edit timestamp automatically.
- Never merge work from different theory/lab/tutorial subjects, or source work targeted at incompatible batches, merely because titles or subject codes are similar. Compare all batch targeting with the student's single profile batch.
- Preserve manual field corrections without creating a source-conflict review.
- Keep assignments/tests with missing, ambiguous or inconsistent timing as normal undated tasks. Other unresolved issues, such as unclear eligibility, can require Needs attention.
- Import genuinely undated tasks immediately without a timing review.

#### Explicit revisions and field precedence

| Situation | Resolution |
|---|---|
| A newer validated notice explicitly revises the date of the same established test | Replace the old source-derived date, keep history, and create the existing deadline-change activity |
| A newer notice adds a room or login requirement without restating the date | Add the new role-specific information and retain compatible earlier date/start details |
| Current message includes old quoted schedules | Keep the quoted dates as historical evidence; do not create another task for each quoted notice |
| Two applicable sources disagree about dates/details on the same task | Latest source publication/edit timestamp wins automatically; retain history and no source-conflict review |
| A newer source contradicts a student-edited field | Preserve the manual override; no source-conflict review |
| An explicit exam slot differs from ordinary reference hours | Use the explicit slot and expose the reference discrepancy; review any unresolved exam-specific conflict |
| Teacher supplies a tentative interval or two alternatives | Keep the task normally with no specific dates; retain the original alternatives as source evidence |
| A newer general guideline refers to a known assessment without enough identity/context | Enrich only when an established association is safe; otherwise request association review |
| A due/overdue notice disagrees with accepted completion | Keep completed; no reopen, duplicate task, or review merely for the status contradiction |

“Newer” refers to the applicable source event/revision, not the time DueCare imported it. An old email imported after a revised notice cannot restore the old schedule. Source disappearance, deleted posts, grade-release notices, and classmates' comments cannot erase accepted work or prove completion.

Match assessment identity using the established subject, term, assessment label/number, source identifiers, intended cohort, and deliverable. The same short title in a later semester is not the same task. Similarity alone never merges different theory/lab/tutorial subjects, independently required deliverables, or adjacent numbered assessments.

### Rules

Support simple filters and natural-language rules.

Allowed actions:

- Include or exclude newly detected tasks.
- Set priority.

Natural-language rules must produce a structured preview that the student confirms before activation.

Rules are ordered by the student:

- First matching relevance rule decides inclusion or exclusion.
- First matching priority rule supplies rule priority.

The complete sender blocklist and mandatory academic-targeting check run before ordered task rules. No include rule overrides a blocked sender, a confirmed academic mismatch, or unresolved applicability.

Ordinary task relevance rules do not suppress submission evidence or authorized updates for existing tasks. The complete sender blocker is a separate control and deliberately suppresses all processing from the blocked sender, including those updates and receipts.

Rule changes apply to future processing by default. Provide an explicit reprocessing action.

Use a validated, allowlisted condition structure covering source, sender, subject, subject kind, class/year, semester, division, the batch and observed source targeting, academic targeting, keywords, and task type. Rules cannot define per-subject student batches. Natural-language interpretation cannot generate executable code, database queries, or additional actions. Exact sender inclusion/blocking is managed through dedicated sender preferences rather than being weakened by rule ordering.

### Syncing and failure behavior

There is no scheduled syncing.

Start or resume syncing:

- On login or app opening.
- On tab refocus when the last automatic attempt was at least 15 minutes ago.
- When the student selects **Sync now**.

The API worker advances durable jobs after the browser enqueues them:

- Each sync chunk has a 90-second work budget.
- Configure both backend and gateway request duration to allow processing and response overhead.
- Save durable checkpoints between chunks.
- Show successful partial results immediately.
- Continue processing when the page is hidden, another app is focused, or the browser closes.
- Resume durable queued work after API restart; honor active leases and saved retry timing.
- Account and source deletion also run in the API worker. The API must remain running.
- Permit only one in-flight sync per connection.

Within that connection's lease, import and interpretation run concurrently. The importer commits source records and its checkpoint; a separate lane interprets committed records and applies validated tasks and deadlines immediately. Refresh visible source progress, tasks, calendar, and overview every five seconds while work is active, including during a running request. Interpret submission confirmations and Classroom submission states as they arrive; retry unmatched receipts when their exact task is created. Explicit reprocessing finishes re-queuing before interpretation begins.

An active Gmail import checkpoint may keep keyed, opaque duplicate fingerprints and source record IDs so duplicate detection survives early minimization of an ignored original. Erase that temporary index when importing ends, fails, or is cancelled. This does not retain ignored source text, titles, excerpts, or plain content hashes.

Permit up to ten OpenRouter calls per API process across source lanes; other providers share one request slot. Respect model cooldowns after HTTP 429 and temporary server failures while continuing imports and deterministic interpretation. An exhausted request budget keeps unfinished work queued for the next request; it does not impose an AI outage pause. Persist only safe provider status codes in logs, without provider bodies or source prompts.

Persist retry timing, leases, and checkpoints in PostgreSQL. Retry provider quota and temporary failures with backoff. Do not advance checkpoints past unpersisted work.

If both AI providers fail, preserve successful results and pause only the items requiring AI. Other eligible processing can continue. Resume failed items during later active syncing or explicit retry.

### Activity inbox

Include activity for:

- New tasks.
- Deadline changes.
- Reopened tasks.
- Items requiring review.
- Connection and sync issues.

Provide unread/read state and links to the affected task, review item, or connection.

## 3. Architecture, AI, security, and privacy

### Approved stack

| Area | Choice |
|---|---|
| Frontend | Next.js, TypeScript |
| UI | Tailwind CSS, shadcn/ui |
| Server-state management | TanStack Query |
| Forms | React Hook Form, Zod |
| Backend | FastAPI, Pydantic |
| Database | Supabase PostgreSQL |
| Authentication | Supabase Auth with Google |
| Database access | SQLAlchemy, Alembic, psycopg |
| Integrations | Official Google API clients |
| AI | Groq primary, configured Groq/OpenAI/Gemini fallbacks (text only); timetable files are read without AI using pdfplumber and local Tesseract OCR |
| Tests | Pytest, Vitest, React Testing Library, Playwright |
| JavaScript runtime | Node 24 |
| Python runtime | Python 3.13 |
| Package management | npm and uv, with lockfiles |
| Hosting | Separate frontend and backend Vercel projects |

Node 24 is supported by Vercel, and Vercel supports deploying FastAPI applications. [Node runtime](https://vercel.com/docs/functions/runtimes/node-js/node-js-versions), [FastAPI deployment](https://vercel.com/docs/frameworks/backend/fastapi)

### Request flow

`Browser → Next.js server gateway → FastAPI → PostgreSQL / Google APIs / AI APIs`

Next.js handles:

- Google sign-in through Supabase.
- Authentication callbacks.
- Secure server-managed cookies.
- Session refresh.
- Same-origin gateway requests.

FastAPI owns:

- Business rules.
- Ownership enforcement.
- Integrations.
- Extraction and matching.
- Task reconciliation.
- Sync jobs.
- Data deletion.

The browser does not access the application database directly or hold Google source tokens.

### Authentication and authorization

- Enable Google as the only Supabase sign-in provider.
- Gate account creation to verified Somaiya Google identities.
- Recheck eligibility during authenticated API authorization.
- Do not use editable profile metadata as authorization evidence.
- Validate JWT signature, issuer, audience, expiry, and user identity.
- Check the JWT's native Supabase session against `auth.sessions` to reject revoked sessions.
- Use Supabase's default session behavior without custom idle or maximum-duration policies.

Supabase documents its default session behavior and native session checks after sign-out. [Supabase sessions](https://supabase.com/docs/guides/auth/sessions)

Store authentication tokens in secure, HTTP-only cookies managed by the server. Do not initialize a browser Supabase Auth client that requires access to those tokens.

Protect state-changing gateway requests with origin checks and CSRF protection. Refresh sessions on the server and prevent concurrent refresh races.

### Source OAuth

Use one Somaiya-owned Google OAuth application with an external audience.

Separate DueCare login from source authorization:

- Somaiya identity is required for login.
- Personal Google accounts may supply source data.
- Source callbacks require an authenticated DueCare session.
- Use OAuth state, PKCE, callback allowlists, and verified account identity.
- Never link source accounts as Supabase login identities.
- Request each service's permissions when that service is connected.

Scopes:

- Identity: `openid`, `email`, `profile`.
- Gmail: `gmail.readonly`.
- Classroom: `classroom.courses.readonly`, `classroom.coursework.me.readonly`, `classroom.announcements.readonly`.

Encrypt refresh tokens at rest with versioned encryption keys. Keep credentials server-side. Preserve an existing refresh token when a later authorization response omits a replacement.

Disconnecting one service must not accidentally revoke another service's shared authorization. Remove local access for the selected service; revoke the Google grant when the entire account is disconnected or no remaining service uses it.

### Database security

- Use a private application schema that is not exposed directly through browser-accessible APIs.
- Use a least-privilege runtime database role.
- Apply ownership checks to every read and write.
- Apply row-level security as additional protection.
- Set user context within transactions.
- Prevent cross-user relationships through constraints and application validation.
- Use the Supabase transaction pooler for runtime connections, SSL, a small connection pool, and compatible prepared-statement settings.
- Use a separate privileged migration connection.
- Keep Supabase-managed authentication tables outside Alembic ownership.

### AI contract

AI performs classification, extraction, rule interpretation, and permitted candidate matching. It does not provide student-facing summaries or chat.

- Groq is primary (student decision). After a retryable failure, or invalid structured output following one repair attempt, try the configured Groq fallback model, then OpenAI, then Gemini.
- One deadline bounds a whole provider chain, including repairs and fallbacks, where a workflow sets one (timetable upload).
- Model IDs are deployment configuration.
- Validate configured models against extraction and matching fixtures before release.
- Reject outputs that violate schemas, ownership, task-type restrictions, or candidate constraints.
- Treat message content as untrusted input.
- Never send blocked-sender message content to an AI provider.
- Supply class/year, semester, division, the student's single batch, manually added theory/lab/tutorial subjects, and relevant valid weekly slots before interpreting candidate work; use that batch for every subject.
- Check academic applicability before detailed task extraction and association; ignore confirmed mismatches and send ambiguous or insufficient targeting to student review.
- Match only to existing subject IDs owned by the student; never create subjects or per-subject student batch values from AI output, or combine work with incompatible source batch targeting.
- Send necessary academic text only.
- Exclude unnecessary personal details, unrelated messages, and attachment contents.
- Store processing/model versions for reproducibility without retaining full prompts or full source bodies.

Structured extraction must distinguish notice intent (`new work`, `revision`, `due/overdue notice`, `supporting information`, `submission`, `withdrawal`, or `unknown`), current versus quoted sections, intended audience, assessment/deliverable identity, timing roles, and per-field evidence references. These are processing attributes, not additional task types or statuses. AI may propose only assignment/test obligations; the backend owns the approved due/completed/overdue/missed lifecycle and validates all decisions before applying them.

Keep student names, other students' roll numbers, seating rosters, unrelated personal passages, and signatures out of AI input when they are unnecessary. Where a notice contains an explicit per-student schedule, determine the student's matching row using confirmed identifiers and retain only necessary row-level academic information. A name-only resemblance is insufficient. If the roster is an attachment or inaccessible linked document, preserve its metadata and use review under the existing attachment policy.

The supplied examples guide redacted extraction fixtures, schema validation, and evaluation. Reading examples is not model training. Do not promise fine-tuning, automatic learning from every correction, or sending historical private mail to a training pipeline. A correction changes the relevant task/mapping/rule only through an explicit supported action.

The project funds AI usage. Students supply no API keys. There is no application AI spending ceiling.

Use provider settings and paid service terms appropriate for private academic data. Google-derived data must follow the applicable user-data requirements. [Google API user-data policy](https://developers.google.com/terms/api-services-user-data-policy), [Gemini terms](https://ai.google.dev/gemini-api/terms)

### Retention and deletion

- Retain relevant task instructions, source metadata, and minimal evidence excerpts.
- Re-fetch source content when retrying instead of permanently storing full bodies.
- Retain linked evidence and task history until deletion.
- Expire skipped/irrelevant processing metadata and diagnostics after 30 days.
- Hide expired records immediately; physically purge them during later application activity.
- Retain unfinished operational checkpoints until completion or cancellation.

Disconnecting a source preserves imported tasks and offers a separate imported-data deletion action.

When imported data is deleted:

- Preserve tasks supported by another source.
- Preserve student-created work.
- Convert source-only tasks containing student edits into manual tasks.
- Remove associated source evidence and credentials as applicable.

Deleted imported tasks remain suppressed during later syncs. Retain minimal suppression identifiers, with explicit restore/reimport support.

Account deletion stops new processing, removes application data and source credentials, and deletes the authentication account. Make deletion resumable and idempotent.

The local web implementation persists privacy operations before external revocation or deletion steps. Disconnect and imported-data deletion are separate actions. An unfinished operation blocks sync, restoration and reconnection to its affected Google account until it completes. Account deletion freezes normal workspace access and uses an HTTP-only recovery capability; an authenticated second browser can recover pending progress. Completed account-deletion receipts remove the user reference and expire after 30 days, while unfinished checkpoints remain. [Local operations](OperationsLocal.md) describes recovery and the bounded request chunks.

Privacy settings provide deletion and connection controls. There is no administrative student-data browsing interface.

### Operational limits

Do not impose product caps on connected accounts, subjects, rules, tasks, or total imported messages.

Pagination, request work budgets, provider quotas, and infrastructure capacity remain technical constraints. Show actual connection or processing failures without describing free hosting as unlimited.

Gmail's read-only scope is restricted. Production verification and applicable security assessment requirements must be satisfied for server-side storage or transmission. [Gmail scope requirements](https://developers.google.com/workspace/gmail/api/auth/scopes)

## 4. Database, API, and frontend contracts

### Database conventions

Use UUID primary keys, UTC timestamps, explicit foreign keys, and snake_case database names. Every user-owned record carries `user_id`.

Use revisions for editable records. Preserve source occurrence time separately from ingestion time.

### Required entities

| Entity | Required stored information |
|---|---|
| `profiles` | Auth user ID; Google name/email/photo; six academic fields plus fixed KJSSE/BTech and canonical branch code/full name, including distinct class/year, semester, division, and batch; onboarding state; theme preference; revision; timestamps |
| `google_accounts` | Owner; Google subject; verified email; display metadata; connection timestamps |
| `oauth_grants` | Account; scopes; encrypted refresh token; encryption-key version; grant status; timestamps |
| `connections` | Owner/account; Gmail or Classroom; granted permissions; status; last attempt/success; incremental checkpoint; retry time |
| `subjects` | Owner; manually entered name; kind (`theory`, `lab`, or `tutorial`); optional subject code/confirmed aliases/academic-term label; confirmed source class-code references with their identifier namespace and component label; revision; timestamps; academic context inherited from the profile, with no subject-level student batch field |
| `subject_timetable_slots` | Owner; existing subject ID; ISO weekday; local start/end time; Asia/Kolkata timezone; optional venue/instructor; optional validity date bounds; semester/term context at entry; stable ID; timestamps; edits governed by subject revision; no student batch value or override |
| `subject_mappings` | Subject; connection; external Classroom course identifier; relevant source course name/section metadata; explicit mapping state; source availability; theory/lab/tutorial context; no student batch override |
| `tasks` | Owner; optional subject; type; title; relevant instructions; assessment/deliverable labels; optional source component label; academic-term context; observed audience/batch targeting (evidence only, not student membership); timing mode/fields defined below; venue; accepted completion state, origin, evidence reference, recorded time and source-time basis; latest explicit manual decision and permitted reopening evidence; status enum/snapshot (`due`, `completed`, `overdue`, or `missed`); notes; estimated effort; manual priority; rule priority; manual field overrides; revision |
| `source_records` | Connection; namespaced provider ID and relevant course/work or activity-resource ID; external link; sender mailbox; relevant source title; sent/received/published/updated time separately; thread/parent references when available; content/revision hash; processing state; academic-targeting outcome; minimal ignored/review/status-suppression reason; minimal evidence excerpt for eligible work only; processing version; expiry when applicable; blocked records retain only permitted identifiers/reason |
| `source_attachments` | Source record; filename/title; link or provider reference; media type and available size |
| `source_events` | Source record/revision; classified event type (including due/overdue notice, submission confirmation, or explicit reopen); candidate obligation/deliverable identity; relevant section/digest-row reference; observed targeting with qualifier scope; role-specific fields with evidence references; source occurrence/submission/state-transition time and basis when supplied; superseded event references; sender/template/ownership validation result; processing version |
| `task_evidence` | Task/event relationship; association method; active/reassigned state; timestamps |
| `task_history` | Task; action; actor; changed fields; evidence reference; source occurrence time; recorded time |
| `rules` | Owner; name; enabled state; ordering; original instruction; structured conditions/exceptions/actions; version/revision |
| `sender_preferences` | Owner; normalized exact sender email; action (`include` or `block`); revision; timestamps; unique per owner/sender |
| `review_items` | Owner; optional task/source/event; issue type; observed academic targeting; relevant student/subject context; missing/conflicting fields; proposed fields/date windows/tentative alternatives; bounded evidence excerpts; resolution; timestamps |
| `activity_notifications` | Owner; event type; related task/review/connection; message; created/read timestamps |
| `sync_jobs` | Connection; import/reprocess mode; phase; status; checkpoint; progress counters; lease; next retry; sanitized error; timestamps |
| `suppression_records` | Owner; namespaced source identifiers; deletion time; restore state |
| `privacy_jobs` | Owner; connection identifier; disconnect/source-data kind; current stage; pending/waiting-retry/completed state; content-free counters; safe error code; revision and timestamps |
| `duecare_internal.account_deletions` | Server-only checkpoint; owner while pending; hashed recovery capability; stage/status; safe error code; created/completed timestamps; owner removed on completion; no source text or account address |
| `merge_operations` | Owner; surviving and absorbed task references; association/field changes required for undo; timestamps |

#### Task timing and supporting fields

These fields refine existing assignment/test tasks. They do not introduce another task lifecycle or require extra fields for a manual task.

| Stored field | Data contract |
|---|---|
| `due_at` | Nullable UTC timestamp; incomplete-status cutoff under the timing rules above |
| `timing_mode` | `deadline_only`, `fixed_session`, `attempt_window`, `unresolved`, or `undated`; timing metadata, not another task type or status |
| `submission_opens_at` | Nullable UTC timestamp for assignment availability |
| `availability_opens_at`, `availability_closes_at` | Nullable UTC online-quiz availability bounds; use the close as the cutoff for attempt-window tests, preserving any separate classroom attendance times |
| `login_by_at`, `reporting_at`, `starts_at`, `ends_at` | Separate nullable UTC timestamps for explicitly distinguished attendance roles |
| `date_window_start`, `date_window_end` | Nullable local date values with a timezone and role; unresolved slot range, never automatically substituted for `due_at` |
| `date_alternatives` | Validated candidate dates/intervals with their stated tentative basis; unresolved alternatives ordinarily belong in a review proposal |
| `duration_minutes` | Nullable positive number; retain explicit or derived basis |
| `timing_provenance` | Per-field original date/time wording, timezone, precision/basis, eligible source event reference, timetable slot ID/subject revision when used, and manual-override marker; bounded excerpts only |
| `location` | Optional relevant room/venue label with evidence reference; do not store the full seating roster |
| `assessment_label`, `deliverable_label` | Optional labels distinguishing assessment series and separately actionable work; labels do not determine task type by themselves |
| `component_label` | Optional source context such as theory, practical, or tutorial; does not automatically create another subject kind |
| `academic_term_label` | Optional established term context used to avoid mixing repeated titles across semesters/academic years |
| `instructions` | Relevant preparation, syllabus, required tools, and deliverable requirements; supporting points/rubrics can remain text rather than creating a grade-tracking schema |

Weekly timetable slots are approved optional subject context. They are manually entered; the reference slots in section 6 are examples and must not be seeded automatically into user records. A tutorial has its own subject ID and slots even when it shares a course code with theory.

Important constraints:

- Unique source identifiers within the correct connection and service context.
- Idempotent source-event processing.
- A source revision can emit several role-specific updates, but replaying that revision cannot duplicate tasks or history events. A later revision of the same message/resource remains processable.
- One active leased sync job per connection.
- Same-owner task, subject, event, and evidence relationships.
- Explicit subject kind; store the student's sole batch value in the profile and use it for every subject. No subject, mapping, or task may override student batch membership.
- No subject creation from connection callbacks, source discovery, email extraction, or AI processing.
- Timetable slots belong to an existing subject owned by the same user. Validate weekday 1–7, local time values, end after start, and ordered validity dates. Detect multiple/overlapping matching slots rather than arbitrarily selecting one.
- On semester/term changes, slots from the old context cannot silently supply new-term times. Existing task provenance retains the slot/revision used even after that slot is edited or removed.
- Sender preferences are user-owned; block decisions supersede all inclusion and processing paths. Do not store blocked message bodies or excerpts.
- Record academic-targeting outcomes and minimal reasons separately from the four task statuses; reject AI output that bypasses a confirmed mismatch or unresolved applicability.
- Exactly four effective task statuses; derive incomplete status from type, timing mode, accepted cutoff, and current time. Enforce overdue-only-for-assignment and missed-only-for-test constraints. Completed always takes precedence over the clock and reminder labels.
- A confirmed fixed-session test's `starts_at` and `due_at` agree; an attempt-window test's `availability_closes_at` and `due_at` agree. Reporting/login/opening fields do not overwrite the applicable cutoff. Reject inconsistent accepted intervals and negative durations; conflicting extracted timing values leave the imported task undated without a timing review.
- Accepted completion is persisted independently of reminder labels and effective deadline calculations. The backend rejects any attempt to apply a generic reminder event as a completed-to-incomplete transition, even when AI proposes it or the event is newer.
- Recheck the current task completion state, latest manual decision, and revision in the applying transaction. A queued reminder extracted before a receipt/user confirmation cannot commit an incomplete status after that confirmation; retries and concurrent syncs obey the same guard.
- Preserve the latest manual completion/reopen decision and explicit permitted-reopen evidence during replay, reprocessing, merge undo, and evidence reassignment. A status change requires its own authorized action/evidence; updating a deadline cannot clear completion.
- Preserve local date windows and tentative alternatives without manufacturing timestamps. Each accepted timing field retains its independent provenance; source-update timestamps never become deadlines by default.
- Ordinary assessment points, published marks, and receipt sender addresses cannot independently set completion.
- Indexed task completion/deadline/subject, subject kind, source identifiers, active jobs, unread activity, and unresolved reviews.
- Suppression survives removal of a deleted task's ordinary contents.

### Public API conventions

FastAPI exposes versioned REST under `/api/v1`, with generated OpenAPI documentation.

- JSON uses camelCase.
- Cursor pagination defaults to 50 records and allows at most 100 per page.
- Page size does not limit total records.
- Use opaque cursors with deterministic ordering.
- Return structured errors with `code`, `message`, optional field errors, and `requestId`.
- Require the current revision for edits.
- Return `409` for revision conflicts.
- Use idempotency keys for job creation and destructive or reversible compound operations.
- Return `404` for inaccessible user-owned resources without revealing another user's data.
- Never return OAuth tokens or internal credentials.

### Endpoint groups

| Area | Routes and behavior |
|---|---|
| Profile | `GET/PATCH /me`; retrieve identity/profile and edit permitted academic/preferences fields |
| Overview | `GET /overview`; dashboard task groups and current processing/review state |
| Tasks | `GET/POST /tasks`; `GET/PATCH/DELETE /tasks/{id}` |
| Task history | `GET /tasks/{id}/history`; paginated source and change timeline |
| Subjects | `GET/POST /subjects`; `GET/PATCH/DELETE /subjects/{id}`; kinds theory/lab/tutorial; subject creation is student-initiated |
| Subject timetable | `GET/PUT /subjects/{id}/timetable`; retrieve or atomically replace the subject's optional weekly slots using its current revision; omitted existing slots are removed after explicit save |
| Timetable upload | `POST /timetable-imports/extract` (multipart; returns grid cells and page previews); `POST /timetable-imports/interpret` (returns an editable draft; no writes); `POST /timetable-imports/confirm` (`dryRun` summary, or one atomic save across subjects in add/replace mode) |
| Classroom mapping | `GET /connections/{id}/classroom-courses` for source metadata only; `PUT/DELETE /subjects/{id}/classroom-mappings/{connectionId}/{externalCourseId}` for explicit linking/unlinking |
| Connections | `GET /connections`; `POST /connections/authorize`; `GET /connections/oauth/callback`; `DELETE /connections/{id}` |
| Sync | `POST /connections/{id}/sync`; `GET /sync-jobs/{id}`; `POST /sync-jobs/{id}/advance` |
| Reprocessing | `POST /connections/{id}/reprocess`; creates a resumable explicit reprocessing job |
| Rules | `GET/POST /rules`; `POST /rules/interpret`; `PATCH/DELETE /rules/{id}`; `PUT /rules/order` |
| Sender preferences | `GET /sender-preferences`; `PUT /sender-preferences/{senderEmail}` with action `include` or `block` and revision for replacement; `DELETE /sender-preferences/{senderEmail}` to remove the preference; URL-encode the exact address |
| Review | `GET /review-items`; `GET /review-items/{id}` for the exact open review; `POST /review-items/{id}/resolve` |
| Duplicates | `POST /task-merges`; `POST /task-merges/{id}/undo` |
| Evidence | `POST /evidence/{id}/reassign` |
| Activity | `GET /activity`; `PATCH /activity/{id}` for read state |
| Privacy | `GET /privacy/jobs`; `POST /privacy/jobs/{id}/advance`; `POST /privacy/source-data-deletions`; `GET/POST /privacy/account-deletion` for owner-confirmed deletion and checkpoint recovery |
| Restore | `GET /suppression-records`; `POST /suppression-records/{id}/restore`; `POST /connections/{id}/reimport` for explicit source reimport after restoration |
| Health | Minimal public liveness endpoint; protected dependency diagnostics |

Task edits cover completion, reopening, notes, deadlines, subject assignment, and priority overrides. Task responses and filters expose exactly `due`, `completed`, `overdue`, and `missed`. Students mark work completed or reopen it; the server determines the effective incomplete status from type, timing mode, and cutoff. Clients cannot force overdue/missed through an arbitrary status edit or use missed for an assignment. Reject unsupported task statuses.

The existing task create/edit contracts can accept optional timing and supporting fields in camelCase: `timingMode`, `submissionOpensAt`, `availabilityOpensAt`, `availabilityClosesAt`, `loginByAt`, `reportingAt`, `startsAt`, `endsAt`, `dateWindowStart`, `dateWindowEnd`, `durationMinutes`, `location`, `assessmentLabel`, and `deliverableLabel`. Required manual fields remain `title` and `type`. Validate related fields atomically and mark student edits as manual overrides. No additional scheduling endpoint or external calendar connection is implied.

Editing a confirmed fixed-session test start updates `startsAt` and its effective `dueAt` together. Editing an attempt-window quiz close updates `availabilityClosesAt` and `dueAt` together. The UI exposes the applicable edit rather than requiring the student to keep equivalent fields synchronized. Reporting, login, opening, and end-time edits remain separate. Neither edit reopens completed work.

Review responses expose proposed alternatives, source role labels, and the precise unresolved question, such as “Which date in this exam window applies to you?” or “Does this transfer-student exception apply?” Resolution can confirm an undated/window-only task, choose an existing subject, accept a proposed same-task revision, correct timing, confirm applicability, or dismiss the item. The backend rechecks ownership, current sender blocks, academic context, and record revision before applying a resolution. A confirmed mismatch remains an ignored source item rather than an item that the UI can silently approve.

Deleting a subject detaches task associations rather than deleting personal task work. Destructive API responses report the affected records. Source-metadata endpoints must not create subjects as a side effect.

Timetable responses include the current subject revision. A replacement updates that revision and returns stable IDs for retained/new slots. An empty `slots` array explicitly clears the timetable; timetable omission in ordinary subject edits preserves it. Deleting the subject removes its slots while preserving accepted task history and the minimal schedule basis used in past interpretations.

Representative manual timetable replacement for an already-created DS lab subject:

```json
{
  "revision": 4,
  "slots": [
    {
      "weekday": 2,
      "startsLocalTime": "11:00",
      "endsLocalTime": "13:00",
      "timezone": "Asia/Kolkata",
      "location": "A105",
      "instructorLabel": null,
      "validFrom": "2026-07-13",
      "validUntil": "2026-11-18"
    }
  ]
}
```

The example uses Tuesday (`weekday: 2`) and no batch field. The subject's existing identity and current profile context supply ownership and applicability. Retained slots in later replacements include their returned IDs.

The Next.js gateway forwards these contracts without duplicating business logic. Its authentication routes handle sign-in, callback, session refresh, and sign-out.

### Representative task request

```json
{
  "title": "Database lab report",
  "type": "assignment",
  "subjectId": null,
  "dueAt": null,
  "notes": "",
  "estimatedEffortMinutes": null,
  "priorityOverride": null
}
```

An edit includes the current revision:

```json
{
  "revision": 4,
  "status": "completed"
}
```

Task responses include the effective four-value status, subject kind, the student's profile batch and any observed source targeting, effective priority, separate timing roles/windows and their precision/defaulting, source availability, completion provenance, and revision. Observed targeting does not establish a second student batch.

Generic reminders cannot call the manual status-edit path. Reconciliation classifies and validates incoming events before applying them; it is not a passthrough of an AI-proposed `status`. Responses can expose the completion origin/evidence and a minimal reason that a contradictory reminder did not change it. Completed tasks remain outside due/overdue/missed groups and counts regardless of source-mail labels.

Representative extracted timing proposal for the revised Discrete Maths quiz (an extraction fixture, not a claim that this task exists in the application):

```json
{
  "type": "test",
  "timingMode": "fixed_session",
  "title": "Discrete Maths IA1 quiz",
  "assessmentLabel": "IA1",
  "reportingAt": "2026-10-01T08:00:00Z",
  "startsAt": "2026-10-01T08:10:00Z",
  "endsAt": "2026-10-01T08:30:00Z",
  "dueAt": "2026-10-01T08:10:00Z",
  "durationMinutes": 20,
  "location": null,
  "sourceTimezone": "Asia/Kolkata",
  "timingProvenance": {
    "reportingAt": { "basis": "source-exact", "evidenceRef": "E03" },
    "startsAt": { "basis": "source-exact", "evidenceRef": "E03" },
    "endsAt": { "basis": "source-exact", "evidenceRef": "E03" }
  }
}
```

`E03` is a documentation reference. Production evidence references use owned, persisted event IDs. The UTC values above display as reporting 13:30, start 13:40, and end 14:00 IST. Prior 30 September scheduling remains historical evidence rather than another task.

### Screens

| Screen | Required behavior |
|---|---|
| Sign-in | Somaiya Google sign-in; clear rejection for ineligible identities |
| Onboarding | Six required academic fields with fixed institution/programme and a branch dropdown with separate class/year, semester, division, and one batch for all subjects; manually add theory/lab/tutorial subjects without entering another batch; optional timetable and connections; no Classroom course-selection step |
| Dashboard | Due, completed, overdue assignments, missed tests, undated work, Needs attention, and sync progress |
| Tasks | Search; subject/subject-kind/batch/type/status/priority/date/source filters; due/completed/overdue/missed status filters with type-specific validity; editing, completion, and reopening actions |
| Task detail | Instructions, assessment/deliverable labels, subject kind, profile batch versus observed targeting; clearly separate upload opening/deadline, quiz availability, and login/report/start/end; venue, date precision, personal fields, links, attachment metadata, completion origin/evidence, revision timeline |
| Calendar | Confirmed dated assignments and tests; clear date-only labels; exam windows/tentative alternatives visibly unresolved, never plotted as an invented exact slot or all-day exam lasting the whole window |
| Subjects | Manually add/edit subjects using only name and theory/lab/tutorial kind; enter/edit/remove weekly slots with weekday, local times, optional venue/instructor; no Valid from/Valid until inputs; use the profile's batch without another batch input; explicitly link existing subjects to Classroom source metadata |
| Needs attention | Show observed versus student academic context; missing/conflicting targeting or timing, tentative alternatives, unknown eligibility, and proposed withdrawal; confirm applicability, select an existing manual subject, resolve the actual question, or dismiss; do not show blocked mail or confirmed mismatches as review items |
| Rules | Simple rule editor; natural-language interpretation preview; enable/order/edit/reprocess |
| Sender preferences | Add included sender emails; add/remove complete blocks; show block precedence and its effect on submission receipts; offer explicit reprocessing after unblocking |
| Connections | Accounts, service permissions, sync status, Sync now, reconnect/disconnect |
| Activity | Unread/read events linking to affected records |
| Settings | Academic profile with distinct targeting fields; sender preferences; theme, connection and deletion controls |

Use a spacious blue-neutral visual system with light and dark themes. Start with the system theme and allow a saved preference.

All workflows must work in desktop and mobile browsers. Include accessible labels, keyboard operation, loading states, empty states, recoverable errors, and visible partial-sync results.

Use concrete review explanations rather than scores: “Exact exam date has not been announced,” “Two weekly slots match this notice,” or “Two applicable notices give different start times.” Confirmed other-division work remains ignored rather than becoming a review item. Do not bury arrival instructions under the submission-deadline label, and do not display a source edit date as an assignment date.

## 5. Verification, roadmap, and future scope

### Current evidence

- The DueCare checkout has no application implementation yet.
- Gmail authorization success is user-reported.
- The existing access probe checks Gmail profile access and message listing.
- Classroom authorization, body extraction, submission interpretation, and deployed integration remain separate validation milestones.
- The first batch supplied 12 EML exports and 23 screenshots. The second supplied 11 email paths, including the already catalogued E09 notice and 10 additional files. All 22 catalogued exports were decoded successfully. Two earlier DS follow-up exports share the same Message-ID and decoded selected body; the two EXP6 receipts are distinct messages for one activity.
- The primary sender `lms-kjsse@somaiya.edu` appears in an actual B2 practical-test notification. Faculty/department examples cover assignments, quizzes, IA tests, ESE practical windows, seating changes, and conditional assessment notices.
- Course details visibly establish Semester III, Division B, and batch 2 for the supplied reference student. These are examples for documentation and evaluation; no DueCare profile has been populated or inferred automatically.
- Screenshots demonstrate both Assigned and Turned in Classroom work, stream-only obligations, and edited coursework. They do not demonstrate a successful live Classroom API read.
- Exported authentication-result headers are sample data, not independently verified live sender authentication.
- Three assignment-submission-confirmation exports now establish candidate receipt patterns: two EXP6-BST messages and one ITVC IA2 message. Sender authentication, recipient ownership, template semantics, and live task association still require validation before production enablement. Test-submission and withdrawal receipt patterns have not been supplied.
- Supplied EXP6 and ITVC reminder links match their respective receipt activity identifiers. Due/overdue mail is not submission-state authority. The user explicitly requires confirmed completion to survive even a newer contradictory reminder.
- Online-quiz closing was chosen as the attempt-window cutoff, and `missed` was explicitly added as a fourth stored/API task status for expired tests. This supersedes the earlier three-status requirement.
- The examples have not been used to train a model, and no extraction implementation or automated acceptance suite has been run. Section 6 defines expected behavior for future redacted fixtures.

### Required acceptance scenarios

| Area | Acceptance checks |
|---|---|
| Authentication | Eligible Somaiya account succeeds; personal login fails; personal source connection succeeds after eligible login |
| Sessions | Server refresh works; tokens remain inaccessible to browser scripts; revoked native sessions are rejected |
| Ownership | Cross-user reads, edits, source callbacks, matching, merges, and deletion are rejected |
| Onboarding | Six fields required; fixed KJSSE/BTech and branch code/full name; class/year, semester, division, and batch stored separately; roll-number formatting preserved; subjects manually added; no automatic subject creation or Classroom course-selection step |
| Subjects and batches | Theory/lab/tutorial remain separate, including shared course codes; the same profile batch applies to every subject; changing it updates processing context across all subjects; no subject batch inputs or overrides; clear other-batch or other-division work is ignored; ambiguous or insufficient targeting requires review |
| Manual timetable | Optional slots save/edit/remove atomically with revision checks; no batch input; validity/term boundaries enforced; derived times cite slot/revision; ambiguous “during/by lab” text reviewed; source-exact exam time wins over weekly hours |
| Manual tasks | Title/type alone suffice; undated tasks are due until completed; completion, reopening, editing, and deletion persist correctly |
| Task statuses | Exactly due/completed/overdue/missed in database/API; incomplete assignments expire to overdue, tests to missed; attempt-window quizzes become missed at close, not open; completed tasks remain completed; reopening/timing edits recalculate within type-specific rules |
| Dates/priority | IST conversion, date-only default labeling, overdue boundaries, and priority precedence are correct |
| Timing roles | Login, reporting, start, end, and upload opening/closing remain distinct; source publication/edit dates do not become deadlines; duration-derived times retain their basis |
| Windows and tentative dates | ESE and lecture-week windows do not choose a slot; alternative presentation dates remain unresolved; accepted unknown-time tests do not receive invented start times |
| Source chronology | New authored revisions supersede compatible old quoted fields; importing an old message later cannot roll back a newer schedule; explicit same-test revisions do not create duplicate tests |
| Gmail | Primary assignment sender recognized; faculty quizzes/tutorials/internal assessments classified within the two task types; theory/lab/tutorial and batch context used; pagination and incremental updates work |
| Sender inclusion | Student-added sender passes sender eligibility but still requires academic relevance, targeting checks, and receipt validation |
| Complete sender block | Blocks override includes, built-in senders, and rules; no bodies sent to AI, tasks, reviews, updates, receipts, or activity; queued/in-flight results cannot apply after blocking; existing accepted tasks preserved |
| Academic applicability | Check context before task creation; clear wrong class/semester/division/batch ignored; ambiguous details reviewed; broad all-batch notices accepted when otherwise applicable; mixed-batch email sections handled separately; include rules cannot bypass the check |
| Cohort normalization | Division B plus batch 2 matches B2; room B115A is not a batch; admission year and academic term are distinct; an enrolled minor's offering department is not an automatic mismatch |
| Conditional eligibility | Diploma/transfer exceptions cannot be inferred from year or identity; irrelevant Division A roster rows are ignored for a Division B student while applicable general guidance is retained |
| Receipts | Valid final receipt completes; forwarded/spoofed/unsupported evidence does not auto-complete |
| Reminder precedence | Both manual and validated receipt completion survive newer/older due notices, overdue labels, digests, countdowns, deadline passage, and late-submit warnings; no false reopen, duplicate task, missed transition, or status-only review |
| Concurrent reconciliation | A pending reminder job and a receipt/manual-completion write cannot race into clearing completion; the applying transaction checks the current task state/revision |
| Receipt identity | EXP6's distinct receipts map to the same activity/task and remain separate evidence events; same title alone does not deduplicate receipts or complete another deliverable |
| Reminder timing | Labelled absolute dates parsed by role; approximate/negative countdowns ignored as status authority; COA/DSM quiz closing times do not overwrite attendance start/end |
| Online quiz boundary | E20 remains due before 21:00 IST, including between opening and closing; incomplete test is missed at/after 21:00; completed test remains completed |
| Matching | Candidate-only AI selection; unmatched receipt retries when its exact task arrives, within the Gmail 30-day window |
| Classroom | Own submissions only; explicitly mapped manual subjects only; discovering source courses never creates subjects; older outstanding/future work included |
| Classroom content | Actionable announcements are detected; materials/sample questions do not generate tasks; decimal assessment labels remain identifiers; stream and coursework representations reconcile through exact source links |
| Completion | Genuinely newer validated explicit withdrawal/resubmission can reopen; generic reminders never do, even when newer; manual corrections survive unchanged/old evidence |
| Group work | One-uploader instructions do not prove the connected student's completion; independent deliverables/viva remain independent; manual group confirmation keeps its provenance |
| Withdrawn requirements | An applicable withdrawal proposes review/deletion rather than setting completed or adding a fourth task status |
| Conflicts | Latest same-task source publication/edit timestamp wins for source-derived dates/details, independently of sync order; manual corrections stay authoritative; no source-conflict review |
| Duplicates | Exact merge, similarity review, undo, and evidence reassignment preserve history; different theory/lab/tutorial subjects and different-batch work never merge solely by title/code |
| Supplied fixtures | Section 6 covers all 22 catalogued exports and 23 screenshots, including earlier duplicates, EXP6 receipts/reminders, multi-division ITVC targeting, online-quiz expiry, COA thread, DS timing discrepancy, and IA2.14 state |
| Rules | Structured preview and confirmation; ordering works below hard blocks and targeting checks; ordinary rules do not suppress valid existing-task submission updates, while complete sender blocks do |
| Sync | Partial success persists; tab closure stops new work; interrupted jobs resume; concurrent tabs do not duplicate processing |
| AI failure | Primary repair/fallback works; both-provider failure pauses affected items without losing successful imports |
| Privacy | Source deletion preserves personal edits and other-source tasks; deleted imports stay suppressed |
| Retention | Expired diagnostics disappear logically and purge during later activity |
| Frontend | Full mobile-browser workflows, keyboard use, themes, empty/error/loading states |
| Deployment | Vercel runtime, pooled database access, callbacks, cookies, gateway forwarding, and request budgets work live |

Use redacted fixtures for automated tests. Live-provider acceptance must be reported separately from local tests.

Evaluate extraction by exact expected outcomes: correctly identified obligations, correctly ignored sections, correctly unresolved fields, preserved role-specific times, safe duplicate/update decisions, and absence of unauthorized completion. A good result includes asking the student when the source does not establish the answer. Keep evaluation measurements in developer test reports; do not add them to the student task experience.

### Milestones

1. **Foundation and contracts**  
   Establish the approved stack, database migrations, API schemas, ownership checks, and test setup. Acceptance: authenticated profile access and cross-user isolation work.

2. **Identity and manual-task experience**  
   Complete sign-in, onboarding with distinct class/year, semester, division, and a single batch inherited by all manually added theory/lab/tutorial subjects, optional manual weekly timetable context, manual tasks, dashboard, calendar, and responsive layouts. Acceptance: the product works without connected sources, has no subject-level batch input, and exposes exactly four task statuses with missed reserved for tests.

3. **Source authorization and resumable imports**  
   Complete Gmail/Classroom connections, explicit mappings to manually added subjects, batch-aware import, incremental checkpoints, active-browser syncing, and partial results. Acceptance: live authorization and interrupted-job recovery work without automatic subject creation.

4. **Extraction, rules, and reconciliation**  
   Complete sender inclusion and complete blocking, academic applicability checks before extraction, safe MIME/thread/table interpretation, structured AI processing with class/semester/division/subject-kind/batch context and valid manual timetable slots, role-specific dates, revisions/windows, fallback, relevance rules, duplicate handling, conflicts, and Needs attention. Acceptance: redacted fixtures confirm the outcomes in section 6, including blocked/mismatched mail producing no tasks or reviews and unresolved schedules remaining unguessed.

5. **Submission validation**  
   Use the supplied announcements, reminder patterns, and assignment-confirmation templates; collect separate test-submission and withdrawal/resubmission examples. Validate authenticated sender handling, task/owner association, completion precedence under reminder replay, and live own-submission Classroom behavior before enabling the corresponding automatic completion paths. Exported receipt text establishes candidate patterns but is not a live authentication check.

6. **History, activity, and privacy**  
   Complete evidence timelines, corrections, merge undo, activity, disconnection, deletion, suppression, and retention. Acceptance: these operations preserve student work and remain idempotent.

7. **Web release acceptance**  
   Complete automated and live end-to-end checks, provider approvals, deployment configuration, sanitized operational logging, and recovery documentation.

No calendar dates or assumed weekly development pace are assigned.

### Deployment configuration

Document separate environments and server-only settings for:

- Supabase URL, publishable key, and privileged administrative credentials.
- Runtime and migration database connections.
- Google OAuth client credentials and callback URLs.
- Versioned source-token encryption keys.
- Groq, OpenAI and Gemini API keys and explicitly configured model IDs.
- Tesseract OCR installed on the API host for scheduler screenshots.
- Frontend/backend origins.
- Sync work budget and function duration.
- Validated sender/template configuration and completion enablement.

Do not place secrets, real tokens, private message bodies, or student data in the document.

### Future mobile application

Begin native mobile planning after web acceptance. Reuse the established task, source, rule, and reconciliation contracts.

Evaluate mobile authentication, background execution, and time-based notification behavior separately during that future planning stage; they are not dependencies of the current web release.

## 6. College reference evidence and extraction specifications

### How to use this evidence

This section records academic facts visible in the supplied materials and the behavior they require from DueCare. It is a reference catalogue for a future implementation and redacted test suite, not a set of tasks already imported for the student.

- `E01`–`E22` identify the catalogued email export files below. `S01`–`S23` identify screenshots in the order attached to the first request. The DS practical notice supplied again in the second batch retains E09 rather than receiving a duplicate catalogue ID.
- Do not package the original email files, screenshots, mailing-list recipients, raw message IDs, student rosters, or private attachment URLs into the repository. Produce minimal redacted fixtures separately when implementation begins.
- Preserve enough source structure to test current versus quoted messages, timing roles, mixed-batch table rows, and identity matching. Replace unrelated personal details with placeholders.
- KJSSE/BTech are fixed by the student's product decision. Do not treat sample semester, branch, division, batch, course list, or instructor as defaults for every user.
- These samples contain notifications and examples from earlier dates as well as future assessments. Historical examples test chronology; they are not automatically current obligations or completed work.

### Reference student and academic-context distinctions

| Observed reference context | Evidence and implication |
|---|---|
| Current semester III | Scheduler screenshots explicitly show Semester III. Normalize III to 3 for comparison; do not infer semester from a sample paper template |
| Second year / SY | Assessment mail and Classroom titles use second-year/SY labels; keep current class/year distinct from admission year |
| Division B, batch 2 | Detailed DBMS, DS, WDL, and tutorial enrolment cards show B and 2. This supports the combined B2 label in source notices; one profile batch applies across subjects |
| Admission cohort and academic term | Mail-group context refers to the 2025 admission cohort, while course labels refer to the 2026–27 odd term / July–November 2026. These are different concepts |
| Theory, practical, tutorial | Theory, lab, and tutorial are distinct manually added subjects. Tutorial classes have their own class code/instructor/time even when the course code is shared with theory |
| Minor and basket course enrolment | AR/VR minor and Upanishadic Wisdom appear alongside major subjects. Relevant work can come from a broader audience or course-offering department |
| Profile fields not established by all examples | KJSSE/BTech are fixed product values; branch, admission route, and roll-number records are not proved by Google login. Keep manual onboarding and review of unknown eligibility |

The profile's global batch rule remains authoritative. Source records may mention batch-specific schedules; they do not create per-subject student membership. A later screenshot or mail referring to another batch must not silently switch the student to that batch.

### Observed subject catalogue and identifier namespaces

The table is a reference for manual subject names/aliases and future fixture association. Connecting Gmail or Classroom must not populate these subjects automatically.

| Reference subject | Kind/context | Subject code | College class/component code | Relevant naming observations |
|---|---|---|---|---|
| Database Management Systems | Theory | 16U2291 | Theory 352903 | DBMS theory; Classroom `26-27 dbms Div B` |
| Database Management Systems Laboratory | Lab | 16U2296 | Practical 352904 | DBMS lab; Classroom `DBMS B2 116A - Mon 2 to 4 pm` |
| Computer Organization and Architecture | Theory | 16U2577 | Theory 352911 | COA; Classroom `COA 26-27 SY B` |
| Data Structures | Theory | 16U2602 | Theory 352912 | DS theory; visible Classroom title includes theory and Division B |
| Data Structures Laboratory | Lab | 16U2603 | Practical 352914 | DS lab; email course prefix `DS_B_ODD_26-27` supplies additional context |
| Discrete Mathematics | Theory | 16U2604 | Theory 352919 | DSM/Discrete Maths; Classroom `Discrete Mathematics 2026`, B Division |
| Discrete Mathematics Tutorial | Tutorial | 16U2604 | Tutorial 352917 | Separate manual subject; same course code as theory, distinct class context |
| Integral Transform and Vector Calculus | Theory | 16U2538 | Theory 352910 | ITVC; IA2 source describes modelling submission |
| Integral Transform and Vector Calculus Tutorial | Tutorial | 16U2538 | Tutorial 352908 | Separate manual subject; same course code as theory, distinct class context |
| Web Development Laboratory | Lab | 16U2623 | Practical 352921 | WDL; Classroom calls it `SY WPL B2 Jul-Nov 2026`; alias requires explicit confirmation |
| Introduction to Virtual Reality and Unity Game Engine | Minor theory course | 16U2508 | Theory 351907 | Classroom `ARVR MDM sem3`, section `SY all` |
| Glimpses of Upanishadic Wisdom | Basket/theory course | 32SB002 | Theory label displays 32SB002 | Visible Classroom title begins `Upanishad basket course`; truncated portions must not be invented |

College class codes identify an offering/component, not a student. Classroom IDs are opaque service identifiers, not the displayed name or college class code. Some displayed codes happen to be identical; this does not establish equivalence across namespaces.

Screenshots show different instructors for theory, practical, and tutorial components. Jyothi Rao appears for DS theory and DBMS lab. This is a direct counterexample to assigning every message from one faculty sender to one subject. Use confirmed subject aliases, course IDs, task identity, source audience, and content together.

### Weekly reference slots

These slots are transcribed from detailed course cards, not inferred from cropped calendar block sizes. They provide examples for the approved manual timetable-context feature. The student must enter or confirm their own slots; the supplied screenshots do not automatically seed the app.

All times below are IST. Rooms are ordinary teaching locations; an exam notice can specify a different location or time.

| Subject/component | Weekly reference slot | Teaching venue |
|---|---|---|
| DBMS theory | Wednesday 14:00–15:00; Thursday and Friday 12:00–13:00 | B204, Bhaskaracharya |
| DBMS lab | Monday 14:00–16:00 | B116A, Bhaskaracharya |
| COA theory | Tuesday 15:00–16:00; Wednesday 12:00–13:00; Friday 14:00–15:00 | B203, Bhaskaracharya |
| DS theory | Monday 11:00–12:00; Tuesday 10:00–11:00; Thursday 14:00–15:00 | B204, Bhaskaracharya |
| DS lab | Tuesday 11:00–13:00 | A105, Aryabhatta |
| Discrete Maths theory | Tuesday 16:00–17:00; Wednesday 15:00–16:00; Friday 11:00–12:00 | B204, Bhaskaracharya |
| Discrete Maths tutorial | Monday 16:00–17:00 | CCF, Aryabhatta |
| ITVC theory | Monday 12:00–13:00; Tuesday 14:00–15:00; Thursday 15:00–16:00 | B204, Bhaskaracharya |
| ITVC tutorial | Friday 15:00–16:00 | CCF, Aryabhatta |
| WDL lab | Wednesday 16:00–18:00 | B116A, Bhaskaracharya |
| AR/VR minor theory | Tuesday 09:00–10:00; Thursday and Friday 16:00–17:00 | B405, Bhaskaracharya |

The visible teaching period for these detailed cards is 13 July–18 November 2026. The Upanishadic Wisdom overview shows a period ending 30 November. Course enrolment/apply dates, teaching-period dates, credits, and recurring weekdays are reference metadata; none independently creates an assignment deadline or exam task.

### Email source index

| ID | Supplied export filename | Pattern |
|---|---|---|
| E01 | Web Development Laboratory (WDL) Practical Exam ESE 2026.eml | Department notice; practical-exam date window |
| E02 | Regarding DBMS IA2.eml | Timed theory test in an unresolved lecture-week window |
| E03 | Revised Date for Discrete Maths IA1 Quiz – October 1, 2026.eml | Explicit same-test date revision and separate reporting/start/end |
| E04 | ITVC - IA-2 _ AI Enhanced Modelling.eml | Assignment submission opening and closing times |
| E05 | Internal Assessment 1 Schedule - DBMS course.eml | Initial timed quiz announcement |
| E06 | IA1- DS course- September 23, 2026, 1_35 pm(Reporting time), Seating Arrangement(2).eml | Later follow-up with quoted eligibility exceptions and earlier schedule |
| E07 | IA1- DS course- September 23, 2026, 1_35 pm(Reporting time), Seating Arrangement.eml | Original test schedule; image-based seating arrangement |
| E08 | IA1- DS course- September 23, 2026, 1_35 pm(Reporting time), Seating Arrangement(1).eml | Duplicate of E06 by Message-ID and selected decoded body |
| E09 | DS_B_ODD_26-27_ DS OST on 13th Oct 2026-B2 Batch.eml | Primary automated sender; explicit B2 lab-test date/time |
| E10 | DS OST Examination Details.eml | General practical-test requirements without an exact slot |
| E11 | DS IA -II viva Details.eml | General oral-test guidance; quoted Division A student schedule |
| E12 | COA IA 1 scheduled on 28_09_2026 at 1 _30 pm.eml | Multi-message timing revision and mixed-batch room table |
| E13 | [LMS-Reminder] (DS_B_ODD_26-27-Assignment) EXP6-BST is due.eml | Labelled assignment deadline without a submission-state claim |
| E14 | [LMS-Reminder] OVERDUE_ (COA_B_ODD_26-27-Quiz) COA Quiz - IA-1 ODD 2026-27 closes.eml | Quiz-closing notice distinct from classroom timing |
| E15 | [LMS-Reminder] OVERDUE_ (DSM_B_ODD_26-27-Quiz) IA1 Quiz closes.eml | Quiz availability close; negative countdown is not status evidence |
| E16 | Assignment submission confirmation - EXP6-BST.eml | EXP6 confirmation message sent 6 October |
| E17 | Assignment submission confirmation - EXP6-BST(1).eml | Earlier distinct EXP6 confirmation message sent 25 September |
| E18 | Assignment submission confirmation - IA-2 _ AI-Enhanced Modeling.eml | ITVC assignment confirmation with A-B-C-D audience |
| E19 | Due on Monday, 5 October 2026, 10_06 AM_ Exp 5- Doubly LL, Circular LL.eml | Precise assignment deadline and activity link |
| E20 | Opens on Saturday, 5 September 2026, 8_00 PM_ IA -1_5th September 2026 8 pm.eml | ITVC quiz attempt window, opening 20:00 and closing 21:00 |
| E21 | Overdue_ EXP6-BST.eml | Same EXP6 activity as the receipts; late-submit warning |
| E22 | You have assignments due in 7 days.eml | Digest with ITVC due date and same activity identifier as its receipt |

### Observed sender references

These addresses were present in the supplied headers. They are relevance examples, not a universal sender allowlist or proof of final-submission authenticity.

| Sender | Observed role | Required handling |
|---|---|---|
| `lms-kjsse@somaiya.edu` | DS practical notice, due/overdue notices, online-quiz window, assignment-confirmation receipts, and digest | Classify each message's intent separately; perform profile/subject checks; validate candidate receipt templates and never infer unsubmission from reminder mail |
| `dec-comp.engg@somaiya.edu` | Department WDL ESE notice | Broad year-level notice; do not assign an individual exam slot from the date window |
| `jyothirao@somaiya.edu` | DBMS IA theory-test mail | Source/task context determines subject; faculty can teach multiple components |
| `kulkarni.k@somaiya.edu` | Revised Discrete Maths IA1 quiz | Reconcile the explicit revision with the same test |
| `nandinirai@somaiya.edu` | ITVC IA2 modelling upload | Assignment classification despite IA label |
| `swatimali@somaiya.edu` | DS quizzes, OST guidance, viva guidance, and follow-ups | Separate current versus quoted text and eligibility/section-specific information |
| `rohininair@somaiya.edu` | COA IA1 room/timing follow-up | Parse the task's identity and table, rather than infer subject from sender or signature |

Student inclusion and blocking apply exactly as specified earlier. No sample sender is exempt from a complete block. Authentication evidence, template recognition, final wording, ownership, and association must all be validated separately for receipts.

### Expected interpretation of each email

#### E01: WDL practical ESE date window

- The notice covers all second-year batches and a practical-exam window of **30 November–4 December 2026**.
- Candidate: `test`, matched to the manually added WDL lab subject when applicability is established.
- Preserve the date range. The student's individual date, reporting time, start time, and venue are not established by this email.
- Needs attention should explain that the individual slot is missing. The student may accept a window-only test, but its precise `dueAt` remains unset.
- Do not choose 30 November, use 4 December as a due-by timestamp, or create five daily tests.

#### E02: DBMS IA2 unresolved lecture-week test

- The assessment is a **20-mark, 30-minute problem-solving test** involving Normalization and B-Tree topics from modules 3 and 4.
- It will occur during a regular lecture in **19–23 October 2026**, with the exact date to be declared separately.
- Candidate: DBMS **theory** `test`, not a DBMS lab report or a multi-day upload.
- Keep the week as a proposed date window. Do not pick the first scheduled lecture, equate “regular lecture” with a room from another component, or invent an exact start.
- A later exact notice can update the same test once its identity and applicability are established.

#### E03: Discrete Maths IA1 date revision

- The notice explicitly moves the quiz from **30 September to 1 October 2026**.
- Reporting: **13:30**; start: **13:40**; end: **14:00**; duration: **20 minutes**, all IST.
- Candidate: one Discrete Maths theory `test`; the prior date becomes historical evidence.
- A newer same-task source replaces older source-derived schedule/details automatically; manual corrections stay authoritative and source disagreements do not require review.
- Retain relevant syllabus and Safe Exam Browser instructions. The venue is not yet established; do not copy an ordinary lecture room as the quiz venue.

#### E04: ITVC IA2 modelling assignment

- The obligation is an **AI Enhanced Modelling submission**, labelled IA2 and carrying 10 marks.
- Upload window opens **18 September 2026 at 09:00** and closes **9 October 2026 at 23:59 IST**.
- Candidate: ITVC `assignment`; `submissionOpensAt` and `dueAt` are different fields.
- Questions and individual allocation are referenced elsewhere rather than supplied in the email text. Preserve available reference metadata and show that those instructions must be checked; do not manufacture the student's assigned question.
- Attendance/notes-related evaluation text is supporting information unless it gives a separate included obligation. IA2 in the subject is not sufficient to classify the upload as a test.

#### E05: DBMS IA1 initial schedule

- Quiz date: **31 August 2026**; start **13:10**; end **13:30 IST**; 20-minute MCQ assessment for 20 marks, covering modules 1 and 2.
- The email was sent earlier in August. Its sent date is not the quiz date.
- Candidate: DBMS theory `test`; venue is to be announced later.
- Preserve explicit timing, relevant syllabus, and assessment format. The historical date alone must not auto-complete the test during a later import.

#### E06 and E08: duplicate DS follow-up and eligibility exceptions

- These exports contain the same message identity and selected decoded body. They represent one source message despite different filenames.
- The current 28 September section discusses marks and an exceptional re-examination situation; earlier quiz dates appear in quoted messages.
- Quoted sections distinguish diploma-entry students from transfer/lateral-entry situations and contain earlier seating/timing details.
- Do not create a new general DS quiz on 28 September from the send date or revive every quoted test as new work.
- A re-examination candidate needs review when the student's exception eligibility is unknown. Do not infer admission route from SY, semester, admission year, or account identity.
- A room update explicitly concerning another batch must not supply the reference B2 student's room. Keep applicable general guidance separate from mismatched quoted sections.

#### E07: DS IA1 schedule with image-only seating

- Quiz date: **23 September 2026**; reporting **13:35**; start **13:40 IST**; stated duration **20 minutes**, with 20 marks and listed syllabus portions.
- If an end time of 14:00 is calculated from the start and duration, label it derived rather than source-exact.
- The seating arrangement is carried as an image reference. The supplied text does not establish the student's room.
- Retain available image metadata/reference. Missing essential venue information remains reviewable under the existing attachment policy.
- Neither the image filename nor the existence of a seating image supplies trustworthy batch/room data by itself.

#### E09: B2 DS lab OST with an explicit timing discrepancy

- The automated notice identifies **B2**, DS lab OST, **13 October 2026**, **09:00–11:00 IST**, experiments 1–6, 25 marks, and 120-minute duration.
- `DS_B_ODD_26-27` supplies course/division/term context rather than a calendar date.
- Candidate: DS **lab** `test`, confirmed applicable only against the student's profile and manually added subject/context.
- The reference weekly DS lab is Tuesday **11:00–13:00**. The exam notice explicitly gives **09:00–11:00**, although it describes this as the regular timing.
- Preserve the explicit exam interval and show the discrepancy in evidence. Do not change the interval to 11:00–13:00 or modify the profile's batch to make the notice fit.
- This is an assessment announcement, not submission confirmation. It must not complete an assignment merely because it came from the primary sender.

#### E10: general DS OST details

- This mail describes the practical test, 25 marks, 120-minute duration, and general preparation/scoring requirements.
- It does not establish a personal exact date or start time; experiment requirements can vary by batch.
- It can enrich an established compatible DS lab test when identity is sufficiently clear. Otherwise request association/slot review.
- Do not apply B2-only experiment selections to every batch, derive a date from the send date, or create another test solely because a general follow-up exists.
- Inconsistent supporting scoring totals must not cause fabricated student marks or overwrite unrelated timing fields.

#### E11: DS IA2 viva and quoted Division A schedule

- The current notice gives general oral-test requirements and says individual teachers will declare schedules.
- A quoted per-student schedule and linked schedule reference concern **Division A**, including October dates and reporting times.
- For the supplied Division B context, ignore Division A-specific slots and roster rows. Do not infer a Division B date from them.
- Applicable general viva guidance can support a DS test candidate, but the missing Division B schedule remains unresolved.
- Do not retain classmates' names/roll numbers or fetch the linked roster. Unknown student-specific eligibility or dates belong in review.
- A feedback-form request is outside standalone task scope; a relevant prerequisite can remain an instruction attached to the test.

#### E12: COA IA1 thread, login time, and mixed-batch rooms

- The established quiz date is **28 September 2026**.
- An older quoted notice gives a 13:05 start. A later quoted revision gives reporting **13:35**, start **13:40**, and end **13:50 IST**.
- The newest authored section requires login by **13:30** and supplies a room table. This adds a login requirement; it does not turn 13:30 into the test start or restore the older 13:05 schedule.
- For Division B plus batch 2, the room table maps **B2 to B115A**. Select that row only; other batch rows do not make the whole message irrelevant.
- The email subject still references 13:30. A subject-line shorthand does not override the role-specific revised body details.
- Expected result: one COA theory `test`, login 13:30, reporting 13:35, start 13:40, end 13:50, venue B115A, with separate field provenance and a visible revision timeline.

### Additional email cases: completion, reminders, and quiz windows

These 10 additional files extend the catalogue to E22. The second batch's repeated DS practical-test notice is E09. They establish receipt/reminder matching patterns; they do not grant access to another system or prove live sender validation.

#### E13 and E21: EXP6 due/overdue notices

- E13 states that **EXP6-BST** in Data Structures division B, odd term 2026–27, is due **21 September 2026 at 23:59 IST**.
- Its countdown says one day to go, but the absolute `When` field provides the deadline. Use the labelled timestamp rather than adding one day to the send time.
- E21 repeats the same due date, calls the work overdue, and says late submission might still be possible. Its activity identifier matches both EXP6 confirmation receipts.
- Candidate work is an assignment, not a test merely because its title describes a data-structure exercise. Match the owned manual subject/task using established component context; course division B alone does not uniquely prove a lab or exact batch.
- If the task is incomplete, use its accepted deadline and the clock to compute due/overdue. If already completed manually or by receipt, leave it completed and suppress status-driven duplicate/reopen activity.
- “You might still be able to submit” is a generic late-upload warning. It does not establish that the existing submission was withdrawn or that a new upload is required.

#### E14 and E15: quiz close versus classroom attendance

- E14's COA quiz notice gives **28 September 2026 at 14:59 IST** as the online close. E12 separately establishes login 13:30, reporting 13:35, classroom start 13:40, and end 13:50.
- E15's Discrete Maths IA1 notice gives **1 October 2026 at 14:30 IST** as the online close. E03 separately establishes reporting 13:30, start 13:40, and end 14:00.
- Preserve these role-specific facts. A quiz's online close can differ from the physical assessment interval; it cannot overwrite `startsAt` or `endsAt` simply because the email is newer.
- Both notices contain overdue/countdown labels. Neither is an unsubmission event or completion-state authority. A completed COA/DSM task remains completed.
- Keep the established fixed-session timing mode when that test's attendance schedule is confirmed. If the identity or intended timing mode is genuinely unclear, review it without clearing accepted completion.

#### E16 and E17: two EXP6 submission confirmations for one activity

- E17 was sent **25 September 2026 at 18:01:44 IST**. E16 was sent **6 October 2026 at 10:44:34 IST**.
- Both identify EXP6-BST in the same course and use the assignment-submission confirmation wording. Their activity links point to the same assignment resource identifier.
- They have different Message-IDs and different submitted-file metadata. Treat them as two receipt events for one task, not duplicated exports or two assignments.
- After authenticated template/owner/applicability validation, either receipt can complete a suitable existing EXP6 task. The later receipt supplements evidence and never makes completed work due again.
- Both receipt messages are after the original deadline. Confirmed late submission still results in `completed`; do not preserve overdue simply because the upload was late.
- Their sent times establish receipt occurrence, not independently verified transaction timestamps. File metadata is a reference; the files are not read.
- If no suitable owned task exists, retain the unmatched receipt and retry when its exact task arrives, within the Gmail 30-day window. Do not create an unrelated completed task just from the receipt.

#### E18 and E22: ITVC confirmation and a multi-division digest

- E18 confirms the IA2 AI-Enhanced Modeling assignment and was sent **5 October 2026 at 23:56:36 IST**.
- Its breadcrumb is `ITVC_A-B-C-D_SY_ODD_26-27`: a combined A/B/C/D second-year course audience, not Division A-only work.
- E22 was sent on **2 October** and lists the same activity as due **9 October 2026 at 23:59 IST**, matching E04's submission-window close and E18's activity resource identifier.
- Punctuation, case, line wrapping, and Modeling/Modelling spelling variation are normalization inputs, not a reason to duplicate an exact linked activity. Preserve identity/term/subject checks when no exact identifier is available.
- Match only the student's applicable task. The umbrella course audience includes B, but it does not cancel an explicit different-class or different-batch qualifier on a particular activity.
- After valid confirmation, the task is completed even if the earlier digest is imported later or another digest repeats it. Parse each future digest row independently; ignore rows that clearly exclude the student's class/division/batch.
- A seven-day heading does not establish every row's deadline or status. Parse the explicit date and time on the individual activity.

#### E19: precise EXP5 deadline

- The notice says Exp 5 Doubly Linked List/Circular Linked List is due **5 October 2026 at 10:06 IST**.
- This precise time must not be rounded to an ordinary lab start or defaulted to 23:59. Store the actual source time with its basis.
- Its activity resource differs from EXP6's. Do not merge neighbouring experiments, receipts, or deadlines solely because they are both DS work.
- No EXP5 completion receipt is included in this batch. Do not apply EXP6's receipt to EXP5 or infer submission from the existence of a reminder.

#### E20: an online quiz window and the new missed status

- The ITVC IA1 quiz opens **5 September 2026 at 20:00** and closes **21:00 IST** on the same day.
- Candidate: `test`, `timingMode: attempt_window`, with distinct online opening/closing fields. The mail does not establish an individual attempt start or duration.
- The user chose **closing time** as the expiry cutoff and explicitly chose **missed as a fourth stored status**.
- Before 21:00, incomplete work remains due, including before the window opens and during 20:00–21:00. At or after 21:00, it is missed if still incomplete.
- Any accepted manual or valid matched submission completion remains completed before and after that boundary, even if later mail says overdue.
- The combined A-B-C-D audience can include Division B; perform the existing subject/class/semester/batch checks without assuming batch membership from that broad label.

Representative extracted timing fields:

```json
{
  "type": "test",
  "timingMode": "attempt_window",
  "title": "ITVC IA1 online quiz",
  "availabilityOpensAt": "2026-09-05T14:30:00Z",
  "availabilityClosesAt": "2026-09-05T15:30:00Z",
  "dueAt": "2026-09-05T15:30:00Z",
  "startsAt": null,
  "endsAt": null,
  "durationMinutes": null,
  "sourceTimezone": "Asia/Kolkata"
}
```

The example describes a reference fixture, not a currently imported task. The one-hour availability window is not a claimed one-hour individual attempt duration.

#### Actual chronology versus required regression cases

The supplied EXP6 overdue email was sent on 22 September, before the receipts on 25 September and 6 October. The ITVC digest was sent before its 5 October receipt. These files demonstrate matching activity identities and the risk of importing old notices after newer confirmation; they do not themselves prove a reminder was sent after those receipts.

The user separately reports that newer false overdue notices can also occur. Both orders must be covered by future redacted regression fixtures: replay the actual older notices after completion, and construct a clearly labelled synthetic later reminder with the same activity identity. In either order, completed remains completed. Do not describe the synthetic case as an observed live event.

### Screenshot source index

The file identifiers below refer to the supplied `codex-clipboard-<identifier>.png` files. Descriptions record visible content; they do not claim the entire course or stream was shown.

| ID | File identifier | Visible reference |
|---|---|---|
| S01 | c68f885d-015e-4878-ba79-33f962c483c6 | Semester III scheduler morning slots, week 4–10 October 2026 |
| S02 | f0065e97-3d5d-422b-9287-70b87cf90893 | Afternoon slots; basket/lab/theory/tutorial overview |
| S03 | c818f9f8-7dba-4d8b-b637-3d0c0b90abb1 | DS, DS lab, COA, and DBMS component/code overview |
| S04 | a105b7d3-348f-4f5c-9db2-067fcde97748 | DBMS and ITVC theory/tutorial overview |
| S05 | 4de07337-ef90-46b3-be27-7ef1717ecb70 | AR/VR minor course code, class code, instructor, venue, times |
| S06 | d4c09a17-b1c9-4b29-9007-bb15c1cf9655 | DBMS theory and lab; Division B, batch 2 for lab |
| S07 | 0167ba8f-9e45-4fa2-aa59-b6277a1dfab5 | COA theory, DS theory, DS lab; lab batch 2 and Tuesday 11:00–13:00 |
| S08 | 00a32095-5591-43df-9eb0-311fc9ca12c3 | Discrete Maths tutorial/theory; different class codes, instructors, slots |
| S09 | e17d42b2-4cc3-44fb-b968-df0f767c6e11 | WDL lab; Division B, batch 2, Wednesday 16:00–18:00 |
| S10 | 964ac319-2b47-48cf-8362-314d0301fb81 | ITVC tutorial/theory; distinct class codes and times |
| S11 | b63bb818-741a-4900-8746-ef8adb31e2ef | Classroom course cards with theory/lab/batch/minor naming differences |
| S12 | 35502433-f19e-4677-9a62-43babbcc9f9c | DBMS stream: grading information, viva withdrawal, and OST notices |
| S13 | ac2de719-4055-4da6-8a13-3d640eb679b1 | DBMS OST notices, UI comments, and sample paper image |
| S14 | f799ddae-9f54-49c4-a7f3-51e2fbdb2ba1 | DBMS OST week notice, experiment assignment cards, “by today” upload instruction |
| S15 | bb7556cd-2588-4c61-9215-b6ebbd0f316f | Experiment 4 write-up date revision and sample query material |
| S16 | 6592cafe-d106-4367-bd86-227ed3c7d251 | Detailed sample query/reference text |
| S17 | 4241286c-5471-4fee-b489-47c0decff386 | Separate query upload/write-up requirements, EER work, viva dates |
| S18 | ee1a48ad-e87d-4a80-a9a7-189ce1cc1ae6 | Group-detail sheet, assignment cards, reference materials/rubrics |
| S19 | 4de11dce-5841-41c4-8208-5b54b17a46d4 | Experiment 8, due 11 October, Assigned state, material metadata |
| S20 | dcd1be88-bb35-4844-bfb6-2135bf2f7920 | AR/VR SY-all course; IA2 series, reference video, no-work-due-soon text |
| S21 | 755e7384-46ba-4da5-a162-3e3bfd9b9011 | Distinct numbered IA2 coursework: code, resume, numerical, question bank, write-up |
| S22 | 56e1e4e4-98d1-4beb-9cee-2360bbafff12 | IA2.14 due 1 October 23:59; Turned in with Unsubmit control |
| S23 | 192838f0-e202-4738-9975-525beab3f3d1 | WPL alias, group presentation upload, tentative presentation dates/times |

### Classroom and schedule cases demonstrated by screenshots

#### Stream notices can create or update included work

The DBMS stream references an OST during the regular lab in the week of **5 October**, followed by a more specific **5 October** notice. Preserve the later specificity for the same established test. A valid student-entered DBMS lab slot can establish the Monday 14:00–16:00 session window. Because “during the lab” alone does not specify the exact test start within that window, retain the precise start in review unless clarified. A UI typo in the notice is not authority to infer a new scheduling rule.

The same stream contains upload instructions with “today” and “before the next lab.” Resolve “today” against that post's publication date, not the day the student connects DueCare. A reference to the next lab needs established schedule context; with multiple or missing slots, review is required.

A later announcement says the experiment viva will not be conducted. That is a withdrawal candidate for an existing relevant viva, handled through review and the existing deletion/suppression action. The announcement's unrelated personal explanation must not be retained in task instructions or sent to AI.

#### Separate deliverables within an experiment

The Experiment 4 examples distinguish query demonstration/uploads from the written report:

- The 31 August notice sets **6 September 2026** for the query-upload work and says the write-up can come later.
- The 5 September notice specifies the write-up on or before the **7 September lab**.
- Preserve two independently required deliverables when that distinction is confirmed. Link them through assessment/source metadata rather than merging their deadlines.
- “By the lab” does not prove whether the cutoff is at the beginning or end of the session. Preserve the phrase and request the missing cutoff rather than selecting 14:00 or 16:00 silently.
- A receipt for the query upload does not complete the final write-up or associated viva.

The Experiment 1 example contains EER diagram/write-up work and a separate viva, using numeric dates **9/8/26** and **10/8/26** in an August post. The Indian convention and nearby chronology support 9 and 10 August; retain that interpretation basis. If production text lacks this context, do not assume the dates mean September and October or choose one interpretation without review.

#### Reference material and template text

Long lists of sample SQL questions are supporting content for the established experiment, not a separate task for each query. A sample OST paper can show a semester different from the current enrolment because it is a template. Reference-only paper headings cannot override the student's semester or turn an otherwise applicable announcement into a mismatch.

The group-details spreadsheet request and general reference materials/rubrics do not create standalone tasks under current scope. Material metadata may be linked to the related assessment. Exact instructions hidden in the document, image, or a UI-only comment remain unavailable to this import design.

#### Actual assignment state and provider timestamps

Experiment 8 is titled TCL and DCL commands, carries 25 points, and is displayed as due **11 October** with an **Assigned** state. Preserve the actual API deadline once fetched; the screenshot's abbreviated date does not prove that 23:59 IST should be used. Its material filename is metadata, not submission evidence.

IA2.14 shows **Turned in** and a deadline of **1 October at 23:59**, with an Unsubmit control and an attached PDF. In a future live fixture, the connected student's matching `TURNED_IN` evidence completes that specific task, even when the deadline has passed. An attached PDF without turn-in would not suffice. A later explicit unsubmission can reopen the same task under the reconciliation rules.

An edited assignment card is still one coursework item. Publication, last edit, deadline, submission, and withdrawal timestamps must stay distinct. Points shown on the coursework do not establish earned marks or completion.

#### Numbered IA2 items and generic titles

The AR/VR course contains IA2.1 through later IA2 items with differing work: FOV/PPD calculations, headset write-up, question bank, numerical work, C# programs, resume, and MCQ-labelled work. These are separate provider items; do not merge the entire series into one IA2 task.

The course context can establish that a generic title such as Resume is academic assignment work in an explicitly mapped subject. Title-only keyword filters would miss it. Conversely, a reference video in the same course is not automatically an assignment. A home/stream message that no work is due soon does not complete undated or previously outstanding coursework.

#### WDL/WPL group presentation and conflicting time references

The WDL subject appears under a WPL Classroom label. Retain an explicit confirmed alias rather than auto-creating another subject.

The presentation guideline is tentative for **23 or 30 September 2026**, and references **14:00–16:00** lab hours. The supplied enrolment card instead places WDL on Wednesday **16:00–18:00**. Keep both observations and the discrepancy in review; do not choose a presentation date or substitute the weekly time for the notice.

The upload card requests one person per group, but its title is truncated in the screenshot. Do not reconstruct the hidden text. Preserve the group instruction only to the extent actually visible or subsequently returned by the API. No classmate-upload check or automatic group-wide completion is implied.

### Redacted fixture expectations

| Fixture | Expected outcome |
|---|---|
| E01 ESE window | Applicable WDL test proposal; range retained; individual slot unresolved; no fabricated `dueAt` |
| E02 lecture-week IA2 | DBMS theory test; 19–23 October window; no chosen lecture date |
| E03 revised quiz | One test updated to 1 October; reporting/start/end distinct; prior date retained only as history |
| E04 modelling upload | Assignment with opening/closing window; hidden allotted questions not fabricated |
| E05 initial DBMS IA1 | Test on 31 August; sent date excluded from deadline; missing venue stays unknown |
| E06/E08 duplicate | One source occurrence processed; no duplicate follow-up task/activity |
| E07 image-only seating | Correct quiz timing; derived end labelled; no inferred room or OCR operation |
| E09 versus S07 | B2 DS lab test at explicit 09:00–11:00; 11:00–13:00 reference discrepancy visible |
| E10 general OST | Safe enrichment or association review; no invented slot or cross-batch syllabus |
| E11 Division A roster | Division A-specific rows ignored for B; relevant general viva guidance kept; B schedule unresolved |
| E12 COA thread/table | Correct current login, revised reporting/start/end, and B2 room B115A; one task |
| S08/S10 tutorial context | Separate manually added tutorial subjects preserve different class codes/instructors/times despite shared course codes |
| S12 withdrawn viva | Review proposal using existing deletion/suppression; no automatic completed state or fourth status |
| S14 relative “today” | Resolve against post date; no deadline equal to sync date |
| S15/S17 deliverables | Query upload and write-up kept independent when established; valid timetable context supplied, but unspecified start-versus-end lab cutoff reviewed |
| S16/S18 references | No new task per sample question, rubric, reference video, or standalone group-details form |
| S19 Assigned | Incomplete task; no completion from material/points/Mark as done button |
| S20/S21 IA2 numbering | Distinct coursework IDs; labels are not dates; generic academic titles recognized in mapped context |
| S22 Turned in | Matching own-submission completion; later unsubmission tested separately |
| S23 tentative presentation | Two alternatives and time discrepancy reviewed; no group-wide completion assumption |
| Any blocked sender | No body processing, AI request, tasks, reviews, completion, or activity from that sender |
| Same notice for another batch | Explicit mismatch ignored before detailed extraction; general profile batch unchanged |
| Old source replay after manual edit | Manual correction preserved; imported chronology cannot roll it back |
| Candidate receipt templates | EXP6 and ITVC confirmation formats specified from actual exports; automatic completion enablement still requires live template/authentication/ownership/association validation |
| E13/E21 then E17/E16 | One EXP6 task completes from validated receipt evidence, even after its deadline; two distinct receipt events, no duplicated task |
| E21 replayed after EXP6 completion | Remains completed; no reopen, overdue duplicate, missed status, or status-conflict review |
| Synthetic later EXP6 reminder | Same completed outcome even when reminder source time is newer; explicitly label this test as synthetic |
| Manual completion followed by reminder | Remains completed for both assignment and test; clock/label does not clear the user's decision |
| E18 and E22 activity matching | One ITVC task; digest/reminder cannot reverse confirmation; exact links support association without visiting them |
| E14/E15 with E12/E03 | Availability close stays separate from classroom attendance timing; accepted completion preserved |
| E19 versus EXP6 receipts | Precise 10:06 deadline retained; different activity IDs stay separate; EXP6 receipt does not complete EXP5 |
| E20 at 20:59:59 / 21:00 IST | Incomplete test is due before close and missed at close; completed test remains completed at both times |
| Broad A-B-C-D audience plus B2 profile | Division B is included; no rewrite of division or global batch; unresolved batch still uses confirmed context or review |
| Synthetic broad course with B1-only activity | Explicit B1 qualifier excludes B2; ignore the activity despite the familiar sender or broad course audience |
| Mixed-cohort digest | Process applicable rows individually; ignore explicit other-class/batch rows; ambiguous rows reviewed, no cross-row completion |
| Stored status validity | Database/API supports missed as a distinct fourth value; assignment-missed and test-overdue combinations rejected; effective status refreshed without scheduled work |

### Confirmed additions and evidence still needed

The user confirmed the following product decisions raised by the supplied materials:

1. **Manual weekly timetable context in the first web release:** optional slots per manually added subject, used with provenance and ambiguity checks; no recurring task generation.
2. **Separate manual tutorial subjects:** subject kinds are theory/lab/tutorial, all inheriting the same general student batch. Task types remain assignment/test.
3. **Online quiz expiry at closing:** opening/closing bounds remain separate; a window-only quiz expires when it closes, not when it opens.
4. **Fourth status `missed`:** explicitly confirmed as a database/API status for expired incomplete tests, replacing the earlier three-status decision; assignments retain overdue. Confirmed completion is protected against reminder mail.

Evidence gaps are validation work, not assumptions to fill:

- Live validation of the supplied assignment-submission-confirmation formats, plus separate test-submission, withdrawal, and resubmission email examples for the college notification sender.
- Live Classroom coursework and own-submission responses confirming deadline timezone conversion and state/history behavior under the approved scopes.
- Individual exam slots/venues for notices that announce only a window or another division's schedule.
- Student confirmation of ambiguous aliases, exceptional eligibility, and conflicts that source evidence cannot settle.

Resolving these gaps must preserve Gmail/Classroom sources, manually added subjects, the single batch, the latest four-status decision, complete sender blocking, and mobile planning after web acceptance.

### Source policy update (9 October 2026)

Source-to-source date/detail disagreements are settled using source publication/edit timestamps, including Classroom updateTime. Equal timestamps use a stable source identity tie-break. Manual field edits and completion authority remain protected. Own Classroom TURNED_IN states complete matching tasks automatically; newer verified unsubmission retains its existing reopening behavior. Recruitment, council/club, placement, internship, hackathon and promotional community mail is excluded before extraction. Existing source conflicts and completion evidence can be reconciled from saved evidence without new AI requests; uncertain eligibility remains in Needs attention. Missing, unclear or inconsistent dates/times are kept as normal undated tasks and do not create timing reviews.

### Undated-task policy (9 October 2026)

A missing, unclear, tentative or internally inconsistent imported deadline/date/time never blocks creation of an otherwise applicable assignment or test. Keep it in Tasks with timingMode=undated and no accepted date, date window or clock times. Existing timing-only reviews are resolved into normal tasks using saved source evidence, retaining ownership checks, sender blocks, deleted-import suppression, manual field edits and completion state. Genuine eligibility and association questions remain eligible for Needs attention. Clear later source timing or a manual edit can supply the schedule.
