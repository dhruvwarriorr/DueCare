"use client";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, localTime, utcTime } from "@/lib/api";
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
// Deadline inputs split the stored IST cutoff into a date and an optional time.
function deadlineOf(task?: Task) {
  if (task?.dueDate) return { date: task.dueDate, time: "" };
  const local = localTime(task?.dueAt);
  return local
    ? { date: local.slice(0, 10), time: local.slice(11, 16) }
    : { date: "", time: "" };
}
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
  const deadline = deadlineOf(task);
  const defaults: Values = {
    title: task?.title || "",
    type: task?.type || "assignment",
    subjectId: task?.subjectId || "",
    priorityOverride: task?.priorityOverride || "",
    notes: task?.notes || "",
    deadlineDate: deadline.date,
    deadlineTime: deadline.time,
  };
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: defaults,
  });
  const date = useWatch({ control: form.control, name: "deadlineDate" });
  const save = useMutation({
    mutationFn: async (v: Values) => {
      const body: Record<string, unknown> = {
        title: v.title,
        type: v.type,
        subjectId: v.subjectId || null,
        priorityOverride: v.priorityOverride || null,
        notes: v.notes || "",
      };
      // Only rewrite timing when the student changed it, so imported test
      // details (start, attempt window) survive ordinary edits.
      const changed =
        !task ||
        v.deadlineDate !== deadline.date ||
        v.deadlineTime !== deadline.time;
      if (changed) {
        const d = v.deadlineDate || "";
        const t = v.deadlineTime || "";
        body.timingMode = d ? "deadline_only" : "undated";
        body.dueDate = d && !t ? d : null;
        body.dueAt = d && t ? utcTime(d + "T" + t) : null;
        if (task) {
          body.startsAt = null;
          body.availabilityClosesAt = null;
        }
      }
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
      await client.invalidateQueries({ queryKey: ["task"] });
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
      description="Only a title is required. All times use IST."
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
            <Field id="deadline-date" label="Deadline date">
              <input
                id="deadline-date"
                type="date"
                {...form.register("deadlineDate")}
              />
            </Field>
            <Field id="deadline-time" label="Deadline time (optional)">
              <input
                id="deadline-time"
                type="time"
                disabled={!date}
                {...form.register("deadlineTime")}
              />
            </Field>
            <Field id="priority" label="Priority">
              <select id="priority" {...form.register("priorityOverride")}>
                <option value="">Based on deadline</option>
                {["low", "medium", "high", "critical"].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </Field>
          </div>
          <p className="form-help">
            {date
              ? "Without a time, it's due by 23:59 IST that day."
              : "No date yet? Leave it blank and add it when you know."}
          </p>
          <Field id="notes" label="Personal notes">
            <textarea id="notes" rows={2} {...form.register("notes")} />
          </Field>
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
