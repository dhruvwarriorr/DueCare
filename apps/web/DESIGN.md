---
name: DueCare
description: The student's week on one ruled sheet, with every deadline coloured by its status.
colors:
  ink: "#c21c58"
  ink-line: "#d4668b"
  ink-rule: "#efc3d2"
  ink-tint: "#fbe4ec"
  ink-wash: "#fdf3f7"
  graphite: "#18171b"
  graphite-2: "#5d4a53"
  paper: "#f4f5f8"
  sheet: "#ffffff"
  good: "#1d7440"
  good-tint: "#e5f5ea"
  due: "#f5c400"
  due-line: "#d9ad00"
  due-tint: "#fff6d6"
  due-text: "#7a5800"
  on-due: "#2b2100"
  bad: "#c8261e"
  bad-tint: "#fde8e5"
  bad-text: "#b4231b"
  band: "#18171b"
  ink-dark: "#ff6f9c"
  ink-line-dark: "#b94e76"
  ink-rule-dark: "#3f2430"
  ink-tint-dark: "#33202a"
  ink-wash-dark: "#221b21"
  graphite-dark: "#efeaec"
  graphite-2-dark: "#b8a7af"
  paper-dark: "#121014"
  sheet-dark: "#1a171c"
  on-dark: "#141216"
  good-dark: "#4fc37f"
  good-tint-dark: "#15301f"
  due-dark: "#f5c518"
  due-line-dark: "#c9a10f"
  due-tint-dark: "#33290a"
  due-text-dark: "#f5c84b"
  bad-dark: "#ff6b5e"
  bad-tint-dark: "#3a1715"
  bad-text-dark: "#ff7b70"
  band-dark: "#2b262d"
typography:
  display:
    fontFamily: "Sofia Sans Condensed, Arial Narrow, sans-serif"
    fontSize: "clamp(36px, 4vw, 48px)"
    fontWeight: 800
    lineHeight: 0.95
    letterSpacing: "-0.015em"
  display-cover:
    fontFamily: "Sofia Sans Condensed, Arial Narrow, sans-serif"
    fontSize: "clamp(44px, 5.4vw, 84px)"
    fontWeight: 800
    lineHeight: 0.92
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Sofia Sans Condensed, Arial Narrow, sans-serif"
    fontSize: "34px"
    fontWeight: 800
    lineHeight: 1.05
  title:
    fontFamily: "Sofia Sans Condensed, Arial Narrow, sans-serif"
    fontSize: "26px"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.005em"
  subtitle:
    fontFamily: "Sofia Sans, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 650
    lineHeight: 1.3
  body:
    fontFamily: "Sofia Sans, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  numeral:
    fontFamily: "Sofia Sans Condensed, Arial Narrow, sans-serif"
    fontSize: "22px"
    fontWeight: 800
    lineHeight: 1
    fontFeature: "\"tnum\" 1"
  label:
    fontFamily: "Sofia Sans Condensed, Arial Narrow, sans-serif"
    fontSize: "11.5px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.09em"
rounded:
  none: "0px"
  bubble: "50%"
spacing:
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  gutter: "36px"
components:
  button-primary:
    backgroundColor: "{colors.graphite}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.none}"
    padding: "0 18px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
  button-outline:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.none}"
    padding: "0 18px"
    height: "44px"
  button-outline-hover:
    backgroundColor: "{colors.ink-wash}"
    textColor: "{colors.ink}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.graphite}"
    rounded: "{rounded.none}"
  button-ghost-hover:
    backgroundColor: "{colors.ink-wash}"
    textColor: "{colors.ink}"
  button-destructive:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.none}"
    padding: "0 18px"
    height: "44px"
  button-destructive-hover:
    backgroundColor: "{colors.graphite}"
    textColor: "{colors.sheet}"
  input:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.none}"
    padding: "10px 12px"
    height: "44px"
  bubble:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.bubble}"
    width: "20px"
    height: "13px"
  bubble-filled:
    backgroundColor: "{colors.graphite}"
  status-due:
    backgroundColor: "{colors.due}"
    textColor: "{colors.on-due}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0 10px"
    height: "26px"
  status-completed:
    backgroundColor: "{colors.good}"
    textColor: "{colors.sheet}"
  status-overdue:
    backgroundColor: "{colors.bad}"
    textColor: "{colors.sheet}"
  status-missed:
    backgroundColor: "{colors.bad-tint}"
    textColor: "{colors.bad-text}"
  due-item:
    backgroundColor: "{colors.due-tint}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.none}"
    padding: "6px 7px"
  due-item-completed:
    backgroundColor: "{colors.good-tint}"
  due-item-overdue:
    backgroundColor: "{colors.bad}"
    textColor: "{colors.sheet}"
  due-item-missed:
    backgroundColor: "{colors.bad-tint}"
  summary-chip:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.none}"
    padding: "0 12px 0 4px"
    height: "36px"
  next-band:
    backgroundColor: "{colors.band}"
    textColor: "{colors.sheet}"
    padding: "12px 36px"
  nav-tab:
    textColor: "{colors.graphite}"
    padding: "0 16px"
    height: "64px"
  panel:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.none}"
    padding: "18px 20px"
