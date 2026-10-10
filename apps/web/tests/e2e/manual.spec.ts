import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
test("manual workspace persists onboarding, subjects, timetable, tasks, completion, calendar, and deletes", async ({
  page,
  context,
}) => {
  const { handle } = JSON.parse(
    readFileSync(resolve("../../.local/e2e-account.json"), "utf8"),
  );
  await context.addCookies([
    {
      name: "duecare-session",
      value: handle,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await page.goto("/");
  for (const label of [
    "Institution",
    "Programme",
    "Department",
    "Admission year",
    "General batch",
  ])
    await expect(page.getByLabel(label, { exact: true })).toHaveCount(0);
  await expect(
    page.getByLabel("Branch", { exact: true }).locator("option"),
  ).toHaveText([
    "Choose your branch",
    "COMPS",
    "IT",
    "AIDS",
    "CSBS",
    "VLSI",
    "CCE",
    "EXTC",
    "EXCP",
    "MECH",
    "RAI",
    "CIVIL",
  ]);
  await page.getByLabel("Branch", { exact: true }).selectOption("COMPS");
  await page.getByRole("radio", { name: /^SY\b/ }).check();
  const values = {
    "Current semester": "3",
    Division: "B",
    Batch: "2",
    "Roll number": "001A",
  };
  for (const [label, value] of Object.entries(values))
    await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Save profile", exact: true }).click();
  await expect(page.getByRole("heading", { name: /This week/ })).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.reload();
  await expect(page.getByLabel("Branch", { exact: true })).toHaveValue("COMPS");
  const profile = await page.request.get("/api/v1/me");
  expect(await profile.json()).toMatchObject({
    institution: "KJSSE",
    programme: "BTech",
    branchCode: "COMPS",
    branchName: "Computer Engineering",
  });
  await page.getByRole("button", { name: "Subjects", exact: true }).click();
  await page.getByRole("button", { name: "Add subject", exact: true }).click();
  await page.getByLabel("Subject name", { exact: true }).fill("Database lab");
  await page.getByLabel("Subject kind", { exact: true }).selectOption("lab");
  await page.getByRole("button", { name: "Save subject", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Database lab", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Timetable", exact: true }).click();
  await page.getByRole("button", { name: "Add weekly slot" }).click();
  await page.getByLabel("Starts hour").selectOption("2");
  await page.getByLabel("Starts minute").selectOption("0");
  await page
    .getByRole("group", { name: "Starts morning or afternoon" })
    .getByRole("button", { name: "pm" })
    .click();
  await page.getByLabel("Ends hour").selectOption("4");
  await page.getByLabel("Ends minute").selectOption("0");
  await page
    .getByRole("group", { name: "Ends morning or afternoon" })
    .getByRole("button", { name: "pm" })
    .click();
  await page.getByLabel("Room / location").fill("Lab 101");
  await page.getByRole("button", { name: "Save timetable" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "Add task", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Browser lab report");
  await page
    .getByLabel("Subject", { exact: true })
    .selectOption({ label: "Database lab · lab" });
  await page.getByLabel("Personal notes").fill("Keep this personal note");
  await page.getByLabel("Deadline date").fill("2026-10-20");
  await page.getByRole("button", { name: "Save task", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "Tasks", exact: true }).click();
  await page.getByRole("button", { name: /^Browser lab report/ }).click();
  await expect(
    page.getByText("Keep this personal note", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Mark completed", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Reopen task", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Edit task", exact: true }).click();
  await page.getByLabel("Personal notes").fill("Edited while completed");
  await page.getByRole("button", { name: "Save task", exact: true }).click();
  await page.reload();
  await page.getByRole("radio", { name: "Completed", exact: true }).check();
  await page.getByRole("button", { name: /^Browser lab report/ }).click();
  await expect(
    page.getByRole("button", { name: "Reopen task", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Edited while completed", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Reopen task", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Mark completed", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: "Week", exact: true }).click();
  await page.getByRole("button", { name: "Month", exact: true }).click();
  const currentMonth = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
  })
    .format(new Date())
    .slice(0, 7);
  const delta =
    (2026 - Number(currentMonth.slice(0, 4))) * 12 +
    10 -
    Number(currentMonth.slice(5));
  for (let i = 0; i < Math.abs(delta); i++)
    await page
      .getByRole("button", {
        name: delta > 0 ? "Next month" : "Previous month",
      })
      .click();
  await expect(
    page.getByRole("heading", { name: "October 2026" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "2026-10-20, 1 tasks" }).click();
  await expect(
    page.getByRole("button", { name: /^Browser lab report/ }).last(),
  ).toBeVisible();
  await page.screenshot({
    path: "../../.local/calendar-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Tasks", exact: true }).click();
  await page.getByRole("radio", { name: "All", exact: true }).check();
  await page.screenshot({
    path: "../../.local/tasks-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: /^Browser lab report/ }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("button", { name: "Confirm deletion" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "No tasks in this view" }),
  ).toBeVisible();
  const csrf = await page.request.get("/auth/csrf");
  const { token } = await csrf.json();
  const quizResponse = await page.request.post("/api/v1/tasks", {
    headers: { Origin: "http://localhost:3001", "X-CSRF-Token": token },
    data: {
      title: "Live cutoff quiz",
      type: "test",
      timingMode: "attempt_window",
      availabilityClosesAt: new Date(Date.now() + 5000).toISOString(),
    },
  });
  expect(quizResponse.status()).toBe(201);
  const quiz = await quizResponse.json();
  await page.reload();
  await expect(
    page.getByRole("button", { name: /^Live cutoff quiz/ }),
  ).toContainText("due");
  await expect(
    page.getByRole("button", { name: /^Live cutoff quiz/ }),
  ).toContainText("missed", { timeout: 10000 });
  const afterCsrf = await page.request.get("/auth/csrf");
  const afterToken = (await afterCsrf.json()).token;
  const removeQuiz = await page.request.delete(
    "/api/v1/tasks/" + quiz.id + "?revision=" + quiz.revision,
    {
      headers: {
        Origin: "http://localhost:3001",
        "X-CSRF-Token": afterToken,
        "Idempotency-Key": "browser-cutoff-cleanup",
      },
    },
  );
  expect(removeQuiz.status()).toBe(200);
  await page.reload();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  // Online, the saved-data banner never shows.
  expect((await page.request.get("/api/v1/changes")).status()).toBe(200);
  await expect(page.locator(".offline-banner")).toHaveCount(0);
  await page.getByRole("radio", { name: "Dark", exact: true }).check();
  await page.getByRole("button", { name: "Save profile", exact: true }).click();
  await expect(page.locator("html")).toHaveClass("dark");
  await page.reload();
  await expect(page.locator("html")).toHaveClass("dark");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Subjects", exact: true }).click();
  await page
    .getByRole("button", { name: "Edit Database lab", exact: true })
    .click();
  await page
    .getByLabel("Subject name", { exact: true })
    .fill("Database lab revised");
  await page.getByRole("button", { name: "Save subject", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Database lab revised", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Delete Database lab revised", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete subject", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "A place for every subject" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/sign-in/);
  expect(
    (await context.cookies()).some((c) => c.name === "duecare-session"),
  ).toBe(false);
});

test("gateway rejects forged writes and never exposes credentials", async ({
  request,
}) => {
  const r = await request.patch("/api/v1/me", {
    data: { revision: 1, division: "A" },
  });
  expect(r.status()).toBe(403);
  const signIn = await request.get("/sign-in");
  expect(signIn.status()).toBe(200);
  const html = await signIn.text();
  expect(html).not.toContain("GATEWAY_SECRET");
  expect(html).not.toContain("access_token");
});
