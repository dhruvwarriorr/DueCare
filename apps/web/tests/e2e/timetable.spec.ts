import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
test("timetable upload keeps the student's batch, links subjects, and saves after review", async ({
  page,
  context,
}) => {
  const { timetableHandle } = JSON.parse(
    readFileSync(resolve("../../.local/e2e-account.json"), "utf8"),
  );
  await context.addCookies([
    {
      name: "duecare-session",
      value: timetableHandle,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await page.goto("/");
  await page.getByRole("button", { name: "Subjects", exact: true }).click();
  await page.getByRole("button", { name: "Upload timetable" }).click();
  const dialog = page.getByRole("dialog", { name: "Upload timetable" });
  await dialog
    .locator('input[type="file"]')
    .setInputFiles(resolve("../../.local/e2e-timetable.pdf"));
  await expect(dialog.getByText("e2e-timetable.pdf")).toBeVisible();
  await dialog.getByRole("button", { name: "Read timetable" }).click();
  await expect(dialog.getByText(/ready ·/)).toBeVisible({ timeout: 30000 });
  await expect(dialog.getByText("Your batch: B2")).toBeVisible();
  await page.screenshot({ path: "test-results/timetable-review.png" });

  // Other batches' labs and lunch are left out of the review.
  await expect(dialog.getByText("Batch B1")).toHaveCount(0);
  await expect(dialog.getByText(/\d+ not included/)).toBeVisible();

  // A missing subject can be added without losing the draft, then linked.
  await dialog.getByRole("button", { name: "Add subject" }).click();
  const add = page.getByRole("dialog", { name: "Add a subject" });
  await add.getByLabel("Subject name").fill("Web Development Lab");
  await add.getByLabel("Subject kind").selectOption("lab");
  await add.getByRole("button", { name: "Save subject" }).click();
  await expect(add).toBeHidden();
  await expect(dialog.getByText("Your batch: B2")).toBeVisible();
  await expect(
    dialog.locator("option", { hasText: "Web Development Lab · lab" }).first(),
  ).toBeAttached();

  // Nothing can be saved until groups are chosen and every slot has a subject.
  const review = dialog.getByRole("button", { name: /needs? review/ });
  await expect(review).toBeDisabled();
  await dialog.getByLabel("DA: which group are you in?").selectOption("none");
  await dialog
    .getByRole("button", { name: "Accept 2 suggested links" })
    .click();
  await page.screenshot({
    path: "test-results/timetable-linked.png",
    fullPage: false,
  });
  await dialog.getByRole("button", { name: "Review save" }).click();
  await expect(dialog.getByText("Will add (4)")).toBeVisible();
  await expect(
    dialog.getByText(
      /Database Management Systems Lab Mon 14:00–16:00 · B116A/,
    ),
  ).toBeVisible();
  await page.screenshot({ path: "test-results/timetable-summary.png" });
  await dialog.getByRole("button", { name: "Confirm timetable" }).click();
  await expect(dialog.getByText("Timetable saved")).toBeVisible();
  await expect(
    dialog.getByText(/4 weekly slots saved across 4 subjects/),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "Done" }).click();

  // The confirmed slots appear in the existing subject timetable editor.
  const lab = page
    .locator("article")
    .filter({ hasText: "Database Management Systems Lab" });
  await lab.getByRole("button", { name: "Timetable" }).click();
  const editor = page.getByRole("dialog", {
    name: "Database Management Systems Lab timetable",
  });
  await expect(editor.getByLabel("Starts (IST)")).toHaveValue(/^14:00/);
  await expect(editor.getByLabel("Ends (IST)")).toHaveValue(/^16:00/);
  await expect(editor.getByLabel("Room / location")).toHaveValue("B116A");
});
test("scheduler screenshots are read and linked without AI", async ({
  page,
  context,
}) => {
  const { schedulerHandle } = JSON.parse(
    readFileSync(resolve("../../.local/e2e-account.json"), "utf8"),
  );
  await context.addCookies([
    {
      name: "duecare-session",
      value: schedulerHandle,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await page.goto("/");
  await page.getByRole("button", { name: "Subjects", exact: true }).click();
  await page.getByRole("button", { name: "Upload timetable" }).click();
  const dialog = page.getByRole("dialog", { name: "Upload timetable" });
  await expect(
    dialog.getByText("Somaiya roster scheduler screenshots"),
  ).toBeVisible();
  await dialog
    .locator('input[type="file"]')
    .setInputFiles([
      resolve("../../.local/e2e-scheduler-2.png"),
      resolve("../../.local/e2e-scheduler-1.png"),
    ]);
  await dialog.getByRole("button", { name: "Read timetable" }).click();
  await expect(dialog.getByText(/\d+ ready/)).toBeVisible({ timeout: 30000 });
  await expect(
    dialog.getByText("Screenshot 2 · shows 07:00–11:55"),
  ).toBeVisible();
  await page.screenshot({ path: "test-results/scheduler-review.png" });
  // A missing subject is created from its course card and linked to every slot.
  const dbms = dialog.locator("fieldset", {
    has: page.locator("legend", { hasText: "Database Management Systems" }),
  });
  await dbms.getByRole("button", { name: "Create subject from this" }).click();
  await expect(dbms.getByLabel("New subject name")).toHaveValue(
    "Database Management Systems",
  );
  await expect(dbms.getByLabel("Kind")).toHaveValue("theory");
  await dbms.getByRole("button", { name: "Create and link 1 slot" }).click();
  await expect(dbms.getByLabel("Subject", { exact: true })).toHaveValue(/.+/);
  // An existing subject is never created again; it is offered for linking instead.
  const lab = dialog.locator("fieldset", {
    has: page.locator("legend", { hasText: "Data Structures Laboratory" }),
  });
  await lab.getByRole("button", { name: "Create subject from this" }).click();
  await lab.getByLabel("New subject name").fill("data structures lab");
  await expect(
    lab.getByText("You already have Data Structures Lab · lab"),
  ).toBeVisible();
  await expect(
    lab.getByRole("button", { name: /Create and link/ }),
  ).toBeDisabled();
  await lab.getByRole("button", { name: "Use it" }).click();
  await page.screenshot({ path: "test-results/scheduler-created.png" });
  await dialog.getByRole("button", { name: "Accept 1 suggested link" }).click();
  await dialog.getByRole("button", { name: "Review save" }).click();
  await expect(dialog.getByText("Will add (4)")).toBeVisible();
  await expect(
    dialog.getByText(/Data Structures Lab Tue 11:00–13:00/),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "Confirm timetable" }).click();
  await expect(dialog.getByText("Timetable saved")).toBeVisible();
  await dialog.getByRole("button", { name: "Done" }).click();
  await expect(
    page.getByRole("heading", { name: "Database Management Systems" }),
  ).toHaveCount(1);
});