---

# Design System: DueCare

## Overview

**Creative North Star: "The Answer Sheet"**

DueCare is still drawn like a printed answer sheet: white stock, ruled lines, condensed printed labels and square boxes. Rose drop-out ink prints the structure the institution owns (field and column labels, timetable slot outlines, hour rules, the now line). Graphite carries the student's text and actions. On top of those two inks sits one more layer the owner asked for directly: status colour. Completed is green, due is yellow, overdue is solid red, and missed is red tint with the title struck through. That colour appears only where a deadline's state is shown, so a glance at the week answers "what's done, what's due, what's late".

The interface is meant to be simple to move around. One header row holds the wordmark, five plain text tabs, the bell, Add task and the account button. The week sheet reads top to bottom: day heads, a "Due" row listing each day's deadlines in plain words, then a timeline of classes with the now line. There are no shadows and no rounded rectangles. Depth comes from 1px rules and solid fills.

Dark mode is a carbon sheet. The paper turns near-black, rose brightens to #ff6f9c, graphite becomes the light ink, and each status colour has its own dark value. The next-due band stays a dark strip (#2b262d) in both modes.

**Key Characteristics:**
- Rose prints structure, graphite carries text and action, and green, yellow and red show status only.
- One-row header with plain text tabs and a 4px graphite underline on the active tab.
- Square corners everywhere. The oval bubble is the only curve.
- No shadows. Depth comes from 1px rules and solid fills.
- Condensed face for labels and numerals, Sofia Sans for reading, tabular numerals for every time and count.

## Colors

The palette is white stock, one rose ink in five densities, graphite in two weights, and three status colours.

### Primary
- **Drop-out Rose** (ink): the printed ink. It's used for caps labels, the "Due" row label, day names, input carets, select chevrons, the now line and its time tab, hover text on outline and ghost buttons, the logo's bubble and pencil fill, and destructive buttons. In dark mode it becomes **Lit Rose**.
- **Rose Line** (ink-line): stroke for inputs, panels, the task list frame, and timetable slot outlines.
- **Rose Rule** (ink-rule): hairline column, row and divider rules, the hour grid, the rail's hour ticks, and the hover underline on idle nav tabs.
- **Rose Tint** (ink-tint): the lab-slot fill, avatar ground, selection highlight and the hatch stroke.
- **Rose Wash** (ink-wash): hover grounds, the today column in the timeline, and the "without a date" count box.

### Secondary
- **Graphite** (graphite): body text, primary buttons, the active tab underline, the today day head fill, selected segmented and settings tabs, the review count box, and the 1px frame around the week sheet, dialogs and header. In dark mode it becomes **Chalk**.
- **Soft Graphite** (graphite-2): secondary text, meta lines, hour labels and placeholders.
- **Night Band** (band): the ground of the next-due band. In dark mode it is #2b262d, so the band stays dark.

### Tertiary (status)
- **Done Green** (good, with good-tint): completed. Solid green for the "done" pill, the bubble on a completed due item, mobile day ticks and the sign-in check icons. The tint is the completed due item and month chip ground.
- **Due Yellow** (due, due-line, due-tint, due-text, on-due): due. Solid yellow for the status pill, the "due" summary count, the "Next due" label and the bubble on a due item. Due Line strokes due items and chips, Due Tint fills them, Due Text sets the priority flag (HIGH, CRITICAL), and On-Due is the dark text on solid yellow.
- **Late Red** (bad, bad-tint, bad-text): overdue and missed. Solid red with white text is overdue (pill, due item, month chip, overdue and missed counts, the review badge in nav and the bottom bar). Red Tint with a red stroke, Red Text and a strike-through is missed.

