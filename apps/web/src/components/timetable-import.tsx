"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  Check,
  FileUp,
  Plus,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  DraftRow,
  ImportSlotBrief,
  ImportSummary,
  Subject,
  TimetableDraft,
  TimetableReading,
} from "@/lib/types";
import { Button } from "./ui/button";
import { TimePicker } from "./ui/time-picker";
import { Dialog } from "./ui/dialog";
import { ErrorNotice } from "./ui/field";

const days = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];
const short = (weekday: number) => days[weekday - 1]?.slice(0, 3) || "?";
const MB = 1024 * 1024;
const issueText: Record<string, string> = {
  check_text: "Check this entry against the original",
  batch_unknown:
    "Add your batch in your profile so batch sessions can be filtered",
  ambiguous_subject: "Several subjects match. Choose the right one",
  clipped_start:
    "This class is cut off at the top of your screenshots. Check its start time",
  placeholder:
    "A class-wide slot for each student's own choice. Link it to your subject, or exclude it",
  clipped_end:
    "This class is cut off at the bottom of your screenshots. Check its end time",
};

type View = {
  row: DraftRow;
  included: boolean;
  reason: string | null;
  needsChoice: boolean;
  problems: string[];
  notes: string[];
};

// Mirrors the server's name normalization, so a repeat is caught before asking it.
const normalized = (value: string) =>
  value
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[^a-z0-9]/g, "");

function componentText(row: DraftRow) {
  if (row.component) return row.component;
  return row.batches.length || row.group !== null ? "batch session" : "";
}

type Course = {
  key: string;
  label: string;
  code: string | null;
  component: string;
  track: string | null;
  slots: View[];
  subjectId: string | null;
  mixed: boolean;
  suggestion: string | null;
  suggestionSource: DraftRow["suggestionSource"];
  needsReview: boolean;
  notes: string[];
};

// One course (same printed name or code and component) is linked once for all its weekly slots.
function courseKey(row: DraftRow) {
  if (!row.cellId) return row.id; // Slots the student adds stay separate.
  const name = row.code || row.baseLabel.trim().toLowerCase();
  return name + "|" + (row.component || "batch");
}

function courses(views: View[]): Course[] {
  const map = new Map<string, View[]>();
  for (const v of views)
    map.set(courseKey(v.row), [...(map.get(courseKey(v.row)) || []), v]);
  return [...map.entries()].map(([key, slots]) => {
    const first = slots[0].row;
    const linked = new Set(slots.map((v) => v.row.subjectId));
    const suggested = slots.find((v) => v.row.suggestedSubjectId)?.row;
    return {
      key,
      label: first.baseLabel || first.label,
      code: first.code,
      component: componentText(first),
      track:
        first.track && first.track !== "core"
          ? first.placeholder
            ? `${first.track} slot`
            : first.track
          : null,
      slots: slots.sort(
        (a, b) =>
          a.row.weekday - b.row.weekday ||
          a.row.startTime.localeCompare(b.row.startTime),
      ),
      subjectId: linked.size === 1 ? first.subjectId : null,
      mixed: linked.size > 1,
      suggestion: suggested?.suggestedSubjectId || null,
      suggestionSource: suggested?.suggestionSource || null,
      needsReview: slots.some((v) => v.problems.length),
      notes: [...new Set(slots.flatMap((v) => v.notes))],
    };
  });
}

function view(
  row: DraftRow,
  choices: Record<string, string>,
  taken: Record<string, boolean>,
): View {
  const notes = row.issues.map((i) =>
    i === "component_missing"
      ? `No ${row.component || "lab or tutorial"} subject matches ${row.baseLabel}. Add one or choose another`
      : issueText[i] || i,
  );
  if (!row.include)
    return {
      row,
      included: false,
      reason: row.exclusionReason || "Excluded",
      needsChoice: false,
      problems: [],
      notes,
    };
  if (row.familyKey && taken[row.familyKey] === false)
    return {
      row,
      included: false,
      reason: `Not one of your ${row.track === "honours" ? "honours courses" : row.track + "s"}`,
      needsChoice: false,
      problems: [],
      notes,
    };
  const choice = row.choiceKey ? choices[row.choiceKey] : undefined;
  if (row.choiceKey && choice !== undefined && choice !== row.choiceLabel)
    return {
      row,
      included: false,
      reason:
        choice === "none"
          ? "You don't take this"
          : row.choiceKey.startsWith("group:")
            ? "Not your group"
            : row.choiceKey.startsWith("teacher:")
              ? "Not your teacher's group"
              : "Not your room",
      needsChoice: false,
      problems: [],
      notes,
    };
  const problems = [];
  const needsChoice = Boolean(row.choiceKey && choice === undefined);
  if (needsChoice)
    problems.push(
      row.choiceKey?.startsWith("group:")
        ? "Choose your group"
        : row.choiceKey?.startsWith("teacher:")
          ? "Choose your teacher"
          : "Choose your room",
    );
  if (!row.subjectId) problems.push("Choose a subject");
  if (!row.startTime || !row.endTime || row.endTime <= row.startTime)
    problems.push("Check this time");
  return { row, included: true, reason: null, needsChoice, problems, notes };
}

