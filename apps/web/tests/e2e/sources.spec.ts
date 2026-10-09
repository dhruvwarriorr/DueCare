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
async function connect(page: Page, service: string, code: string) {
  const { url } = await write(page, "post", "/api/v1/connections/authorize", {
    service,
  });
  const authorization = new URL(url);
  expect(authorization.searchParams.get("code_challenge_method")).toBe("S256");
  // Google would redirect the browser here; the synthetic provider accepts the code.
  await page.goto(
    "/connections/callback?code=" +
      code +
      "&state=" +
      encodeURIComponent(authorization.searchParams.get("state") || ""),
  );
}

test("sources connect, sync in the browser, honour blocks, and link Classroom courses without creating tasks", async ({
  page,
  context,
}) => {
  const { sourcesHandle } = JSON.parse(
    readFileSync(resolve("../../.local/e2e-account.json"), "utf8"),
  );
  await context.addCookies([
    {
      name: "duecare-session",
      value: sourcesHandle,
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
    rollNumber: "002B",
  });
  await write(page, "post", "/api/v1/subjects", {
    name: "Databases",
    kind: "theory",
  });

  await page.goto("/?view=connections");
  await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Gmail and Classroom access is needed" }),
  ).toBeVisible();
  await page
    .getByLabel("Sender email", { exact: true })
    .fill(" Blocked.Sender@SOMAIYA.edu ");
  await page.getByLabel("Preference", { exact: true }).selectOption("block");
  await page.getByRole("button", { name: "Save sender" }).click();
  await expect(page.getByText("blocked.sender@somaiya.edu")).toBeVisible();

  await connect(page, "gmail", "gmail-e2e");
  await expect(page).toHaveURL(/view=connections$/);
  await expect(
    page.getByText("Gmail is connected. Syncing will start now."),
  ).toBeVisible();
  const gmail = page.locator(".connection-card", { hasText: "Gmail" });
  await expect(gmail).toContainText("personal.gmail@example.com");
  await expect(gmail).toContainText("Last synced", { timeout: 15000 });
  await expect(gmail).toContainText("1 waiting for AI interpretation");
  await expect(gmail).toContainText("1 from blocked senders");

  // The LMS reminder is the student's own work: it becomes a task without asking. No subject of
  // theirs matches "Data Structures", so it is kept without one.
  await page.goto("/?view=tasks");
  await expect(page.getByRole("button", { name: /EXP3-Queue/ })).toBeVisible();
  await page.goto("/?view=dashboard");
  await expect(page.locator(".sync-overview")).toContainText(
    "personal.gmail@example.com",
  );

  await connect(page, "classroom", "classroom-e2e");
  const classroom = page.locator(".connection-card", {
    hasText: "Google Classroom",
  });
  await expect(classroom).toContainText("Synthetic Databases Div B", {
    timeout: 15000,
  });
  // The course names the student's subject, so it links itself and its work is read at once.
  await expect(classroom.locator(".chip")).toContainText(
    "Databases · theory · auto",
  );
  await expect(classroom).toContainText("1 waiting for AI interpretation", {
    timeout: 15000,
  });
  await page.goto("/?view=connections");
  await expect(
    page.getByRole("heading", { name: "Gmail and Classroom are connected" }),
  ).toBeVisible();
  await page.goto("/?view=subjects");
  await expect(
    page.getByText("Linked to Classroom: Synthetic Databases Div B"),
  ).toBeVisible();

  const forged = await page.request.get(
    "/api/v1/connections/oauth/callback?state=x&code=y",
  );
  expect(forged.status()).toBe(404);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?view=connections");
  await expect(gmail).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../../.local/sources-mobile.png",
    fullPage: true,
  });
  await gmail.getByRole("button", { name: "Disconnect" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Disconnect" })
    .click();
  await expect(page.getByText("1 disconnected source")).toBeVisible();
});
