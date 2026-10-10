import { describe, expect, it } from "vitest";
import { importSubjectKind } from "@/lib/import-subject";
import type { DraftRow, Subject } from "@/lib/types";

const row = (label: string, component: DraftRow["component"] = null) =>
  ({ label, baseLabel: label, code: null, component }) as DraftRow;

describe("timetable subject defaults", () => {
  it("uses tutorials for Maths batch names and ITVC", () => {
    for (const label of ["Maths", "Engineering Mathematics", "AM-II", "EM3", "ITVC"])
      expect(importSubjectKind(row(label), [])).toBe("tutorial");
    expect(importSubjectKind(row("DBMS"), [])).toBe("lab");
  });

  it("recognizes Maths through an existing subject's printed alias", () => {
    const subjects = [{ name: "Engineering Mathematics", aliases: ["MA2"] }] as Subject[];
    expect(importSubjectKind(row("MA2"), subjects)).toBe("tutorial");
  });

  it("keeps an explicit component, including class-wide Maths theory", () => {
    expect(importSubjectKind(row("Maths", "theory"), [])).toBe("theory");
    expect(importSubjectKind(row("Maths", "tutorial"), [])).toBe("tutorial");
  });
});