### Neutral
- **Cool Paper** (paper): the page ground behind sheets, and the sign-in form side.
- **Sheet White** (sheet): every working surface: the sheet, panels, inputs, header, dialogs and empty bubbles.

### Named Rules
**The Status Colour Rule.** Completed is green, due is yellow, overdue is solid red, missed is red tint with strike-through (owner commitment). These colours appear wherever a deadline's state is shown (status pills, due items, month chips, summary counts, day ticks, review badges) and nowhere else. They are never used for structure, decoration or buttons.

**The Two-Ink Rule.** Outside status, a fill is sheet, a rose density, or graphite. Rose prints structure and graphite carries text and action. No neutral grey surface exists.

**The Hatch Rule.** Anything waiting for the student's review, and any day outside the current month, takes the diagonal "do not write" hatch (-45deg, Rose Tint 2px every 7px). This covers the attention banner, import rows that need a fix, and outside days in the month view.

## Typography

**Display Font:** Sofia Sans Condensed (with Arial Narrow, sans-serif)
**Body Font:** Sofia Sans (with system-ui, sans-serif)

**Character:** The condensed cut is the printer's face for headings, labels and every numeral. The regular cut is the reading voice. Both load through next/font as `--font-condensed` and `--font-body`.

### Hierarchy
- **Display** (800, clamp(36px, 4vw, 48px), 0.95): the week title ("This week"), with the date range under it in 15px Sofia Sans. The sign-in cover uses Display Cover (clamp(44px, 5.4vw, 84px), 0.92) with the key words in rose.
- **Headline** (800 condensed, 34px, 1.05): page section bars such as "All tasks". Intro pages use 40px.
- **Title** (700 condensed, 26px, 1.15): the default h2 and dialog titles. Panel headings use 22px.
- **Subtitle** (650 Sofia Sans, 17px, 1.3): the h3 inside panels and subject cards.
- **Body** (400, 15px, 1.55): reading text, nav tabs (500, active 700) and task titles (600). Secondary text runs at 13 to 14px in Soft Graphite. Due-item titles are 12.5px at 600.
- **Numeral** (800 condensed, tabular): day numbers (22px), the countdown (22px), summary counts (16px) and task dates (650, 15px).
- **Label** (700 condensed, 11.5px, 0.09em, uppercase): printed labels such as day names, the "Due" row label, field labels and status pills (12px, 0.07em). The range is 10 to 12px.

### Named Rules
**The Printed Caps Rule.** Uppercase condensed caps are reserved for labels the sheet itself would print: a field name, a day name, a row label, a status, or a priority flag. They label data that sits right next to them. They never sit above a heading as a decorative eyebrow.

**The Tabular Rule.** Every time, date and count uses `tabular-nums`.

## Layout

The page is a sticky 64px header, then the next-due band on the week view, then content inside a 1480px column with a 36px side gutter and 96px of bottom padding. The header is one row: wordmark, five text tabs (Week, Tasks, Review, Subjects, Settings), then the bell, Add task, and the avatar button that opens a 260px account menu. There is no second tab row. Settings splits into in-page tabs (Profile & privacy, Sources, Rules) at every size.

The week sheet is a 56px rail plus seven equal day columns. The day head row comes first (today in solid graphite), then the "Due" row, closed by a 1px graphite rule, then the class timeline at 58px per hour with the rose now line. Under the week title sits one row of summary count chips; only "due" and non-zero counts appear.

At 860px and below the tabs and Add task leave the header. A fixed bottom bar (Week, Tasks, a graphite add button, Review, More) and a 300px slide-in drawer of plain nav rows take over. The week becomes a seven-day strip with coloured status ticks under each date, then a day agenda: Due items, then Classes. Every interactive target is at least 44px tall (42px inside segmented groups).

The spacing rhythm runs 8 / 12 / 16 / 18 / 24 / 32, and 36px is the page gutter. Grids of boxed cells share collapsed borders.

## Elevation & Depth

