"use client";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, CalendarDays, FileUp, Pencil, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Subject, Slot } from "@/lib/types";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { Field, ErrorNotice } from "./ui/field";
import { TimetableImport } from "./timetable-import";
const schema = z.object({
  name: z.string().trim().min(1),
  kind: z.enum(["theory", "lab", "tutorial"]),
});
type Values = z.infer<typeof schema>;
function SubjectEditor({
  subject,
  onClose,
}: {
  subject?: Subject;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: subject?.name || "",
      kind: subject?.kind || "theory",
    },
  });
  const save = useMutation({
    mutationFn: (v: Values) =>
      api(
        subject ? "/subjects/" + subject.id : "/subjects",
        subject ? "PATCH" : "POST",
        {
          ...v,
          // Retain existing source-matching metadata when editing the simpler form.
          ...(subject
            ? {
                code: subject.code,
                aliases: subject.aliases,
                term: subject.term,
                classCode: subject.classCode,
              }
            : {}),
          revision: subject?.revision,
        },
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["subjects"] });
      await client.invalidateQueries({ queryKey: ["tasks"] });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
      title={subject ? "Edit subject" : "Add a subject"}
      description="Theory, lab, and tutorial subjects stay separate. Your profile batch applies to all of them."
    >
      <form onSubmit={form.handleSubmit((v) => save.mutate(v))}>
        <div className="dialog-body form-grid">
          <Field
            label="Subject name"
            id="name"
            error={form.formState.errors.name?.message}
          >
            <input id="name" required {...form.register("name")} />
          </Field>
          <Field label="Subject kind" id="kind">
            <select id="kind" {...form.register("kind")}>
              <option value="theory">Theory</option>
              <option value="lab">Lab</option>
              <option value="tutorial">Tutorial</option>
            </select>
          </Field>
          <ErrorNotice error={save.error} />
        </div>
        <div className="dialog-footer">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={save.isPending}>Save subject</Button>
        </div>
      </form>
    </Dialog>
  );
}
const days = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];
function Timetable({
  subject,
  onClose,
}: {
  subject: Subject;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["timetable", subject.id],
    queryFn: () =>
      api<{ slots: Slot[]; revision: number }>(
        "/subjects/" + subject.id + "/timetable",
      ),
  });
  const [draft, setDraft] = useState<Slot[] | null>(null);
  const slots = draft || query.data?.slots || [];
  const change = (i: number, key: string, value: string | number) =>
    setDraft(slots.map((s, n) => (n === i ? { ...s, [key]: value } : s)));
  const save = useMutation({
    mutationFn: () =>
      api("/subjects/" + subject.id + "/timetable", "PUT", {
        revision: query.data?.revision,
        slots: slots.map((s) => ({
          id: s.id,
          weekday: s.weekday,
          startTime: s.startTime,
          endTime: s.endTime,
          location: s.location || null,
          instructor: s.instructor || null,
          validFrom: s.validFrom || null,
          validUntil: s.validUntil || null,
        })),
      }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["subjects"] });
      await client.invalidateQueries({ queryKey: ["timetable", subject.id] });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
      title={subject.name + " timetable"}
      description="Optional weekly context in IST. Saving does not create attendance tasks."
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="dialog-body">
          <ErrorNotice error={query.error} retry={() => query.refetch()} />
          {query.isPending ? (
            <p role="status">Loading weekly slots…</p>
          ) : (
            <>
              {slots.length === 0 && (
                <p className="empty-small">
                  No weekly slots yet. Add your regular class or lab hours.
                </p>
              )}
              {slots.map((s, i) => (
                <fieldset key={s.id || i} className="slot">
                  <legend>Weekly slot {i + 1}</legend>
                  <div className="form-grid">
                    <Field id={"day" + i} label="Day">
                      <select
                        id={"day" + i}
                        value={s.weekday}
                        onChange={(e) =>
                          change(i, "weekday", Number(e.target.value))
                        }
                      >
                        {days.map((d, n) => (
                          <option key={d} value={n + 1}>
                            {d}
                          </option>
                        ))}
                      </select>
                    </Field>
                    {(["startTime", "endTime", "location"] as const).map(
                      (key) => (
                        <Field
                          key={key}
                          id={key + i}
                          label={
                            {
                              startTime: "Starts (IST)",
                              endTime: "Ends (IST)",
                              location: "Room / location",
                            }[key]
                          }
                        >
                          <input
                            id={key + i}
                            required={key === "startTime" || key === "endTime"}
                            type={key.endsWith("Time") ? "time" : "text"}
                            value={s[key] || ""}
                            onChange={(e) => change(i, key, e.target.value)}
                          />
                        </Field>
                      ),
                    )}
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setDraft(slots.filter((_, n) => n !== i))}
                  >
                    <Trash2 size={15} />
                    Remove slot
                  </Button>
                </fieldset>
              ))}
              <Button
                type="button"
                variant="outline"
                onClick={() =>
                  setDraft([
                    ...slots,
                    { weekday: 1, startTime: "", endTime: "" },
                  ])
                }
              >
                <Plus size={16} />
                Add weekly slot
              </Button>
            </>
          )}
          <ErrorNotice error={save.error} />
        </div>
        <div className="dialog-footer">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={save.isPending || query.isPending}>
            Save timetable
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
export function Subjects({
  subjects,
  batch,
}: {
  subjects: Subject[];
  batch?: string;
}) {
  const client = useQueryClient();
  const [editing, setEditing] = useState<Subject | null | undefined>(undefined);
  const [timetable, setTimetable] = useState<Subject | null>(null);
  const [deleting, setDeleting] = useState<Subject | null>(null);
  const [importing, setImporting] = useState(false);
  const remove = useMutation({
    mutationFn: (s: Subject) =>
      api("/subjects/" + s.id + "?revision=" + s.revision, "DELETE"),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["subjects"] });
      await client.invalidateQueries({ queryKey: ["tasks"] });
      await client.invalidateQueries({ queryKey: ["overview"] });
      setDeleting(null);
    },
  });
  return (
    <>
      <div className="section-bar">
        <div>
          <h2>Your subjects</h2>
          <p className="text-secondary">
            Batch {batch || "not set"} applies to every subject.
          </p>
        </div>
        <div className="section-actions">
          <Button variant="outline" onClick={() => setImporting(true)}>
            <FileUp size={16} />
            Upload timetable
          </Button>
          <Button onClick={() => setEditing(null)}>
            <Plus size={16} />
            Add subject
          </Button>
        </div>
      </div>
      {subjects.length === 0 ? (
        <div className="empty panel">
          <CalendarDays size={30} />
          <h3>A place for every subject</h3>
          <p>
            Add theory, lab, and tutorial subjects separately, then upload your
            timetable to fill in their weekly slots.
          </p>
        </div>
      ) : (
        <div className="subject-grid">
          {subjects.map((s) => (
            <article className="panel subject-panel" key={s.id}>
              <span className="kind-label">{s.kind}</span>
              <h3>{s.name}</h3>
              {(s.code || s.term) && (
                <p className="text-secondary text-sm">
                  {[s.code, s.term].filter(Boolean).join(" · ")}
                </p>
              )}
              {s.aliases.length > 0 && (
                <p className="text-sm">Also known as {s.aliases.join(", ")}</p>
              )}
              {s.classroomMappings?.map((m) => (
                <p
                  key={m.connectionId + m.externalCourseId}
                  className="text-xs text-secondary"
                >
                  Linked to Classroom: {m.courseName || m.externalCourseId}
                  {m.sourceAvailable ? "" : " (no longer available)"}
                </p>
              ))}
              <div className="subject-actions">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setTimetable(s)}
                >
                  <CalendarDays size={15} />
                  Timetable
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={"Edit " + s.name}
                  onClick={() => setEditing(s)}
                >
                  <Pencil size={15} />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={"Delete " + s.name}
                  onClick={() => setDeleting(s)}
                >
                  <Trash2 size={15} />
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}
      {importing && (
        // Stays mounted while a subject is added, so the draft survives.
        <TimetableImport
          subjects={subjects}
          onAddSubject={() => setEditing(null)}
          onClose={() => setImporting(false)}
        />
      )}
      {editing !== undefined && (
        <SubjectEditor
          subject={editing || undefined}
          onClose={() => setEditing(undefined)}
        />
      )}
      {timetable && (
        <Timetable subject={timetable} onClose={() => setTimetable(null)} />
      )}
      {deleting && (
        <Dialog
          open
          title="Delete subject?"
          description="Its timetable will be removed. Your tasks and history will remain, with the subject unlinked."
          onOpenChange={(v) => {
            if (!v) setDeleting(null);
          }}
        >
          <div className="dialog-body">
            <p>{deleting.name}</p>
            <ErrorNotice error={remove.error} />
          </div>
          <div className="dialog-footer">
            <Button variant="outline" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => remove.mutate(deleting)}
            >
              Delete subject
            </Button>
          </div>
        </Dialog>
      )}
    </>
  );
}
