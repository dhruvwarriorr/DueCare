import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
test("KT notice preference is saved from Settings", async ({
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
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const show = page.getByRole("radio", { name: /Show KT notices/ });
  const ignore = page.getByRole("radio", { name: /Ignore KT notices/ });
  await expect(show).toBeChecked();
  await ignore.check();
  await expect(
    page.getByRole("status").filter({ hasText: "Saved" }),
  ).toBeVisible();
  await page
    .getByRole("heading", { name: "KT notices" })
    .scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/kt-settings.png" });
  await page.reload();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(
    page.getByRole("radio", { name: /Ignore KT notices/ }),
  ).toBeChecked();
});
