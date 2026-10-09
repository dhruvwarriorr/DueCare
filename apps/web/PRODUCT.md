# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

KJSSE (Somaiya) BTech students signed in with a verified `@somaiya.edu` Google account. They juggle theory, lab, and tutorial subjects across a weekly timetable, with assignments and tests arriving through Gmail, Google Classroom, and word of mouth. They open DueCare equally on a phone between lectures and on a laptop for planning; both are first-class.

## Product Purpose

DueCare keeps every assignment and test in one place. It reads Gmail and Classroom (read-only), interprets messages into tasks, reconciles completion from submission evidence, and asks the student only when something is ambiguous. Success: a student never misses a cutoff and never has to hunt through inboxes to know what is due.

## Positioning

Not a to-do list and not a college portal. DueCare is anchored to the student's own academic identity (branch, year, division, batch, timetable) and uses it to decide which messages apply to them, with evidence and change history behind every task.

## Operating Context

- Home answers "my week, mapped": this week's classes and deadlines laid out together on time.
- Tasks are assignments or tests; statuses due, completed, overdue (assignments), missed (tests). All times are IST; date-only assignments close at 23:59 IST.
- Imported items that cannot be settled automatically land in Needs attention for student review.
- Timetables are typed or uploaded (image/PDF) and reviewed against the original.
- Activity records changes and sync issues; Settings holds profile, KT preference, privacy operations, and account deletion.

## Capabilities and Constraints

- Next.js web app, localhost-only scope for now; native mobile is future scope.
- Theme preference: system, light, dark (stored on the profile).
- Navigation may be restructured freely as long as every feature stays reachable (confirmed by the student owner).
- Branch codes: COMPS, IT, AIDS, CSBS, VLSI, CCE, EXTC, EXCP, MECH, RAI, CIVIL. Class/year: FY, SY, TY, LY.

## Brand Commitments

- Name: DueCare.
- Binding visual constraints from the owner: no drop shadows, no heavily rounded corners.
- Must not feel gamified (streaks, badges, confetti), childish/cartoon, like a corporate admin/ERP portal, or dark-first neon.

## Evidence on Hand

Real academic reference material lives in `docs/reference-files` (emails, Classroom screenshots, timetables). No testimonials, metrics, or adoption figures exist; do not invent them.

## Product Principles

1. Time is the organizing axis: work is shown against the week it lives in.
2. Evidence over assertion: every imported task can show where it came from and what changed.
3. Ask only when unsure: automation settles what it can; the student decides the rest.
4. Calm under load: dense information, never noisy.

## Accessibility & Inclusion

Keyboard reachable throughout, visible focus, WCAG AA contrast in both themes, reduced-motion respected.
