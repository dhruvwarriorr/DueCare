import { test, expect, type Page, type BrowserContext } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
async function signIn(context: BrowserContext, key: string) {
  const data = JSON.parse(
    readFileSync(resolve("../../.local/e2e-account.json"), "utf8"),
  );
  await context.addCookies([
    {
      name: "duecare-session",
      value: data[key],
      domain: "localhost",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
}
async function write(
  page: Page,
  method: "post" | "patch",
  path: string,
  data: unknown,
) {
  const { token } = await (await page.request.get("/auth/csrf")).json();
  const r = await page.request[method](path, {
    headers: {
      Origin: "http://localhost:3001",
      "X-CSRF-Token": token,
      "Idempotency-Key": crypto.randomUUID(),
    },
    data,
  });
  expect(r.ok()).toBeTruthy();
  return r.json();
}
async function onboard(page: Page) {
  const me = await (await page.request.get("/api/v1/me")).json();
  await write(page, "patch", "/api/v1/me", {
    revision: me.revision,
    institution: "Example University",
    programme: "Engineering",
    department: "Computing",
    admissionYear: 2025,
    classYear: "SY",
    currentSemester: 3,
    division: "B",
    generalBatch: "2",
    rollNumber: "004D",
  });
}
test("activity reads, task links, privacy controls, and themes work on a mobile browser", async ({
  page,
  context,
}) => {
  await signIn(context, "privacyHandle");
  await page.goto("/");
  await onboard(page);
  await write(page, "post", "/api/v1/tasks", {
    title: "Activity browser task",
    type: "assignment",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?view=activity");
  await expect(
    page.getByRole("heading", { name: "Activity", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("New work was added to your tasks."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Mark read", exact: true }).click();
  await page.getByLabel("Activity filter").selectOption("false");
  await expect(
    page.getByRole("heading", { name: "No activity here yet" }),
  ).toBeVisible();
  await page.getByLabel("Activity filter").selectOption("true");
  await page.getByRole("button", { name: "Mark unread", exact: true }).click();
  await page.getByLabel("Activity filter").selectOption("");
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Activity browser task" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.goto("/?view=settings");
  await expect(
    page.getByRole("heading", { name: "Privacy and your data" }),
  ).toBeVisible();
  await expect(page.getByText("No imported sources to delete.")).toBeVisible();
  await page.getByLabel("Appearance").selectOption("dark");
  await page.getByRole("button", { name: "Save profile", exact: true }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByLabel("Appearance").selectOption("light");
  await page.getByRole("button", { name: "Save profile", exact: true }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await page
    .getByRole("button", { name: "Delete account", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Permanently delete account" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../../.local/privacy-mobile.png",
    fullPage: true,
  });
});

test("account deletion keeps its recovery token server-side and survives page reload", async ({
  page,
  context,
}) => {
  await signIn(context, "deleteHandle");
  await page.goto("/");
  await onboard(page);
  await write(page, "post", "/api/v1/tasks", {
    title: "Delete this workspace",
    type: "assignment",
  });
  await page.goto("/?view=settings");
  await page
    .getByRole("button", { name: "Delete account", exact: true })
    .click();
  await page.getByLabel("Type DELETE to confirm").fill("DELETE");
  await page
    .getByRole("button", { name: "Permanently delete account" })
    .click();
  await expect(page).toHaveURL(/privacy\/deletion/);
  await expect(
    page.getByRole("heading", { name: "Your account has been deleted" }),
  ).toBeVisible({ timeout: 30000 });
  const cookies = await context.cookies();
  const ticket = cookies.find((c) => c.name === "duecare-deletion");
  expect(ticket?.httpOnly).toBe(true);
  expect(cookies.some((c) => c.name === "duecare-session")).toBe(false);
  const response = await (
    await page.request.get("/api/v1/privacy/account-deletion")
  ).json();
  expect(response.status).toBe("completed");
  expect(response.resumeToken).toBeUndefined();
  expect(await page.evaluate(() => document.cookie)).not.toContain(
    "duecare-deletion",
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Your account has been deleted" }),
  ).toBeVisible();
  expect((await page.request.get("/api/v1/tasks")).status()).toBe(401);
});

test("imported-data deletion preserves student edits and restoration does not silently recreate tasks", async ({
  page,
  context,
}) => {
  await signIn(context, "sourceDeleteHandle");
  await page.goto("/");
  await onboard(page);
  await page.goto("/?view=settings");
  await page
    .getByRole("button", { name: "Delete imported data", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Confirm deletion", exact: true })
    .click();
  await expect(page.getByText("1 tasks removed · 1 preserved")).toBeVisible({
    timeout: 30000,
  });
  const data = JSON.parse(
    readFileSync(resolve("../../.local/e2e-account.json"), "utf8"),
  );
  expect(
    (await page.request.get("/api/v1/tasks/" + data.removedTask)).status(),
  ).toBe(404);
  const retained = await (
    await page.request.get("/api/v1/tasks/" + data.retainedTask)
  ).json();
  expect(retained.sources).toEqual(["manual"]);
  expect(retained.notes).toBe("My note");
  await page.getByText("Restore deleted imports", { exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Restore import", exact: true }),
  ).toHaveCount(2);
  await page
    .getByRole("button", { name: "Restore import", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: "Restore import", exact: true }),
  ).toHaveCount(1);
  expect(
    (await page.request.get("/api/v1/tasks/" + data.removedTask)).status(),
  ).toBe(404);
  await expect(
    page.getByRole("button", { name: "Reimport", exact: true }),
  ).toBeDisabled();
});
