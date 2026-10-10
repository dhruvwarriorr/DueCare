"use client";
import { useCutoffRefresh } from "@/lib/use-cutoff-refresh";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  classroomNote,
  datetimeFields,
  dueWindow,
  formatRange,
  formatTime,
} from "@/lib/api";
import type { Evidence, Task } from "@/lib/types";
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
  const evidence = useQuery({
    queryKey: ["evidence", id],
    queryFn: () => api<{ items: Evidence[] }>("/tasks/" + id + "/evidence"),
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
      description={
        t?.sourceTitle && t.sourceTitle !== t.title
          ? "Original title: " + t.sourceTitle
          : "Your instructions, timing, and status."
      }
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
                    {classroomNote(t) && (
                      <small className="block text-xs text-secondary">
                        Classroom: {classroomNote(t)}
                      </small>
                    )}
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
                    <dt>Date window</dt>
                    <dd>
                      {formatRange(
                        t.dateWindowStart,
                        t.dateWindowEnd || t.dateWindowStart,
                      )}
                      {dueWindow(t) && (
                        <span className="block text-xs text-secondary">
                          Exact day not announced; due by the last day
                        </span>
                      )}
                    </dd>
                  </div>
                )}
                {t.timingTentative && (
                  <div>
                    <dt>Timing</dt>
                    <dd>
                      Tentative
                      {t.timingTentative.question && (
                        <span className="block text-xs text-secondary">
                          {t.timingTentative.question}
                        </span>
                      )}
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
              <SourceList items={evidence.data?.items} />
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

const kindNames: Record<Evidence["sourceKind"], string> = {
  gmail_message: "Email",
  classroom_announcement: "Classroom post",
  classroom_coursework: "Classroom assignment",
  classroom_submission: "Classroom turn-in",
};
/** Where the task came from: who posted it, when, and a link back to the original. */
function SourceList({ items }: { items?: Evidence[] }) {
  const seen = new Set<string>();
  const sources = (items || []).filter((e) => {
    // One row per original item; a turn-in only matters as proof of completion.
    const key = e.openUrl || e.id;
    if (e.state !== "active" || e.eventType === "submission" || seen.has(key))
      return false;
    seen.add(key);
    return true;
  });
  if (!sources.length) return null;
  return (
    <section className="detail-section">
      <h3>{sources.length === 1 ? "Source" : "Sources"}</h3>
      <ul className="source-list">
        {sources.map((e) => (
          <li key={e.id}>
            <div>
              <strong>{kindNames[e.sourceKind]}</strong>
              {e.sourceKind === "gmail_message"
                ? e.senderName || e.sender
                  ? " from " + (e.senderName || e.sender)
                  : ""
                : (e.postedBy ? " by " + e.postedBy : "") +
                  (e.courseName ? " in " + e.courseName : "")}
              {e.postedAt && (
                <span className="text-secondary">
                  {" · posted " + formatTime(e.postedAt)}
                </span>
              )}
            </div>
            {e.senderName && e.sender && (
              <small className="block text-xs text-secondary">{e.sender}</small>
            )}
            {(e.sourceTitle || e.excerpt) && (
              <p className="text-secondary mt-1">
                {e.sourceTitle || "“" + e.excerpt + "”"}
              </p>
            )}
            {e.openUrl && (
              <a
                className="source-open"
                href={e.openUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                {e.sourceKind === "gmail_message"
                  ? "Open in Gmail"
                  : "Open in Classroom"}{" "}
                ↗
              </a>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
