import { describe, it, expect } from "vitest";
import { deadline } from "@/lib/api";

const base = {
  dueAt: null as string | null,
  dueDate: null as string | null,
  type: "test" as "test" | "assignment",
  dateWindowStart: null as string | null,
  dateWindowEnd: null as string | null,
  timingProvenance: {} as Record<string, { basis?: string }>,
  timingTentative: null as { question?: string } | null,
};

describe("deadline wording", () => {
  it("says so only when the source gave no date", () => {
    expect(deadline(base)).toEqual({ main: "No due date yet", note: null });
  });
  it("shows a window as its range, not its derived cutoff", () => {
    const d = deadline({
      ...base,
      dueAt: "2026-12-04T18:29:00+00:00",
      dateWindowStart: "2026-11-30",
      dateWindowEnd: "2026-12-04",
      timingProvenance: { dueAt: { basis: "source-window-end" } },
    });
    expect(d.main).toBe("30 Nov – 4 Dec 2026");
    expect(d.note).toBe("exact day not announced");
  });
  it("names a dated test without a time, and marks doubt", () => {
    const d = deadline({
      ...base,
      dueAt: "2026-10-31T18:29:00+00:00",
      dueDate: "2026-10-31",
      timingTentative: { question: "Which date applies?" },
    });
    expect(d.main).toBe("31 Oct 2026");
    expect(d.note).toBe("Tentative · time not announced");
  });
  it("keeps an exact time, and a window beside it is not the deadline", () => {
    const d = deadline({
      ...base,
      dueAt: "2026-09-28T08:00:00+00:00",
      dateWindowStart: "2026-09-27",
      dateWindowEnd: "2026-09-30",
    });
    expect(d.main).toMatch(/28 Sept? 2026, 1:30\s?pm/i);
    expect(d.note).toBeNull();
  });
});
