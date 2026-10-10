import type { DraftRow, Subject } from "./types";

export function importSubjectKind(
  row: DraftRow,
  subjects: Subject[],
): Subject["kind"] {
  if (row.component) return row.component;
  const maths = /\b(math(s|ematics)?|am|em|itvc|calculus)(?:\b|(?=[1-4]))|integral transforms/i;
  const labels = [row.baseLabel, row.label, row.code || ""];
  const related = subjects.filter((s) =>
    [s.name, s.code, ...s.aliases].some(
      (value) => value && labels.some(
        (label) => label && value.toLowerCase() === label.toLowerCase(),
      ),
    ),
  );
  return [...labels, ...related.map((s) => s.name)].some((label) => maths.test(label))
    ? "tutorial"
    : "lab";
}
