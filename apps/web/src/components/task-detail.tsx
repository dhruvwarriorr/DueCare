"use client";
import { useCutoffRefresh } from "@/lib/use-cutoff-refresh";
import { useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api, formatTime, datetimeFields } from "@/lib/api";
import type { Task, Page, History } from "@/lib/types";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { ErrorNotice } from "./ui/field";
export function TaskDetail({
  id,
  onClose,
  onEdit,
}: {
  id: string;
  onClose: () => void;
  onEdit: (t: Task) => void;
}) {
  const client = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const task = useQuery({
    queryKey: ["task", id],
    queryFn: () => api<Task>("/tasks/" + id),
  });
  const timeline = useInfiniteQuery({
    queryKey: ["history", id],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Page<History>>(
        "/tasks/" +
          id +
          "/history" +
          (pageParam ? "?cursor=" + encodeURIComponent(pageParam) : ""),
      ),
    getNextPageParam: (p) => p.nextCursor || undefined,
  });
  const mutation = useMutation({
    mutationFn: ({ remove }: { remove: boolean }) =>
      api(
        "/tasks/" + id + (remove ? "?revision=" + task.data?.revision : ""),
        remove ? "DELETE" : "PATCH",
        remove
          ? undefined
          : {
              revision: task.data?.revision,
              status: task.data?.status === "completed" ? "due" : "completed",
            },
      ),
    onSuccess: async (_, v) => {
      await client.invalidateQueries({ queryKey: ["tasks"] });
      await client.invalidateQueries({ queryKey: ["overview"] });
      await client.invalidateQueries({ queryKey: ["task", id] });
      await client.invalidateQueries({ queryKey: ["history", id] });
      if (v.remove) onClose();
    },
  });
  const labels: Record<string, string> = {
    dueAt: "Applicable cutoff",
    submissionOpensAt: "Submission opens",
    availabilityOpensAt: "Quiz window opens",
    availabilityClosesAt: "Quiz window closes",
    loginByAt: "Login by",
    reportingAt: "Report at",
    startsAt: "Test starts",
    endsAt: "Test ends",
  };
  const t = task.data;
  useCutoffRefresh(t ? [t] : []);
  return (
    <Dialog
      open
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
      title={t?.title || "Task details"}
      description="Your instructions, timing, and change history."
    >
      <div className="dialog-body">
        <ErrorNotice error={task.error} retry={() => task.refetch()} />
        {task.isPending ? (
          <p role="status">Loading task…</p>
        ) : (
          t && (
            <>
              <div className="flex flex-wrap gap-2 mb-5">
                <span className={"status " + t.status}>{t.status}</span>
                <span className="tag">{t.type}</span>
                <span className="tag">{t.priority} priority</span>
              </div>
              <dl className="detail-grid">
                <div>
                  <dt>Subject</dt>
                  <dd>
                    {t.subjectName || "No subject"}
                    {t.subjectKind ? " · " + t.subjectKind : ""}
                  </dd>
                </div>
                <div>
                  <dt>General batch</dt>
                  <dd>{t.generalBatch || "Not set"}</dd>
                </div>
                <div>
                  <dt>Source</dt>
                  <dd>Student entered</dd>
                </div>
                <div>
                  <dt>Completion</dt>
                  <dd>
                    {t.completedAt
                      ? "Manually confirmed · " + formatTime(t.completedAt)
                      : "Not completed"}
                  </dd>
                </div>
                {datetimeFields
                  .filter((k) => t[k])
                  .map((k) => (
                    <div key={k}>
                      <dt>{labels[k]} (IST)</dt>
                      <dd>
                        {formatTime(t[k])}
                        {k === "dueAt" && t.dueDate && (
                          <span className="block text-xs text-secondary">
                            Date only; default 23:59 IST
                          </span>
                        )}
                      </dd>
                    </div>
                  ))}
                {t.dueDate && t.type === "test" && (
                  <div>
                    <dt>Test date</dt>
                    <dd>{t.dueDate} · exact start not entered</dd>
                  </div>
                )}
                {t.dateWindowStart && (
                  <div>
                    <dt>Unresolved date window</dt>
                    <dd>
                      {t.dateWindowStart} to {t.dateWindowEnd || "unknown"}
                    </dd>
                  </div>
                )}
                {(
                  [
                    "assessmentLabel",
                    "deliverableLabel",
                    "location",
                    "estimatedEffortMinutes",
                    "durationMinutes",
                    "syllabus",
                    "permittedTools",
                    "preparationInstructions",
                  ] as const
                )
                  .filter((k) => t[k])
                  .map((k) => (
                    <div key={k}>
                      <dt>{k.replace(/([A-Z])/g, " $1")}</dt>
                      <dd>{t[k]}</dd>
                    </div>
                  ))}
              </dl>
              {t.instructions && (
                <section className="detail-section">
                  <h3>Instructions</h3>
                  <p className="whitespace-pre-wrap">{t.instructions}</p>
                </section>
              )}
              {t.notes && (
                <section className="detail-section">
                  <h3>Personal notes</h3>
                  <p className="whitespace-pre-wrap">{t.notes}</p>
                </section>
              )}
              <section className="detail-section">
                <h3>Change history</h3>
                <ErrorNotice
                  error={timeline.error}
                  retry={() => timeline.refetch()}
                />
                <ol className="timeline">
                  {timeline.data?.pages
                    .flatMap((p) => p.items)
                    .map((h) => (
                      <li key={h.id}>
                        <strong>{h.action.replaceAll("_", " ")}</strong>
                        <time>{formatTime(h.recordedAt)}</time>
                        <p className="text-secondary text-xs">
                          Student · {Object.keys(h.changes).join(", ")}
                        </p>
                        <details>
                          <summary>View change details</summary>
                          <pre className="history-values">
                            {JSON.stringify(h.changes, null, 2)}
                          </pre>
                        </details>
                      </li>
                    ))}
                </ol>
                {timeline.hasNextPage && (
                  <Button
                    variant="outline"
                    onClick={() => timeline.fetchNextPage()}
                  >
                    Older changes
                  </Button>
                )}
              </section>
              <ErrorNotice error={mutation.error} />
              {confirm && (
                <div className="error-notice">
                  <p>Delete this task and its history?</p>
                  <Button
                    variant="destructive"
                    disabled={mutation.isPending}
                    onClick={() => mutation.mutate({ remove: true })}
                  >
                    Confirm deletion
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirm(false)}>
                    Keep task
                  </Button>
                </div>
              )}
            </>
          )
        )}
      </div>
      {t && (
        <div className="dialog-footer flex-wrap">
          <Button variant="ghost" onClick={() => setConfirm(true)}>
            Delete
          </Button>
          <Button variant="outline" onClick={() => onEdit(t)}>
            Edit task
          </Button>
          <Button
            disabled={mutation.isPending}
            onClick={() => mutation.mutate({ remove: false })}
          >
            {t.status === "completed" ? "Reopen task" : "Mark completed"}
          </Button>
        </div>
      )}
    </Dialog>
  );
}
