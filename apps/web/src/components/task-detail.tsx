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
import type { Task, Page, History, Evidence } from "@/lib/types";
import { FacultyApproval } from "./faculty-approval";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { ErrorNotice } from "./ui/field";
const origins: Record<string, string> = {
  manual: "Marked completed by you",
  lms_assignment_receipt: "LMS submission confirmation",
  classroom_turned_in: "Classroom shows turned in",
  student_confirmed_evidence: "Confirmed by you from submission evidence",
};
const sourceNames: Record<string, string> = {
  manual: "Student entered",
  gmail: "Gmail",
  classroom: "Google Classroom",
};
const eventNames: Record<string, string> = {
  new_work: "New work",
  revision: "Revision",
  due_notice: "Due / overdue notice",
  supporting: "Supporting information",
  submission: "Submission evidence",
  unsubmission: "Unsubmission",
  withdrawal: "Withdrawal notice",
  unknown: "Source item",
};

function SourceEvidence({ task }: { task: Task }) {
  const client = useQueryClient();
  const evidence = useQuery({
    queryKey: ["evidence", task.id],
    queryFn: () =>
      api<{ items: Evidence[] }>("/tasks/" + task.id + "/evidence"),
  });
  const others = useQuery({
    queryKey: ["tasks", "picker", task.type],
    queryFn: () => api<Page<Task>>("/tasks?limit=100&type=" + task.type),
  });
  const [target, setTarget] = useState<Record<string, string>>({});
  const [merged, setMerged] = useState<string | null>(null);
  const [absorb, setAbsorb] = useState("");
  const done = async () => {
    for (const key of ["tasks", "task", "overview", "evidence", "history"])
      await client.invalidateQueries({ queryKey: [key] });
  };
  const move = useMutation({
    mutationFn: (e: Evidence) =>
      api("/evidence/" + e.id + "/reassign", "POST", { taskId: target[e.id] }),
    onSuccess: done,
  });
  const merge = useMutation({
    mutationFn: () => {
      const other = candidates.find((t) => t.id === absorb)!;
      return api<{ id: string }>("/task-merges", "POST", {
        survivingTaskId: task.id,
        absorbedTaskId: other.id,
        survivingRevision: task.revision,
        absorbedRevision: other.revision,
      });
    },
    onSuccess: async (r) => {
      setMerged(r.id);
      setAbsorb("");
      await done();
    },
  });
  const undo = useMutation({
    mutationFn: () => api("/task-merges/" + merged + "/undo", "POST"),
    onSuccess: async () => {
      setMerged(null);
      await done();
    },
  });
  const candidates = (others.data?.items || []).filter((t) => t.id !== task.id);
  const items = evidence.data?.items || [];
  return (
    <section className="detail-section">
      <h3>Source evidence</h3>
      <ErrorNotice error={evidence.error} retry={() => evidence.refetch()} />
      {items.length === 0 ? (
        <p className="text-sm text-secondary mt-2">
          No imported evidence. This task was entered by you.
        </p>
      ) : (
        <ol className="timeline">
          {items.map((e) => (
            <li key={e.id} className={e.state === "reassigned" ? "muted" : ""}>
              <strong>{eventNames[e.eventType] || e.eventType}</strong>
              <time>
                {e.occurredAt ? formatTime(e.occurredAt) : "Time not stated"}
              </time>
              <p className="text-secondary text-xs">
                {e.sourceKind.startsWith("classroom") ? "Classroom" : "Gmail"}
                {e.sender ? " · " + e.sender : ""}
                {e.sourceTitle ? " · " + e.sourceTitle : ""}
                {e.state === "reassigned" ? " · moved to another task" : ""}
              </p>
              {e.excerpt && <p className="text-xs">{e.excerpt}</p>}
              {e.state === "active" && candidates.length > 0 && (
                <span className="link-control mt-2">
                  <label className="sr-only" htmlFor={"move-" + e.id}>
                    Move this evidence to another task
                  </label>
                  <select
                    id={"move-" + e.id}
                    value={target[e.id] || ""}
                    onChange={(ev) =>
                      setTarget({ ...target, [e.id]: ev.target.value })
                    }
                  >
                    <option value="">Move to another task…</option>
                    {candidates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.title}
                      </option>
                    ))}
                  </select>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!target[e.id] || move.isPending}
                    onClick={() => move.mutate(e)}
                  >
                    Move
                  </Button>
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
      <ErrorNotice error={move.error} />
      <div className="merge-row">
        <label className="sr-only" htmlFor={"merge-" + task.id}>
          Duplicate task to merge into this one
        </label>
        <select
          id={"merge-" + task.id}
          value={absorb}
          onChange={(e) => setAbsorb(e.target.value)}
        >
          <option value="">Merge a duplicate into this task…</option>
          {candidates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title}
              {t.subjectName ? " · " + t.subjectName : ""}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          variant="outline"
          disabled={!absorb || merge.isPending}
          onClick={() => merge.mutate()}
        >
          Merge
        </Button>
      </div>
      {merged && (
        <div className="success-notice mt-2" role="status">
          <p>
            Tasks merged. The duplicate is hidden and its evidence moved here.
          </p>
          <button
            type="button"
            disabled={undo.isPending}
            onClick={() => undo.mutate()}
          >
            Undo merge
          </button>
        </div>
      )}
      <ErrorNotice error={merge.error || undo.error} />
    </section>
  );
}

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
              <FacultyApproval emails={t.senderEmails} />
              <dl className="detail-grid">
                <div>
                  <dt>Subject</dt>
                  <dd>
                    {t.subjectName || "No subject"}
                    {t.subjectKind ? " · " + t.subjectKind : ""}
                    {t.subjectLink && t.subjectLink.method !== "none" && (
                      <small className="block text-xs text-secondary">
                        Linked automatically
                        {t.subjectLink.method === "ai"
                          ? " by AI from the course name"
                          : " from the course name"}
                        . Edit the task to change it.
                      </small>
                    )}
                    {t.subjectLink?.method === "none" && !t.subjectName && (
                      <small className="block text-xs text-secondary">
                        {t.subjectLink.reason === "ai_unavailable"
                          ? "Couldn't be linked automatically right now."
                          : "None of your subjects matched."}{" "}
                        Edit the task to set one.
                      </small>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Batch</dt>
                  <dd>{t.generalBatch || "Not set"}</dd>
                </div>
                <div>
                  <dt>Source</dt>
                  <dd>
                    {(t.sources || ["manual"])
                      .map((s) => sourceNames[s] || s)
                      .join(", ")}
                  </dd>
                </div>
                <div>
                  <dt>Completion</dt>
                  <dd>
                    {t.completedAt
                      ? (origins[t.completionOrigin || "manual"] ||
                          "Completed") +
                        " · " +
                        formatTime(t.completedAt)
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
                        {t.timingProvenance?.[k]?.basis &&
                          ![
                            "source-exact",
                            "student-entered",
                            "student-date-only",
                          ].includes(t.timingProvenance[k].basis || "") && (
                            <span className="block text-xs text-secondary">
                              {t.timingProvenance[k].basis?.replace("-", " ")}
                            </span>
                          )}
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
                          {h.actor === "source" ? "From a source" : "You"} ·{" "}
                          {Object.keys(h.changes).join(", ") ||
                            "no field changes"}
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
              <SourceEvidence task={t} />
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