The system is flat. Depth comes from rule weight and fill. Frames are 1px graphite or Rose Line, internal divisions are 1px Rose Rule, and the heaviest objects (primary buttons, the today day head, the next-due band, solid status fills) are solid. Dialogs separate from the page with a graphite scrim (rgb(24 23 27 / 0.55)) and a 6px graphite top rule. The account menu is a 1px graphite frame on sheet. Sticky layers sit on opaque grounds.

### Named Rules
**The No-Shadow Rule.** `box-shadow` and `text-shadow` are banned (owner commitment). If something needs to lift, give it a heavier rule or a solid fill instead.

## Shapes

Every rectangle is square (0px): buttons, inputs, pills, chips, due items, panels, dialogs, drawers, menus and the avatar. The only curve is the oval bubble, a 50% radius on a wide ellipse (20 x 13px base, 14 x 10 on due items). It appears in the logo (as a stadium bubble), filter rows, radios, OMR fields and due items. Checkboxes are square. Dashed outlines mean a tutorial slot. Strike-through means missed.

**The One Curve Rule.** Rounded corners are banned (owner commitment). Only the bubble curves. It is either empty with a rose stroke, filled graphite for a selection, or filled with the item's status colour on a due item.

## Components

### Buttons
Buttons are square, compact and decisive.
- **Shape:** square (0px), 1px border, weight 600, 14px. The md size is 44px tall with 18px side padding. The sm size is 34px tall. The icon size is 44 x 44.
- **Primary:** graphite ground with white text. On hover it turns rose. Transitions run 160ms cubic-bezier(0.16, 1, 0.3, 1).
- **Outline:** sheet ground with a graphite border. On hover the ground becomes Rose Wash and the border and text turn rose.
- **Ghost:** transparent. On hover the ground becomes Rose Wash and the text turns rose.
- **Destructive:** rose ground. On hover it turns graphite.
- **Focus:** a 2px graphite outline at 2px offset across the system. Disabled buttons drop to 50% opacity.

### Status Pills
- A 26px square pill in condensed caps (12px, 0.07em), 10px side padding. Due is solid yellow with On-Due text. Completed reads "done" on solid green. Overdue is solid red with white text. Missed is Red Tint with a red stroke, Red Text and strike-through.

### Due Items (signature)
- The unit of the week's "Due" row and the mobile agenda. A square box with a 1px stroke, a 14 x 10 bubble, the title (12.5px, 600, up to three lines) and a meta line "time · status word" at 11.5px.
- **Due:** Due Tint ground, Due Line stroke, yellow bubble. **Completed:** Green Tint, green stroke and bubble, green "done". **Overdue:** solid red, white text. **Missed:** Red Tint, red stroke, title struck through in red.
- Hover changes the stroke to graphite. Month-view chips use the same four treatments on a single 11.5px line.

### Summary Counts
- A row of 36px square chips on sheet with a Rose Rule border (graphite on hover). Each holds a boxed condensed count and a plain word. The "due" count is yellow, overdue and missed counts are red, review is graphite, and anything else is Rose Wash. Only "due" and non-zero counts are shown.

### Cards / Containers
- **Corner Style:** square (0px).
- **Background:** sheet white on Cool Paper.
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** the week sheet, dialogs and account menu have a 1px graphite frame. Panels, the task list and subject cards have a 1px Rose Line frame. Inner dividers are 1px Rose Rule.
- **Internal Padding:** 18 to 20px in panels, 28px in form panels, 22 to 24px in dialog bodies.

### Task Rows
- A three-column row: the title (15px, 600) with an optional Due Text priority flag for high or critical due tasks, a subline "Assignment · Subject · from Gmail" in Soft Graphite, the date in condensed tabular numerals (with "Date only · due by 23:59" when needed), and the status pill. Completed titles drop to Soft Graphite and missed titles are struck through in red. Hover gives a Rose Wash ground.