export function TimetableImport({
  subjects,
  onAddSubject,
  onClose,
}: {
  subjects: Subject[];
  onAddSubject: () => void;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const [reading, setReading] = useState<TimetableReading | null>(null);
  const [draft, setDraft] = useState<TimetableDraft | null>(null);
  const [rows, setRows] = useState<DraftRow[]>([]);
  const [choices, setChoices] = useState<Record<string, string>>({});
  // Electives, honours and minor courses the student takes (by course family).
  const [taken, setTaken] = useState<Record<string, boolean>>({});
  const [focus, setFocus] = useState<string | null>(null);
  const [pane, setPane] = useState<"draft" | "original">("draft");
  const [mode, setMode] = useState<"add" | "replace">("add");
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [acknowledged, setAcknowledged] = useState({
    overlaps: false,
    removals: false,
  });
  const [saved, setSaved] = useState<{
    slots: number;
    subjects: number;
  } | null>(null);
  const [leaving, setLeaving] = useState(false);
  const confirmKey = useRef<{ payload: string; key: string } | null>(null);
  const added = useRef(0);

  const urls = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);
  useEffect(() => () => urls.forEach((u) => URL.revokeObjectURL(u)), [urls]);
  // An unconfirmed draft lives only in this tab; warn before a refresh discards it.
  useEffect(() => {
    if (!draft || saved) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [draft, saved]);

  const byId = useMemo(
    () => new Map(subjects.map((s) => [s.id, s])),
    [subjects],
  );
  const sortedSubjects = useMemo(
    () =>
      [...subjects].sort(
        (a, b) => a.name.localeCompare(b.name) || a.kind.localeCompare(b.kind),
      ),
    [subjects],
  );
  const views = useMemo(
    () =>
      rows.map((r) => {
        const v = view(r, choices, taken);
        // A subject deleted during review must be linked again.
        if (r.subjectId && !byId.has(r.subjectId) && v.included)
          v.problems.push("Choose a subject");
        return v;
      }),
    [rows, choices, taken, byId],
  );

  const interpret = useMutation({
    mutationFn: (r: TimetableReading) =>
      api<TimetableDraft>("/timetable-imports/interpret", "POST", {
        pages: r.pages.map((p) => ({
          id: p.id,
          layout: p.layout,
          header: p.header,
        })),
        cells: r.pages.flatMap((p) =>
          p.cells.map((c) => ({
            id: c.id,
            page: c.page,
            weekday: c.weekday,
            start: c.start,
            end: c.end,
            lines: c.lines,
            bbox: c.bbox,
            spansDays: c.spansDays,
            narrow: c.narrow,
            clippedTop: Boolean(c.clippedTop),
            clippedBottom: Boolean(c.clippedBottom),
            unsure: Boolean(c.unsure),
          })),
        ),
      }),
    onSuccess: (d) => {
      setDraft(d);
      setRows(d.rows);
      setChoices({});
      setTaken(Object.fromEntries(d.families.map((f) => [f.key, f.selected])));
      setSummary(null);
    },
  });
  const extract = useMutation({
    mutationFn: () => {
      const form = new FormData();
      files.forEach((f) => form.append("files", f, f.name));
      return api<TimetableReading>("/timetable-imports/extract", "POST", form);
    },
    onSuccess: (r) => {
      setReading(r);
      interpret.mutate(r);
    },
  });

  function choose(list: FileList | null) {
    if (!list?.length) return;
    const next = [...files, ...Array.from(list)];
    const pdfs = next.filter((f) => f.type === "application/pdf");
    const pictures = next.filter((f) =>
      ["image/png", "image/jpeg", "image/webp"].includes(f.type),
    );
    if (pdfs.length + pictures.length !== next.length)
      return setFileError(
        "Choose the timetable PDF or scheduler screenshots (PNG, JPEG or WebP)",
      );
    if (pdfs.length && next.length > 1)
      return setFileError(
        "Upload the timetable PDF, or scheduler screenshots, not both",
      );
    if (pictures.length > 4)
      return setFileError("Upload at most four scheduler screenshots");
    if (next.some((f) => f.size > 10 * MB))
      return setFileError("Each file must be 10 MB or smaller");
    if (next.reduce((n, f) => n + f.size, 0) > 20 * MB)
      return setFileError("Uploads are limited to 20 MB in total");
    setFileError(null);
    setFiles(next);
  }
  const move = (i: number, by: number) => {
    const next = [...files];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    setFiles(next);
  };

  const update = (id: string, patch: Partial<DraftRow>) => {
    setRows((all) => all.map((r) => (r.id === id ? { ...r, ...patch } : r)));
    setSummary(null);
  };
  const updateMany = (ids: Set<string>, patch: Partial<DraftRow>) => {
    setRows((all) => all.map((r) => (ids.has(r.id) ? { ...r, ...patch } : r)));
    setSummary(null);
  };

  const ready = views.filter((v) => v.included && !v.problems.length);
  const excluded = views.filter((v) => !v.included);
  const included = useMemo(
    () =>
      courses(views.filter((v) => v.included)).map((c) =>
        // A subject deleted while reviewing must be linked again.
        c.subjectId && !byId.has(c.subjectId) ? { ...c, subjectId: null } : c,
      ),
    [views, byId],
  );
  const attention = included.filter((c) => c.needsReview);
  const done = included
    .filter((c) => !c.needsReview)
    .sort((a, b) =>
      (byId.get(a.subjectId!)?.name || "").localeCompare(
        byId.get(b.subjectId!)?.name || "",
      ),
    );
  const unlinked = included.filter((c) => !c.subjectId);
  const suggestions = unlinked.filter(
    (c) => c.suggestion && byId.has(c.suggestion),
  );
  // Bulk exclusion never discards a course that still has a suggested link to review.
  const unmatched = unlinked.filter((c) => !suggestions.includes(c));
  const rowIds = (list: Course[]) =>
    new Set(list.flatMap((c) => c.slots.map((v) => v.row.id)));
  const choiceGroups = useMemo(() => {
    const groups = new Map<
      string,
      { key: string; title: string; options: Map<string, DraftRow[]> }
    >();
    for (const r of rows) {
      if (!r.choiceKey || !r.include) continue;
      if (r.familyKey && taken[r.familyKey] === false) continue;
      const g = groups.get(r.choiceKey) || {
        key: r.choiceKey,
        title: r.choiceKey.startsWith("group:")
          ? `${r.baseLabel}: which group are you in?`
          : r.choiceKey.startsWith("teacher:")
            ? `${r.baseLabel}: whose group are you in?`
            : `${r.baseLabel} on ${days[r.weekday - 1]} at ${r.startTime}: which room?`,
        options: new Map<string, DraftRow[]>(),
      };
      const label = r.choiceLabel || r.label;
      g.options.set(label, [...(g.options.get(label) || []), r]);
      groups.set(r.choiceKey, g);
    }
    return [...groups.values()];
  }, [rows, taken]);
  const blocked = views.filter((v) => v.included && v.problems.length);
  // A mismatch notice stays until the student includes that sheet's classes anyway.
  const mismatches =
    draft?.documents.filter(
      (d) =>
        d.mismatch &&
        rows.some((r) => r.page === d.page && r.exclusionReason === d.mismatch),
    ) || [];

  function payload(dryRun: boolean) {
    const slots = views
      .filter((v) => v.included)
      .map(({ row }) => ({
        subjectId: row.subjectId as string,
        weekday: Number(row.weekday),
        startTime: row.startTime,
        endTime: row.endTime,
        location: row.location?.trim() || null,
        instructor: null,
      }));
    const ids = [...new Set(slots.map((s) => s.subjectId))];
    return {
      mode,
      dryRun,
      method: reading?.method || "pdf_text",
      profileRevision: draft?.profileRevision,
      subjects: ids.map((id) => ({ id, revision: byId.get(id)?.revision })),
      slots,
      acknowledgeOverlaps: dryRun ? false : acknowledged.overlaps,
    };
  }
  const conflict = async () => {
    await client.invalidateQueries({ queryKey: ["subjects"] });
    await client.invalidateQueries({ queryKey: ["me"] });
  };
  const preview = useMutation({
    mutationFn: (m: "add" | "replace") =>
      api<{ summary: ImportSummary }>("/timetable-imports/confirm", "POST", {
        ...payload(true),
        mode: m,
      }),
    onSuccess: (r) => {
      setSummary(r.summary);
      setAcknowledged({ overlaps: false, removals: false });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) void conflict();
    },
  });
  const save = useMutation({
    mutationFn: () => {
      const body = payload(false);
      const text = JSON.stringify(body);
      // Retrying the same reviewed payload reuses its key; any edit starts a new confirmation.
      if (confirmKey.current?.payload !== text)
        confirmKey.current = { payload: text, key: crypto.randomUUID() };
      return api<{
        summary: ImportSummary;
        subjects: { id: string }[];
      }>("/timetable-imports/confirm", "POST", body, {
        idempotencyKey: confirmKey.current.key,
      });
    },
    onSuccess: async (r) => {
      setSaved({
        slots: r.summary.added.length + r.summary.updated.length,
        subjects: r.subjects.length,
      });
      await client.invalidateQueries({ queryKey: ["subjects"] });
      await Promise.all(
        r.subjects.map((s) =>
          client.invalidateQueries({ queryKey: ["timetable", s.id] }),
        ),
      );
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) {
        setSummary(null);
        void conflict();
      }
    },
  });

  const close = () => {
    if (draft && !saved && !leaving) setLeaving(true);
    else onClose();
  };
  const stage = saved
    ? "done"
    : draft
      ? summary
        ? "summary"
        : "review"
      : extract.isPending
        ? "reading"
        : interpret.isPending
          ? "organizing"
          : "choose";

  const openChoices = choiceGroups.filter(
    (g) => choices[g.key] === undefined,
  ).length;
  const counts = [
    `${ready.length} ready`,
    unlinked.length &&
      `${unlinked.length} ${unlinked.length === 1 ? "course needs" : "courses need"} a subject`,
    openChoices &&
      `${openChoices} group ${openChoices === 1 ? "choice" : "choices"} left`,
    excluded.length && `${excluded.length} not included`,
  ].filter(Boolean);

  return (
    <Dialog
      open
      className="import-dialog"
      onOpenChange={(v) => {
        if (!v) close();
      }}
      title="Upload timetable"
      description="Upload your department's timetable PDF, or screenshots of the Somaiya roster scheduler. Nothing is saved until you confirm."
    >
      {leaving && (
        <div className="import-leave" role="alert">
          <p>
            Discard this draft? Your edits are not saved until you confirm the
            timetable.
          </p>
          <Button variant="outline" size="sm" onClick={() => setLeaving(false)}>
            Keep reviewing
          </Button>
          <Button variant="destructive" size="sm" onClick={onClose}>
            Discard draft
          </Button>
        </div>
      )}
      {stage === "choose" && (
        <>
          <div className="dialog-body import-choose">
            <label className="drop-zone">
              <FileUp size={26} />
              <strong>Choose your timetable</strong>
              <span>
                The timetable PDF, or up to four scheduler screenshots
              </span>
              <input
                type="file"
                multiple
                accept="application/pdf,image/png,image/jpeg,image/webp"
                onChange={(e) => {
                  choose(e.target.files);
                  e.target.value = "";
                }}
              />
            </label>
            {fileError && (
              <p className="error-text" role="alert">
                {fileError}
              </p>
            )}
            {files.length > 0 && (
              <ol className="upload-list">
                {files.map((f, i) => (
                  <li key={f.name + i}>
                    {f.type.startsWith("image/") ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={urls[i]} alt={"Picture " + (i + 1)} />
                    ) : (
                      <span className="file-badge">PDF</span>
                    )}
                    <span className="upload-name">
                      {f.name}
                      <small>{(f.size / MB).toFixed(1)} MB</small>
                    </span>
                    {files.length > 1 && (
                      <>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={"Move " + f.name + " up"}
                          disabled={i === 0}
                          onClick={() => move(i, -1)}
                        >
                          <ArrowUp size={15} />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={"Move " + f.name + " down"}
                          disabled={i === files.length - 1}
                          onClick={() => move(i, 1)}
                        >
                          <ArrowDown size={15} />
                        </Button>
                      </>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={"Remove " + f.name}
                      onClick={() => setFiles(files.filter((_, n) => n !== i))}
                    >
                      <X size={15} />
                    </Button>
                  </li>
                ))}
              </ol>
            )}
            <ul className="upload-kinds">
              <li>
                <strong>Timetable PDF</strong> shared by your department (the
                class timetable with Monday–Friday columns). A scan or a clear,
                uncropped picture of it also works; check the text it reads.
              </li>
              <li>
                <strong>Somaiya roster scheduler screenshots</strong>: open My
                Scheduler, choose <em>Week</em>, and take screenshots while
                scrolling so every hour appears in at least one (usually three).
              </li>
            </ul>
            <p className="form-help">
              Files are read on DueCare&apos;s server and are not stored. Only
              course names may be sent to DueCare&apos;s AI provider, to suggest
              which of your subjects they belong to.
            </p>
            <ErrorNotice error={extract.error} />
            <ErrorNotice
              error={interpret.error}
              retry={reading ? () => interpret.mutate(reading) : undefined}
            />
          </div>
          <div className="dialog-footer">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              disabled={!files.length}
              onClick={() => {
                interpret.reset();
                extract.mutate();
              }}
            >
              Read timetable
            </Button>
          </div>
        </>
      )}
      {(stage === "reading" || stage === "organizing") && (
        <div className="dialog-body import-progress" role="status">
          <ol>
            <li className={stage === "reading" ? "active" : "done"}>
              {stage === "reading" ? (
                <span className="spinner" />
              ) : (
                <Check size={16} />
              )}
              Reading your timetable
            </li>
            <li className={stage === "organizing" ? "active" : ""}>
              {stage === "organizing" && <span className="spinner" />}
              Organizing your timetable
            </li>
          </ol>
        </div>
      )}
      {(stage === "review" || stage === "summary") && draft && reading && (
        <>
          <div className="import-tabs" role="tablist">
            {(["draft", "original"] as const).map((p) => (
              <button
                key={p}
                role="tab"
                aria-selected={pane === p}
                onClick={() => setPane(p)}
              >
                {p === "draft" ? "Draft" : "Original"}
              </button>
            ))}
          </div>
          <div className="import-review" data-pane={pane}>
            <div className="import-source" aria-label="Original timetable">
              {reading.pages.map((p, i) => {
                const src = p.preview || urls[i];
                const hit = rows.find((r) => r.id === focus && r.page === p.id);
                return (
                  <figure key={p.id}>
                    <figcaption>
                      {p.source}
                      {p.visible ? ` · shows ${p.visible}` : ""}
                    </figcaption>
                    {src && (
                      <div className="source-page">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={src} alt={p.source} />
                        {hit?.bbox && (
                          <span
                            className="source-hit"
                            ref={(el) =>
                              el?.scrollIntoView({ block: "nearest" })
                            }
                            style={{
                              left: hit.bbox[0] * 100 + "%",
                              top: hit.bbox[1] * 100 + "%",
                              width: (hit.bbox[2] - hit.bbox[0]) * 100 + "%",
                              height: (hit.bbox[3] - hit.bbox[1]) * 100 + "%",
                            }}
                          />
                        )}
                      </div>
                    )}
                  </figure>
                );
              })}
            </div>
            <div className="import-draft">
              {stage === "review" ? (
                <>
                  <p className="import-counts" aria-live="polite">
                    {counts.join(" · ")}
                    {draft.batch ? ` · Your batch: ${draft.batch}` : ""}
                  </p>
                  <p className="text-xs text-secondary">
                    This draft is only in this tab. Leaving or refreshing
                    discards it.
                  </p>
                  {draft.ai.unavailable && (
                    <p className="import-note">
                      Subject suggestions are unavailable right now. Link
                      subjects yourself, or close and try again later.
                    </p>
                  )}
                  {reading.pages
                    .flatMap((p) => p.issues)
                    .map((issue, i) => (
                      <p key={i} className="import-note">
                        {issue}
                      </p>
                    ))}
                  {mismatches.map((d) => (
                    <div key={d.page} className="import-note warn">
                      <p>
                        {d.mismatch} ({d.classLabel}), not your profile&apos;s
                        class. Its classes are excluded.
                      </p>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          updateMany(
                            new Set(
                              rows
                                .filter(
                                  (r) =>
                                    r.page === d.page &&
                                    r.exclusionReason === d.mismatch &&
                                    !r.otherBatch,
                                )
                                .map((r) => r.id),
                            ),
                            { include: true, exclusionReason: null },
                          )
                        }
                      >
                        Include them anyway
                      </Button>
                    </div>
                  ))}
                  <div className="import-actions">
                    {suggestions.length > 0 && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          const target = new Map(
                            suggestions.flatMap((c) =>
                              c.slots.map((v) => [v.row.id, c.suggestion]),
                            ),
                          );
                          setRows((all) =>
                            all.map((r) =>
                              target.has(r.id)
                                ? {
                                    ...r,
                                    subjectId: target.get(r.id) || null,
                                    link: "accepted",
                                  }
                                : r,
                            ),
                          );
                          setSummary(null);
                        }}
                      >
                        <Check size={15} />
                        Accept {suggestions.length} suggested{" "}
                        {suggestions.length === 1 ? "link" : "links"}
                      </Button>
                    )}
                    {unmatched.length > 0 && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          updateMany(rowIds(unmatched), {
                            include: false,
                            exclusionReason: "Excluded by you",
                          })
                        }
                      >
                        <X size={15} />
                        Exclude {unmatched.length}{" "}
                        {unmatched.length === 1 ? "course" : "courses"} without
                        a subject
                      </Button>
                    )}
                    <Button size="sm" variant="outline" onClick={onAddSubject}>
                      <Plus size={15} />
                      Add subject
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        added.current += 1;
                        setRows([
                          ...rows,
                          {
                            id: "m" + added.current,
                            cellId: null,
                            page: null,
                            bbox: null,
                            sourceText: "Added by you",
                            label: "",
                            baseLabel: "",
                            code: null,
                            group: null,
                            batches: [],
                            component: null,
                            weekday: 1,
                            startTime: "",
                            endTime: "",
                            location: null,
                            instructor: null,
                            include: true,
                            otherBatch: false,
                            exclusionReason: null,
                            subjectId: null,
                            link: "manual",
                            suggestedSubjectId: null,
                            suggestionSource: null,
                            choiceKey: null,
                            choiceLabel: null,
                            issues: [],
                          },
                        ]);
                      }}
                    >
                      <Plus size={15} />
                      Add a missed slot
                    </Button>
                  </div>
                  {draft.families.length > 0 && (
                    <section className="import-section">
                      <h3>Your electives, honours and minor</h3>
                      <p className="text-xs text-secondary">
                        Tick the ones you take. Each includes its theory, lab
                        and tutorial slots; the rest are left out. Ticked ones
                        match your subjects.
                      </p>
                      {(["elective", "honours", "minor"] as const).map(
                        (track) => {
                          const list = draft.families.filter(
                            (f) => f.track === track,
                          );
                          if (!list.length) return null;
                          return (
                            <fieldset key={track} className="family-list">
                              <legend>
                                {track === "honours"
                                  ? "Honours"
                                  : track === "minor"
                                    ? "Minor"
                                    : "Electives"}
                              </legend>
                              {list.map((f) => (
                                <label key={f.key}>
                                  <input
                                    type="checkbox"
                                    checked={taken[f.key] ?? false}
                                    onChange={(e) => {
                                      setTaken((t) => ({
                                        ...t,
                                        [f.key]: e.target.checked,
                                      }));
                                      setSummary(null);
                                    }}
                                  />
                                  <span>
                                    {f.name}
                                    <small>
                                      {f.slots}{" "}
                                      {f.slots === 1 ? "slot" : "slots"}
                                    </small>
                                  </span>
                                </label>
                              ))}
                            </fieldset>
                          );
                        },
                      )}
                    </section>
                  )}
                  {choiceGroups.length > 0 && (
                    <section className="import-section">
                      <h3>Your groups</h3>
                      <p className="text-xs text-secondary">
                        These classes run as parallel groups, teachers or rooms.
                        Choose the one you attend; the others are left out.
                      </p>
                      <div className="choice-grid">
                        {choiceGroups.map((g) => (
                          <label key={g.key} className="field">
                            <span>{g.title}</span>
                            <select
                              value={choices[g.key] ?? ""}
                              onChange={(e) => {
                                const value = e.target.value;
                                setChoices((c) => {
                                  const next = { ...c };
                                  if (value) next[g.key] = value;
                                  else delete next[g.key];
                                  return next;
                                });
                                setSummary(null);
                              }}
                            >
                              <option value="">Choose…</option>
                              {[...g.options.keys()].map((o) => (
                                <option key={o} value={o}>
                                  {o}
                                </option>
                              ))}
                              <option value="none">
                                I don&apos;t take this
                              </option>
                            </select>
                          </label>
                        ))}
                      </div>
                    </section>
                  )}
                  {attention.length > 0 && (
                    <section className="import-section">
                      <h3>Needs your review ({attention.length})</h3>
                      {attention.map((c) => (
                        <CourseCard
                          key={c.key}
                          course={c}
                          subjects={sortedSubjects}
                          byId={byId}
                          onFocus={setFocus}
                          update={update}
                          updateMany={updateMany}
                        />
                      ))}
                    </section>
                  )}
                  {done.length > 0 && (
                    <section className="import-section">
                      <h3>Ready ({done.length})</h3>
                      {done.map((c) => (
                        <CourseCard
                          key={c.key}
                          course={c}
                          subjects={sortedSubjects}
                          byId={byId}
                          onFocus={setFocus}
                          update={update}
                          updateMany={updateMany}
                        />
                      ))}
                    </section>
                  )}
                  <ErrorNotice error={preview.error} />
                  <ErrorNotice error={save.error} />
                </>
              ) : (
                summary && (
                  <SaveSummary
                    summary={summary}
                    mode={mode}
                    setMode={(m) => {
                      setMode(m);
                      preview.mutate(m);
                    }}
                    pending={preview.isPending}
                    acknowledged={acknowledged}
                    setAcknowledged={setAcknowledged}
                    error={save.error}
                  />
                )
              )}
            </div>
          </div>
          <div className="dialog-footer">
            {stage === "summary" ? (
              <>
                <Button
                  key="back"
                  variant="outline"
                  onClick={() => setSummary(null)}
                >
                  Back to draft
                </Button>
                <Button
                  key="confirm"
                  disabled={
                    save.isPending ||
                    preview.isPending ||
                    summary!.added.length +
                      summary!.updated.length +
                      summary!.removed.length ===
                      0 ||
                    (summary!.overlaps.length > 0 && !acknowledged.overlaps) ||
                    (summary!.removed.length > 0 && !acknowledged.removals)
                  }
                  onClick={() => save.mutate()}
                >
                  Confirm timetable
                </Button>
              </>
            ) : (
              <>
                <Button
                  key="restart"
                  variant="ghost"
                  onClick={() => interpret.mutate(reading)}
                  disabled={interpret.isPending}
                  title="Rebuild the draft from the original, discarding your edits"
                >
                  <RotateCcw size={15} />
                  Start over
                </Button>
                <Button key="cancel" variant="outline" onClick={close}>
                  Cancel
                </Button>
                <Button
                  key="review"
                  disabled={
                    preview.isPending ||
                    blocked.length > 0 ||
                    !views.some((v) => v.included)
                  }
                  onClick={() => preview.mutate(mode)}
                >
                  {attention.length
                    ? `${attention.length} ${attention.length === 1 ? "course needs" : "courses need"} review`
                    : "Review save"}
                </Button>
              </>
            )}
          </div>
        </>
      )}
      {stage === "done" && saved && (
        <>
          <div className="dialog-body import-done" role="status">
            <Check size={30} />
            <h3>Timetable saved</h3>
            <p>
              {saved.slots} weekly {saved.slots === 1 ? "slot" : "slots"} saved
              across {saved.subjects}{" "}
              {saved.subjects === 1 ? "subject" : "subjects"}. Open a
              subject&apos;s Timetable to see or adjust them.
            </p>
          </div>
          <div className="dialog-footer">
            <Button onClick={onClose}>Done</Button>
          </div>
        </>
      )}
    </Dialog>
  );
}

