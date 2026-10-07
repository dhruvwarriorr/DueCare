"use client";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, datetimeFields, localTime, utcTime } from "@/lib/api";
import type { Task, Subject } from "@/lib/types";
import { Dialog } from "./ui/dialog";
import { Field, ErrorNotice } from "./ui/field";
import { Button } from "./ui/button";
const schema = z
  .object({
    title: z.string().trim().min(1, "Add a title").max(300),
    type: z.enum(["assignment", "test"]),
  })
  .catchall(z.string());
type Values = z.infer<typeof schema>;
const timeLabels: Record<string, string> = {
  dueAt: "Exact cutoff",
  submissionOpensAt: "Submission opens",
  availabilityOpensAt: "Quiz window opens",
  availabilityClosesAt: "Quiz window closes",
  loginByAt: "Login by",
  reportingAt: "Report at",
  startsAt: "Test starts",
  endsAt: "Test ends",
};
export function TaskEditor({
  task,
  subjects,
  onClose,
}: {
  task?: Task;
  subjects: Subject[];
  onClose: () => void;
}) {
  const client = useQueryClient();
  const defaults: Values = {
    title: task?.title || "",
    type: task?.type || "assignment",
  };
  const optional = [
    "subjectId",
    "instructions",
    "notes",
    "estimatedEffortMinutes",
    "priorityOverride",
    "assessmentLabel",
    "deliverableLabel",
    "location",
    "syllabus",
    "permittedTools",
    "preparationInstructions",
    "dueDate",
    "dateWindowStart",
    "dateWindowEnd",
    "durationMinutes",
    "timingMode",
  ] as const;
  for (const field of optional)
    defaults[field] = task?.[field] == null ? "" : String(task[field]);
  defaults.timingMode = task?.timingMode || "undated";
  for (const field of datetimeFields)
    defaults[field] =
      field === "dueAt" && task?.dueDate ? "" : localTime(task?.[field]);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: defaults,
  });
  const type = useWatch({ control: form.control, name: "type" });
  const mode = useWatch({ control: form.control, name: "timingMode" });
  const save = useMutation({
    mutationFn: async (v: Values) => {
      const body: Record<string, unknown> = { ...v };
      for (const field of datetimeFields) body[field] = utcTime(v[field] || "");
      for (const field of optional)
        if (!v[field])
          body[field] = ["instructions", "notes"].includes(field) ? "" : null;
      body.timingMode = v.timingMode || "undated";
      for (const field of ["estimatedEffortMinutes", "durationMinutes"])
        body[field] = v[field] ? Number(v[field]) : null;
      if (
        v.timingMode === "fixed_session" ||
        v.timingMode === "attempt_window" ||
        v.dueDate
      )
        body.dueAt = null;
      if (task) body.revision = task.revision;
      return api<Task>(
        task ? "/tasks/" + task.id : "/tasks",
        task ? "PATCH" : "POST",
        body,
      );
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["tasks"] });
      await client.invalidateQueries({ queryKey: ["overview"] });
      await client.invalidateQueries({ queryKey: ["history"] });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
      title={task ? "Edit task" : "Add a task"}
      description="Only a title and type are required. All times use IST."
    >
      <form onSubmit={form.handleSubmit((v) => save.mutate(v))}>
        <div className="dialog-body">
          <Field
            id="task-title"
            label="Title"
            error={form.formState.errors.title?.message}
          >
            <input
              id="task-title"
              autoFocus
              required
              {...form.register("title")}
            />
          </Field>
          <div className="form-grid">
            <Field id="task-type" label="Type">
              <select id="task-type" {...form.register("type")}>
                <option value="assignment">Assignment</option>
                <option value="test">Test</option>
              </select>
            </Field>
            <Field id="task-subject" label="Subject">
              <select id="task-subject" {...form.register("subjectId")}>
                <option value="">No subject</option>
                {subjects.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} · {s.kind}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="priority" label="Priority">
              <select id="priority" {...form.register("priorityOverride")}>
                <option value="">Based on deadline</option>
                {["low", "medium", "high", "critical"].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </Field>
            <Field id="effort" label="Estimated effort (minutes)">
              <input
                id="effort"
                type="number"
                min="1"
                {...form.register("estimatedEffortMinutes")}
              />
            </Field>
          </div>
          <Field id="instructions" label="Instructions">
            <textarea
              id="instructions"
              rows={3}
              {...form.register("instructions")}
            />
          </Field>
          <Field id="notes" label="Personal notes">
            <textarea id="notes" rows={2} {...form.register("notes")} />
          </Field>
          <details className="advanced" open={Boolean(task)}>
            <summary>Timing and assessment details</summary>
            <div className="form-grid mt-4">
              <Field id="timing-mode" label="Timing">
                <select id="timing-mode" {...form.register("timingMode")}>
                  <option value="undated">Undated / simple deadline</option>
                  <option value="deadline_only">Deadline only</option>
                  {type === "test" && (
                    <>
                      <option value="fixed_session">Fixed-session test</option>
                      <option value="attempt_window">
                        Online attempt window
                      </option>
                    </>
                  )}
                  <option value="unresolved">Exact time unresolved</option>
                </select>
              </Field>
              <Field
                id="due-date"
                label={
                  type === "assignment"
                    ? "Date-only deadline"
                    : "Test date (time unknown)"
                }
              >
                <input
                  id="due-date"
                  type="date"
                  {...form.register("dueDate")}
                />
              </Field>
              {datetimeFields.map((field) => (
                <Field key={field} id={field} label={timeLabels[field]}>
                  <input
                    id={field}
                    type="datetime-local"
                    {...form.register(field)}
                  />
                </Field>
              ))}
              <Field id="dateWindowStart" label="Unresolved date range begins">
                <input
                  id="dateWindowStart"
                  type="date"
                  {...form.register("dateWindowStart")}
                />
              </Field>
              <Field id="dateWindowEnd" label="Unresolved date range ends">
                <input
                  id="dateWindowEnd"
                  type="date"
                  {...form.register("dateWindowEnd")}
                />
              </Field>
              {(
                [
                  "assessmentLabel",
                  "deliverableLabel",
                  "location",
                  "durationMinutes",
                  "syllabus",
                  "permittedTools",
                  "preparationInstructions",
                ] as const
              ).map((field) => (
                <Field
                  key={field}
                  id={field}
                  label={
                    {
                      assessmentLabel: "Assessment label",
                      deliverableLabel: "Deliverable label",
                      location: "Venue",
                      durationMinutes: "Duration (minutes)",
                      syllabus: "Syllabus",
                      permittedTools: "Permitted tools",
                      preparationInstructions: "Preparation instructions",
                    }[field]
                  }
                >
                  <input
                    id={field}
                    type={field === "durationMinutes" ? "number" : "text"}
                    min={field === "durationMinutes" ? 1 : undefined}
                    {...form.register(field)}
                  />
                </Field>
              ))}
            </div>
            <p className="form-help">
              {mode === "attempt_window"
                ? "The closing time determines when an incomplete test is missed."
                : mode === "fixed_session"
                  ? "The confirmed start determines when an incomplete test is missed."
                  : "Date-only assignment deadlines use 23:59 IST. Unknown exam times remain unresolved."}
            </p>
          </details>
          <ErrorNotice error={save.error} />
        </div>
        <div className="dialog-footer">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save task"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
