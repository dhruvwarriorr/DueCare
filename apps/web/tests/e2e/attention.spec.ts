import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const origin = "http://localhost:3001";
async function write(
  page: Page,
  method: "post" | "patch",
  path: string,
  data: unknown,
) {
  const { token } = await (await page.request.get("/auth/csrf")).json();
  const response = await page.request[method](path, {
    headers: {
      Origin: origin,
      "X-CSRF-Token": token,
      "Idempotency-Key": crypto.randomUUID(),
    },
    data,
  });
  expect(response.ok()).toBeTruthy();
  return response.json();
}

test("imported LMS work is resolved in Needs attention, completed from confirmed evidence, and rules are managed", async ({
  page,
  context,
}) => {
  const { attentionHandle } = JSON.parse(
    readFileSync(resolve("../../.local/e2e-account.json"), "utf8"),
  );
  await context.addCookies([
    {
      name: "duecare-session",
      value: attentionHandle,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await page.goto("/");
  const me = await (await page.request.get("/api/v1/me")).json();
  await write(page, "patch", "/api/v1/me", {
    revision: me.revision,
    branchCode: "COMPS",
    classYear: "SY",
    currentSemester: 3,
    division: "B",
    generalBatch: "2",
    rollNumber: "003C",
  });
  await write(page, "post", "/api/v1/subjects", {
    name: "Data Structures",
    kind: "theory",
  });
  await write(page, "post", "/api/v1/subjects", {
    name: "Data Structures Laboratory",
    kind: "lab",
  });
  const { url } = await write(page, "post", "/api/v1/connections/authorize", {
    service: "gmail",
  });
  const state = new URL(url).searchParams.get("state") || "";
  await page.goto(
    "/connections/callback?code=gmail-attention&state=" +
      encodeURIComponent(state),
  );
  const gmail = page.locator(".connection-card", { hasText: "Gmail" });
  await expect(gmail).toContainText("Last synced", { timeout: 15000 });

  // The course name matches both theory and lab subjects, so DueCare asks instead of guessing.
  await page.goto("/?view=attention");
  const card = page.locator(".review-card", { hasText: "EXP3-Queue" });
  await expect(card).toContainText("Which of your subjects is this for?");
  await expect(page.locator(".nav-badge")).toHaveText(/\d+/);
  await page.screenshot({ path: "../../.local/attention-desktop.png", fullPage: true });
  await card
    .getByLabel("Subject", { exact: true })
    .selectOption({ label: "Data Structures Laboratory · lab" });
  await card.getByRole("button", { name: "Add task" }).click();
  await expect(card).toHaveCount(0);

  // Reprocessing reconsiders the receipt that arrived before the task existed.
  await page.goto("/?view=connections");
  const reprocessed = page.waitForResponse(
    (r) => r.url().includes("/reprocess") && r.request().method() === "POST",
    { timeout: 20000 },
  );
  await gmail.getByRole("button", { name: "Reprocess" }).click();
  expect((await reprocessed).ok()).toBeTruthy();
  await expect(gmail).not.toContainText("Syncing", { timeout: 20000 });
  await page.goto("/?view=attention");
  const receipt = page.locator(".review-card", { hasText: "Submission found" });
  await expect(receipt).toContainText("Mark this task completed?", {
    timeout: 15000,
  });
  await receipt.getByRole("button", { name: "Mark completed" }).click();
  await expect(receipt).toHaveCount(0);

  await page.goto("/?view=tasks");
  await page.getByLabel("Status filter").selectOption("completed");
  await page.getByRole("button", { name: /EXP3-Queue/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(
    "Confirmed by you from submission evidence",
  );
  await expect(dialog).toContainText("Gmail");
  await expect(dialog.getByText("Submission evidence", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Due / overdue notice", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();

  await page.goto("/?view=rules");
  await expect(
    page.getByRole("heading", { name: "No rules yet" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "New rule" }).click();
  await page.getByLabel("Rule name", { exact: true }).fill("Skip hackathons");
  await page.getByLabel("Value", { exact: true }).fill("hackathon");
  await page.getByRole("button", { name: "Save rule" }).click();
  await expect(page.locator(".rule-list")).toContainText(
    "When the text contains “hackathon”, don’t add the task.",
  );

  await page.setViewportSize({ width: 390, height: 844 });
  for (const view of ["attention", "rules"]) {
    await page.goto("/?view=" + view);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
  }
  await page.screenshot({
    path: "../../.local/rules-mobile.png",
    fullPage: true,
  });
});
