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

  // "DS" names both the theory and lab subjects; EXP3 is lab work, so the lab is linked
  // automatically and no subject question is asked.
  await page.goto("/?view=attention");
  await expect(
    page.getByText("Which of your subjects is this for?"),
  ).toHaveCount(0);
  // A verified LMS receipt completes its exact task by itself: nothing is left to confirm.
  await expect(page.getByText("Nothing needs your attention")).toBeVisible();
  await page.screenshot({
    path: "../../.local/attention-desktop.png",
    fullPage: true,
  });

  await page.goto("/?view=tasks");
  await page.getByRole("radio", { name: "Completed", exact: true }).check();
  await page.getByRole("button", { name: /^EXP3-Queue/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("LMS submission confirmation");
  await expect(dialog).toContainText("Gmail");
  await expect(dialog).toContainText("Data Structures Laboratory");
  await expect(dialog).toContainText(
    "Linked automatically from the course name",
  );
  await page.getByRole("button", { name: "Close dialog" }).click();

  await page.goto("/?view=rules");
  await expect(
    page.getByRole("heading", { name: "No rules yet" }),
  ).toBeVisible();
  // A plain sentence becomes a rule without AI; the student confirms it in plain words.
  await page.getByLabel("Add a rule").fill("hide seminar mail");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.locator(".rule-preview")).toContainText(
    "Hide work containing “seminar”.",
  );
  await page.getByRole("button", { name: "Save rule" }).click();
  await expect(page.locator(".rule-list")).toContainText(
    "Hide work containing “seminar”",
  );
  await expect(page.locator(".rule-list")).toContainText("Applies to 0 tasks");
  // Or built from three choices.
  await page.getByRole("button", { name: "Or build it yourself" }).click();
  await page.getByLabel("Do").selectOption("critical");
  await page.getByLabel("For").selectOption("taskType");
  await page.getByLabel("Which").selectOption("test");
  await page.getByRole("button", { name: "Preview" }).click();
  await page.getByRole("button", { name: "Save rule" }).click();
  await expect(page.locator(".rule-list")).toContainText(
    "Make tests critical priority",
  );
  await page.getByRole("checkbox", { name: "On" }).first().click();
  await expect(page.locator(".rule-list li").first()).toContainText("Off");

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
