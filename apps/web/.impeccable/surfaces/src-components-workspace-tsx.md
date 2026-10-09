---
version: 1
slug: "src-components-workspace-tsx"
primary_target: "src/components/workspace.tsx"
related_targets: ["src/components/sign-in.tsx","src/app/globals.css"]
---

# Surface: DueCare web app (whole app revamp)

Scope: full redesign of the authenticated workspace (shell, Week home, Tasks, Review, Subjects, Settings incl. Sources/Rules/Privacy, Activity tray, dialogs, timetable import) plus sign-in and deletion pages. Mode: Operate.

Audience/job: KJSSE BTech students, phone between lectures and laptop for planning, equally. Home answers "my week, mapped". Nav may be restructured; every feature stays reachable. Owner constraints: no shadows, no heavily rounded corners; avoid gamified, childish, ERP/admin, dark-first neon.

## Direction contract

THESIS: The week as a machine-read OMR answer sheet. The timetable and all structure are printed in drop-out rose ink; only what the student has done or must do is marked in graphite. Refuses the sidebar + KPI-cards + chart edtech dashboard.

OWN-WORLD: Cool white stock (#F6F7F9 paper, #FFF sheet), rose drop-out ink (#C21C58) for rules, printed caps labels, slot outlines and bubbles, rose tint fills, graphite (#18171B) for text and marks. Two-ink rule: no neutral grey surfaces. Square corners everywhere; oval bubbles are the only curves. Black timing-mark rails, boxed candidate fields, hatched "do not write" fills for needs-review. Sofia Sans body, Sofia Sans Condensed printed caps and numerals. No shadows; depth by rules and ink density. Dark = carbon sheet.

STORY: Student opens DueCare, sees this week's classes and every cutoff on one sheet, the next cutoff pinned above, and what needs review. They open a mark, complete or review it, move on.

FIRST VIEWPORT: Sticky single-message next-cutoff band at top. Below: week title (Week NN, date range) with prev/today/next and Week/Month switch, a boxed tally strip (due, overdue, missed, undated, to review). Then the week sheet: timing-mark rail + hour labels on the left, seven day columns with ink-outlined class slots, numbered graphite deadline marks at their time, a "by 23:59" row. Right column: numbered cutoff list matching the marks. Add task in masthead.

FORM: OMR answer sheet, candidate 6 of my grounded list; seed key f2674b83. Raises: two-ink rule (Data-sublime field); single-message sticky next-cutoff band (Airport wayfinding); deadlines numbered layer over fixed timetable (Orienteering map); focused day column fades the rest (Streaming wall); thumb bottom bar + 44px targets on phones (Warm consumer app). Signature interaction: the scan, a scanner line sweeping the sheet along the timing rail on load/refresh while marks register; bubbles fill on state change.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
