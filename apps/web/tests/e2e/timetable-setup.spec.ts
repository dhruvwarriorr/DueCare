import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

test("onboarding offers timetable upload, Maths tutorials and instant subject creation", async ({ page, context }) => {
  const { instantHandle } = JSON.parse(readFileSync(resolve("../../.local/e2e-account.json"), "utf8"));
  await context.addCookies([{
    name: "duecare-session", value: instantHandle, domain: "localhost", path: "/", httpOnly: true, sameSite: "Lax",
  }]);
  // Isolate the external upload transport; interpretation, subject writes and timetable saves
  // still go through the actual gateway and disposable database.
  await page.route("**/api/v1/timetable-imports/uploads", async (route) => {
    await route.fulfill({ json: route.request().method() === "DELETE" ? { ok: true } : {
      uploads: [{ path: "synthetic.pdf", url: "http://localhost:3001/test-timetable-upload" }],
    } });
  });
  await page.route("**/test-timetable-upload", (route) => route.fulfill({ status: 200, body: "" }));
  await page.route("**/api/v1/timetable-imports/extract-uploaded", (route) => route.fulfill({ json: {
    method: "pdf_text",
    pages: [{ id: "p1", source: "PDF page 1", layout: "grid", method: "pdf_text", preview: null,
      header: { classLabel: "SY B. Tech COMP B" }, issues: [], cells: [
        [1, "09:00", "10:00", "Maths B102 SAM"],
        [2, "11:00", "12:00", "B2 Maths B102 SAM"],
        [4, "11:00", "12:00", "B2 Maths B102 SAM"],
        [1, "10:00", "11:00", "DS B204 JMR"],
        [2, "11:00", "12:00", "B1 WDL B116B SIP"],
      ].map(([weekday, start, end, text], i) => ({
        id: `c${i + 1}`, page: "p1", weekday, start, end, lines: [text], bbox: null,
        narrow: String(text).startsWith("B"), spansDays: false,
      })),
    }],
  } }));
  await page.goto("/");
  const option = page.getByRole("checkbox", { name: "Add your timetable for better accuracy" });
  await expect(option).not.toBeChecked();
  await page.getByLabel("Branch", { exact: true }).selectOption("COMPS");
  await page.getByRole("radio", { name: /^SY\b/ }).check();
  for (const [label, value] of Object.entries({ "Current semester": "3", Division: "B", Batch: "2", "Roll number": "001A" }))
    await page.getByLabel(label, { exact: true }).fill(value);
  await option.check();
  await page.getByRole("button", { name: "Save and add timetable" }).click();
  const dialog = page.getByRole("dialog", { name: "Upload timetable" });
  await expect(dialog).toBeVisible();
  await dialog.locator('input[type="file"]').setInputFiles(resolve("../../.local/e2e-timetable.pdf"));
  await dialog.getByRole("button", { name: "Read timetable" }).click();
  await expect(dialog.getByRole("button", { name: "Instant create subjects" })).toBeVisible();
  const maths = dialog.locator("fieldset").filter({ has: page.locator("legend", { hasText: /Maths.*tutorial/ }) });
  await maths.getByRole("button", { name: "Create subject from this" }).click();
  await expect(maths.getByRole("combobox", { name: "Kind", exact: true })).toHaveValue("tutorial");
  await maths.getByRole("button", { name: "Cancel", exact: true }).click();
  await dialog.getByRole("button", { name: "Instant create subjects" }).click();
  await expect(dialog.getByText("3 subjects created. All recognized courses are linked.")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Instant create subjects" })).toHaveCount(0);
  const response = await page.request.get("/api/v1/subjects");
  expect((await response.json()).items.map((s: { name: string; kind: string }) => [s.name, s.kind])).toEqual(
    expect.arrayContaining([["Maths", "theory"], ["Maths", "tutorial"], ["DS", "theory"]]),
  );
  // Check the original failure: every hour/minute is readable and contained at each width.
  for (const width of [1440, 1024, 390]) {
    await page.emulateMedia({ colorScheme: width === 1440 ? "light" : "dark" });
    await page.setViewportSize({ width, height: 1000 });
    const draft = dialog.locator(".import-draft");
    expect(await draft.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    const hours = await dialog.locator('.time-custom select').evaluateAll((els) => els.map((el) => el.getBoundingClientRect().width));
    expect(hours.every((width) => width >= 54)).toBe(true);
    await page.screenshot({ path: `test-results/timetable-setup-${width}.png` });
  }
  await dialog.getByRole("button", { name: "Review save" }).click();
  await expect(dialog.getByText("Will add (4)")).toBeVisible();
  await dialog.getByRole("button", { name: "Confirm timetable" }).click();
  await expect(dialog.getByText("Timetable saved", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Done", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Maths", exact: true })).toHaveCount(2);
});