### Inputs / Fields
- **Style:** sheet ground, 1px Rose Line stroke, square, 44px minimum height, 10 x 12px padding, rose caret.
- **Select menus:** native `<select>` styled with `appearance: base-select` where supported (Chromium); other browsers keep the styled native control. A rose chevron turns over 260ms when open and the field border goes graphite. The popup is a square sheet framed 1px graphite with a 4px graphite top rule, max 360px tall. Each option is a 40px ruled row with a bubble: empty rose for choices, filled graphite for the current one; hover gives Rose Wash. Disabled placeholder options show no bubble.
- **Hover / Focus:** hover turns the border rose. Focus turns it graphite and adds a 2px graphite outline.
- **Labels:** printed caps (condensed 700, 12px, rose) above the field.
- **OMR field and filter rows:** a choice set drawn as ruled cells, each with a bubble and a caption. The checked cell fills its bubble graphite.
- **Error:** a 1px rose frame on Rose Wash, with rose inline text at 13px and weight 600.

### Navigation
- **Desktop:** five plain text tabs in the header (15px, 500, active 700, 16px side padding). The active tab carries a 4px graphite underline on the header's bottom rule. An idle tab shows a Rose Rule underline on hover. The bell carries a small count box. The avatar button opens a framed menu with name, email, academic line, the IST note and Sign out.
- **Segmented and settings tabs:** framed in 1px graphite with Rose Rule dividers. The selected option fills graphite with light text.
- **Mobile (860px and below):** a fixed 60px bottom bar with a 4px graphite bar over the active item and a graphite add button in the middle. The review count is a red box. "More" opens a 300px drawer of 48px nav rows with a scrim (280ms).

### Next-Due Band (signature)
A single-message strip pinned under the header on the week view. Night Band ground, a solid yellow "Next due" label with On-Due text, the title in Sofia Sans 650 / 16px, meta at 80% opacity, and a condensed 22px countdown on the right. It always shows exactly one item, or "Nothing due. You're all caught up."

### Disclosures
`<summary>` rows (for example "View change details", "More filters") use a drawn 7px rose chevron that turns from pointing right to pointing down over 260ms, a 36px hit area with Rose Wash on hover, and contents that unfold with an animated height (300ms) where `::details-content` is supported.

### Logo
The mark is an answer bubble with a printed D, half filled in rose the way a student marks an answer: a rose stadium outline (the sheet's bubble), a slanted pencil fill over its left half, and a D that prints in graphite on the empty side and in the sheet colour through the fill. The wordmark "DueCare" is Sofia Sans Condensed 800 at 25px, 9px from the mark. The component (`src/components/ui/logo.tsx`) draws with the ink, graphite and sheet tokens, so it follows dark mode. On hover the pencil fill eases 5 units further across the bubble. The favicon (`src/app/icon.svg`) is the mark in white and rose on a graphite rounded square, matching the Android launcher icon; both come from the same 100-unit geometry as `apps/mobile/tool/mark.py`.

### Dialogs and Drawer
A centered sheet up to 700px wide, framed in 1px graphite with a 6px graphite top rule. It rises 14px over 260ms. The right drawer is up to 460px wide and slides in 40px over 300ms. Footers are sticky with a graphite top rule.

## Do's and Don'ts

### Do:
- **Do** colour every deadline state the same way everywhere: green completed, yellow due, solid red overdue, red tint with strike-through missed (the Status Colour Rule).
- **Do** keep every non-status surface sheet white, a rose density, or graphite.
- **Do** use 1px Rose Rule for internal divisions and 1px graphite for the outer frame of a working sheet.
- **Do** write state in plain words next to its colour ("done", "overdue", "missed"), so colour is never the only signal.
- **Do** set every time, date and count in Sofia Sans Condensed with tabular numerals.
- **Do** mark review-pending items with the -45deg Rose Tint hatch.
- **Do** keep targets at 44px or taller and the focus outline at 2px graphite.
- **Do** use the house easing cubic-bezier(0.16, 1, 0.3, 1) at 160 to 300ms, and drop all motion under prefers-reduced-motion.

### Don't:
- **Don't** use drop shadows or text shadows anywhere (owner commitment).
- **Don't** round corners. Radius is 0 everywhere except the oval bubble (owner commitment).
- **Don't** use green, yellow or red for anything that isn't a deadline's state: no coloured buttons, headers or decoration.
- **Don't** introduce neutral grey surfaces or hues beyond rose, graphite and the three status colours.
- **Don't** put caps above a heading as a decorative eyebrow. Printed caps label data, not sections.
- **Don't** add a second navigation row or boxed header fields. The header is one row.
- **Don't** build the sidebar + KPI-card + chart dashboard. Information sits on the sheet, in ruled boxes.