function CourseCard({
  course: c,
  subjects,
  byId,
  onFocus,
  update,
  updateMany,
}: {
  course: Course;
  subjects: Subject[];
  byId: Map<string, Subject>;
  onFocus: (id: string) => void;
  update: (id: string, patch: Partial<DraftRow>) => void;
  updateMany: (ids: Set<string>, patch: Partial<DraftRow>) => void;
}) {
  const ids = new Set(c.slots.map((v) => v.row.id));
  const suggestion =
    !c.subjectId && c.suggestion ? byId.get(c.suggestion) : undefined;
  const id = "course-" + c.slots[0].row.id;
  return (
    <fieldset className={"import-row" + (c.needsReview ? " needs" : "")}>
      <legend>
        <strong>{c.label || "New slot"}</strong>
        <span>
          {[c.code, c.track, c.component].filter(Boolean).join(" · ")}
          {" · "}
          {c.slots.length} weekly {c.slots.length === 1 ? "slot" : "slots"}
        </span>
      </legend>
      <div className="course-subject">
        <label htmlFor={id}>Subject</label>
        <select
          id={id}
          value={c.subjectId || ""}
          onChange={(e) =>
            updateMany(ids, {
              subjectId: e.target.value || null,
              link: e.target.value ? "manual" : "none",
            })
          }
        >
          <option value="">
            {c.mixed ? "Different subjects. Choose one…" : "Choose a subject…"}
          </option>
          {subjects.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} · {s.kind}
            </option>
          ))}
        </select>
      </div>
      {suggestion && (
        <p className="row-suggestion">
          Suggested: {suggestion.name} · {suggestion.kind}
          {c.suggestionSource === "ai" ? " (AI)" : ""}
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              updateMany(ids, { subjectId: suggestion.id, link: "accepted" })
            }
          >
            Use this
          </Button>
        </p>
      )}
      {!c.subjectId && (
        <CreateSubject
          course={c}
          subjects={subjects}
          onLinked={(subjectId) =>
            updateMany(ids, { subjectId, link: "manual" })
          }
        />
      )}
      <ul className="slot-lines">
        {c.slots.map((v) => (
          <SlotEditor
            key={v.row.id}
            v={v}
            onFocus={() => onFocus(v.row.id)}
            update={update}
          />
        ))}
      </ul>
      {c.notes.length > 0 && (
        <ul className="row-issues">
          {c.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}

function CreateSubject({
  course: c,
  subjects,
  onLinked,
}: {
  course: Course;
  subjects: Subject[];
  onLinked: (subjectId: string) => void;
}) {
  const client = useQueryClient();
  const first = c.slots[0].row;
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(c.label);
  const [kind, setKind] = useState<Subject["kind"]>(first.component || "lab");
  // The same name and kind is never created twice; link the existing subject instead.
  const existing = subjects.find(
    (s) => s.kind === kind && normalized(s.name) === normalized(name),
  );
  // A suggested match (initials, sibling component, AI) is offered before creating a near-repeat.
  const similar = c.suggestion
    ? subjects.find((s) => s.id === c.suggestion)
    : undefined;
  const create = useMutation({
    mutationFn: () =>
      api<Subject>("/subjects", "POST", {
        name: name.trim(),
        kind,
        code: c.code,
        // The printed label stays recognizable in later imports and source matching.
        aliases:
          c.label && normalized(c.label) !== normalized(name) ? [c.label] : [],
      }),
    onSuccess: async (subject) => {
      await client.invalidateQueries({ queryKey: ["subjects"] });
      onLinked(subject.id);
      setOpen(false);
    },
    onError: async (e) => {
      // Another tab may have just added it; refresh so the existing one can be linked.
      if (e instanceof ApiError && e.status === 409)
        await client.invalidateQueries({ queryKey: ["subjects"] });
    },
  });
  const id = "create-" + first.id;
  if (!open)
    return (
      <p className="row-suggestion">
        <span className="problem-line">Choose a subject</span>
        <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
          <Plus size={15} />
          Create subject from this
        </Button>
      </p>
    );
  return (
    <div className="create-subject">
      <div className="create-fields">
        <label htmlFor={id + "-name"}>
          <span>New subject name</span>
          <input
            id={id + "-name"}
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label htmlFor={id + "-kind"}>
          <span>Kind</span>
          <select
            id={id + "-kind"}
            value={kind}
            onChange={(e) => setKind(e.target.value as Subject["kind"])}
          >
            <option value="theory">Theory</option>
            <option value="lab">Lab</option>
            <option value="tutorial">Tutorial</option>
          </select>
        </label>
      </div>
      {c.label && normalized(c.label) !== normalized(name) && (
        <p className="text-xs text-secondary">
          “{c.label}” will be saved as another name for it
          {c.code ? `, with course code ${c.code}` : ""}.
        </p>
      )}
      {existing ? (
        <p className="row-suggestion">
          You already have {existing.name} · {existing.kind}.
          <Button
            size="sm"
            variant="outline"
            onClick={() => onLinked(existing.id)}
          >
            Use it
          </Button>
        </p>
      ) : similar ? (
        <p className="row-suggestion">
          This looks like your {similar.name} · {similar.kind}.
          <Button
            size="sm"
            variant="outline"
            onClick={() => onLinked(similar.id)}
          >
            Use it
          </Button>
        </p>
      ) : null}
      <div className="row-suggestion">
        <Button
          size="sm"
          disabled={!name.trim() || Boolean(existing) || create.isPending}
          onClick={() => create.mutate()}
        >
          Create and link {c.slots.length}{" "}
          {c.slots.length === 1 ? "slot" : "slots"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      <ErrorNotice error={create.error} />
    </div>
  );
}

function SlotEditor({
  v,
  onFocus,
  update,
}: {
  v: View;
  onFocus: () => void;
  update: (id: string, patch: Partial<DraftRow>) => void;
}) {
  const r = v.row;
  const tag = [r.batches.join(", "), r.choiceLabel].filter(Boolean).join(" · ");
  const problems = v.problems.filter((p) => p !== "Choose a subject");
  const name = `${days[r.weekday - 1]} ${r.startTime}`;
  return (
    <li onFocus={onFocus} onMouseEnter={onFocus} title={r.sourceText}>
      <div className="slot-fields">
        <select
          aria-label={"Day for " + name}
          value={r.weekday}
          onChange={(e) => update(r.id, { weekday: Number(e.target.value) })}
        >
          {days.map((d, n) => (
            <option key={d} value={n + 1}>
              {d}
            </option>
          ))}
        </select>
        <TimePicker
          quick={false}
          label={"Starts for " + name}
          value={r.startTime}
          onChange={(v) => update(r.id, { startTime: v })}
        />
        <TimePicker
          quick={false}
          label={"Ends for " + name}
          value={r.endTime}
          onChange={(v) => update(r.id, { endTime: v })}
        />
        <input
          aria-label={"Room for " + name}
          placeholder="Room"
          value={r.location || ""}
          onChange={(e) => update(r.id, { location: e.target.value })}
        />
        <Button
          variant="ghost"
          size="icon"
          aria-label={"Exclude " + name}
          title="Exclude this slot"
          onClick={() =>
            update(r.id, { include: false, exclusionReason: "Excluded by you" })
          }
        >
          <Trash2 size={15} />
        </Button>
      </div>
      {(tag || problems.length > 0) && (
        <p className="slot-meta">
          {tag && <span className="slot-tag">{tag}</span>}
          {problems.map((p) => (
            <span key={p} className="problem">
              {p}
            </span>
          ))}
        </p>
      )}
    </li>
  );
}

function SlotLine({ s }: { s: ImportSlotBrief }) {
  return (
    <li>
      <strong>{s.subjectName}</strong> {short(s.weekday)} {s.startTime}–
      {s.endTime}
      {s.location ? " · " + s.location : ""}
    </li>
  );
}

function SaveSummary({
  summary,
  mode,
  setMode,
  pending,
  acknowledged,
  setAcknowledged,
  error,
}: {
  summary: ImportSummary;
  mode: "add" | "replace";
  setMode: (m: "add" | "replace") => void;
  pending: boolean;
  acknowledged: { overlaps: boolean; removals: boolean };
  setAcknowledged: (a: { overlaps: boolean; removals: boolean }) => void;
  error: Error | null;
}) {
  const nothing =
    summary.added.length + summary.updated.length + summary.removed.length ===
    0;
  return (
    <div className="save-summary" aria-busy={pending}>
      <fieldset className="mode-choice">
        <legend>How should these slots be saved?</legend>
        <label>
          <input
            type="radio"
            name="mode"
            checked={mode === "add"}
            onChange={() => setMode("add")}
          />
          <span>
            Add to existing timetable
            <small>Keeps every slot already saved.</small>
          </span>
        </label>
        <label>
          <input
            type="radio"
            name="mode"
            checked={mode === "replace"}
            onChange={() => setMode("replace")}
          />
          <span>
            Replace timetable for these subjects
            <small>
              Removes their other saved slots. Subjects not in this import keep
              theirs.
            </small>
          </span>
        </label>
      </fieldset>
      {nothing && (
        <p className="import-note">
          Every slot is already saved. There is nothing new to add.
        </p>
      )}
      {summary.added.length > 0 && (
        <section>
          <h3>Will add ({summary.added.length})</h3>
          <ul>
            {summary.added.map((s, i) => (
              <SlotLine key={i} s={s} />
            ))}
          </ul>
        </section>
      )}
      {summary.updated.length > 0 && (
        <section>
          <h3>Will update room ({summary.updated.length})</h3>
          <ul>
            {summary.updated.map((s, i) => (
              <SlotLine key={i} s={s} />
            ))}
          </ul>
        </section>
      )}
      {summary.duplicates.length > 0 && (
        <details>
          <summary>
            Already saved, skipped ({summary.duplicates.length})
          </summary>
          <ul>
            {summary.duplicates.map((s, i) => (
              <SlotLine key={i} s={s} />
            ))}
          </ul>
        </details>
      )}
      {summary.removed.length > 0 && (
        <section className="warn">
          <h3>Will remove ({summary.removed.length})</h3>
          <ul>
            {summary.removed.map((s, i) => (
              <SlotLine key={i} s={s} />
            ))}
          </ul>
          <label className="ack">
            <input
              type="checkbox"
              checked={acknowledged.removals}
              onChange={(e) =>
                setAcknowledged({ ...acknowledged, removals: e.target.checked })
              }
            />
            I reviewed these removals
          </label>
        </section>
      )}
      {summary.overlaps.length > 0 && (
        <section className="warn">
          <h3>Overlapping classes ({summary.overlaps.length})</h3>
          <ul>
            {summary.overlaps.map((o, i) => (
              <li key={i}>
                {short(o.first.weekday)}: <strong>{o.first.subjectName}</strong>{" "}
                {o.first.startTime}–{o.first.endTime} overlaps{" "}
                <strong>{o.second.subjectName}</strong> {o.second.startTime}–
                {o.second.endTime}
              </li>
            ))}
          </ul>
          <p className="text-xs text-secondary">
            Go back to exclude or correct one, or keep both if they really
            overlap.
          </p>
          <label className="ack">
            <input
              type="checkbox"
              checked={acknowledged.overlaps}
              onChange={(e) =>
                setAcknowledged({ ...acknowledged, overlaps: e.target.checked })
              }
            />
            Keep overlapping classes
          </label>
        </section>
      )}
      <ErrorNotice error={error} />
    </div>
  );
}
