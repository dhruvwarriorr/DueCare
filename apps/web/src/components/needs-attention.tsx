"use client";
import { useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
  useQuery,
} from "@tanstack/react-query";
import { Inbox, Check, X, Link2 } from "lucide-react";
import { api, formatTime, localTime, utcTime } from "@/lib/api";
import type { Page, ReviewItem, Subject, Task } from "@/lib/types";
import { Button } from "./ui/button";
import { ErrorNotice, Field } from "./ui/field";

const titles: Record<ReviewItem["issueType"], string> = {
  confirm_applicability: "Is this for you?",
  choose_subject: "Choose a subject",
  timing_unresolved: "Timing not settled",
  possible_duplicate: "Possible duplicate",
  association: "Which task is this about?",
  conflict: "Sources disagree",
  confirm_completion: "Submission found",
  receipt_unverified: "Unverified submission evidence",
  returned_ambiguous: "Returned work",
  unsubmission: "Work was unsubmitted",
  withdrawal: "Requirement withdrawn",
};
const timeFields: [string, string][] = [
  ["dueAt", "Deadline / cutoff"],
  ["startsAt", "Test starts"],
  ["reportingAt", "Report at"],
  ["availabilityClosesAt", "Online window closes"],
];
const sourceLabel: Record<string, string> = {
  gmail_message: "Gmail",
  classroom_coursework: "Classroom coursework",
  classroom_announcement: "Classroom announcement",
  classroom_submission: "Classroom submission",
};

function Targeting({ item }: { item: ReviewItem }) {
  const observed = { ...item.observed?.course, ...item.observed?.activity };
  const show = (["classYears", "semesters", "divisions", "batches"] as const)
    .map((k) => [k, observed[k]] as const)
    .filter(([, v]) => Array.isArray(v) && v.length);
  const s = item.student || {};
  return (
    <dl className="review-context">
      <div>
        <dt>Source mentions</dt>
        <dd>
          {show.length
            ? show
                .map(
                  ([k, v]) =>
                    `${k.replace(/s$/, "")}: ${(v as string[]).join(", ")}`,
                )
                .join(" · ")
            : "No class, division, or batch stated"}
          {observed.allBatches ? " · all batches" : ""}
        </dd>
      </div>
      <div>
        <dt>Your profile</dt>
        <dd>
          {s.classYear} · Semester {s.currentSemester} · Division {s.division} ·
          Batch {s.generalBatch}
        </dd>
      </div>
    </dl>
  );
}

function ReviewCard({
  item,
  subjects,
  tasks,
}: {
  item: ReviewItem;
  subjects: Subject[];
  tasks: Task[];
}) {
  const client = useQueryClient();
  const choices = item.subjectChoices.length
    ? subjects.filter((s) => item.subjectChoices.includes(s.id))
    : subjects;
  const [subjectId, setSubjectId] = useState(
    String(
      item.proposal?.subjectId || (choices.length === 1 ? choices[0].id : ""),
    ),
  );
  const [type, setType] = useState(String(item.proposal?.type || ""));
  const [remember, setRemember] = useState(Boolean(item.courseLabel));
  const [taskId, setTaskId] = useState(item.taskId || "");
  const [times, setTimes] = useState<Record<string, string>>({});
  const resolve = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api("/review-items/" + item.id + "/resolve", "POST", {
        revision: item.revision,
        ...body,
      }),
    onSuccess: async () => {
      for (const key of [
        "review-items",
        "tasks",
        "overview",
        "task",
        "subjects",
      ])
        await client.invalidateQueries({ queryKey: [key] });
    },
  });
  const accept = () => {
    const fields: Record<string, string | null> = {};
    if (type) fields.type = type;
    for (const [k, v] of Object.entries(times)) if (v) fields[k] = utcTime(v);
    resolve.mutate({
      action: "accept",
      subjectId: subjectId || null,
      rememberAlias: remember && Boolean(item.courseLabel),
      fields,
    });
  };
  const p = item.proposal || {};
  const creates = [
    "confirm_applicability",
    "choose_subject",
    "timing_unresolved",
  ].includes(item.issueType);
  return (
    <article className="panel review-card">
      <div className="review-head">
        <span className="kind-label">{titles[item.issueType]}</span>
        <span className="text-xs text-secondary">
          {sourceLabel[item.sourceKind || ""] || "Source"}
          {item.senderEmail ? " · " + item.senderEmail : ""} ·{" "}
          {formatTime(item.createdAt)}
        </span>
      </div>
      <h3>{item.question}</h3>
      {(item.taskTitle || p.title) && (
        <p className="text-sm">
          <strong>{item.taskTitle || String(p.title)}</strong>
          {p.type ? " · " + p.type : ""}
          {item.sourceTitle && item.sourceTitle !== p.title
            ? ` — from “${item.sourceTitle}”`
            : ""}
        </p>
      )}
      {item.excerpt && (
        <blockquote className="review-excerpt">{item.excerpt}</blockquote>
      )}
      {item.issueType === "confirm_applicability" && <Targeting item={item} />}
      {item.window && (
        <p className="text-sm">
          Date window: {item.window[0]} to {item.window[1]}. Accepting keeps the
          window without a precise cutoff.
        </p>
      )}
      {item.alternatives && item.alternatives.length > 0 && (
        <p className="text-sm">
          Tentative alternatives: {item.alternatives.join(" or ")}
        </p>
      )}
      {timeFields.some(([k]) => p[k]) && (
        <ul className="review-times">
          {timeFields
            .filter(([k]) => p[k])
            .map(([k, label]) => (
              <li key={k}>
                {label}: {formatTime(String(p[k]))}
              </li>
            ))}
        </ul>
      )}
      {item.conflicts && (
        <table className="conflicts">
          <thead>
            <tr>
              <th>Field</th>
              <th>Current</th>
              <th>Source says</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(item.conflicts).map(([k, v]) => (
              <tr key={k}>
                <td>{k}</td>
                <td>
                  {String(v.current ?? "—").includes("T")
                    ? formatTime(String(v.current))
                    : String(v.current ?? "—")}
                </td>
                <td>
                  {String(v.proposed).includes("T")
                    ? formatTime(String(v.proposed))
                    : String(v.proposed)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {item.evidenceCount > 1 && (
        <p className="text-xs text-secondary">
          {item.evidenceCount} source messages ask the same question.
        </p>
      )}
      {creates && (
        <div className="form-grid">
          <Field id={"subject-" + item.id} label="Subject">
            <select
              id={"subject-" + item.id}
              value={subjectId}
              onChange={(e) => setSubjectId(e.target.value)}
            >
              <option value="">Choose a subject</option>
              {choices.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} · {s.kind}
                </option>
              ))}
            </select>
          </Field>
          {!p.type && (
            <Field id={"type-" + item.id} label="Type">
              <select
                id={"type-" + item.id}
                value={type}
                onChange={(e) => setType(e.target.value)}
              >
                <option value="">Choose</option>
                <option value="assignment">Assignment</option>
                <option value="test">Test</option>
              </select>
            </Field>
          )}
          {item.issueType === "timing_unresolved" &&
            (["dueAt", "startsAt"] as const).map((k) => (
              <Field
                key={k}
                id={k + item.id}
                label={
                  (k === "dueAt" ? "Deadline" : "Test start") +
                  " (IST, optional)"
                }
              >
                <input
                  id={k + item.id}
                  type="datetime-local"
                  value={times[k] || localTime(p[k] ? String(p[k]) : null)}
                  onChange={(e) => setTimes({ ...times, [k]: e.target.value })}
                />
              </Field>
            ))}
          {item.courseLabel && (
            <label className="check-row">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
              />
              Remember “{item.courseLabel}” for this subject
            </label>
          )}
        </div>
      )}
      {item.issueType === "association" && (
        <Field id={"task-" + item.id} label="Task">
          <select
            id={"task-" + item.id}
            value={taskId}
            onChange={(e) => setTaskId(e.target.value)}
          >
            <option value="">Choose a task</option>
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
              </option>
            ))}
          </select>
        </Field>
      )}
      <ErrorNotice error={resolve.error} />
      <div className="review-actions">
        {creates && (
          <Button disabled={resolve.isPending || !subjectId} onClick={accept}>
            <Check size={15} />
            {item.issueType === "timing_unresolved"
              ? "Accept with this timing"
              : "Add task"}
          </Button>
        )}
        {item.issueType === "possible_duplicate" && (
          <>
            <Button
              disabled={resolve.isPending}
              onClick={() => resolve.mutate({ action: "link" })}
            >
              <Link2 size={15} />
              Same work
            </Button>
            <Button
              variant="outline"
              disabled={resolve.isPending}
              onClick={() =>
                resolve.mutate({ action: "accept", subjectId: p.subjectId })
              }
            >
              Separate task
            </Button>
          </>
        )}
        {item.issueType === "association" && (
          <Button
            disabled={!taskId || resolve.isPending}
            onClick={() => resolve.mutate({ action: "link", taskId })}
          >
            <Link2 size={15} />
            Link
          </Button>
        )}
        {item.issueType === "conflict" && (
          <>
            <Button
              disabled={resolve.isPending}
              onClick={() => resolve.mutate({ action: "apply_update" })}
            >
              Use source values
            </Button>
            <Button
              variant="outline"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate({ action: "keep_current" })}
            >
              Keep current
            </Button>
          </>
        )}
        {[
          "confirm_completion",
          "receipt_unverified",
          "returned_ambiguous",
        ].includes(item.issueType) && (
          <Button
            disabled={resolve.isPending}
            onClick={() => resolve.mutate({ action: "complete" })}
          >
            <Check size={15} />
            Mark completed
          </Button>
        )}
        {item.issueType === "unsubmission" && (
          <>
            <Button
              disabled={resolve.isPending}
              onClick={() => resolve.mutate({ action: "reopen" })}
            >
              Reopen
            </Button>
            <Button
              variant="outline"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate({ action: "keep_current" })}
            >
              Keep completed
            </Button>
          </>
        )}
        {item.issueType === "withdrawal" && (
          <>
            <Button
              variant="destructive"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate({ action: "delete_task" })}
            >
              Delete task
            </Button>
            <Button
              variant="outline"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate({ action: "keep_task" })}
            >
              Keep task
            </Button>
          </>
        )}
        <Button
          variant="ghost"
          disabled={resolve.isPending}
          onClick={() => resolve.mutate({ action: "dismiss" })}
        >
          <X size={15} />
          Dismiss
        </Button>
      </div>
      {item.links.length > 0 && (
        <p className="text-xs text-secondary review-links">
          Source link:{" "}
          <a href={item.links[0]} target="_blank" rel="noreferrer noopener">
            {new URL(item.links[0]).hostname}
          </a>
        </p>
      )}
    </article>
  );
}

export function NeedsAttention({
  subjects,
  targetId,
  onBack,
}: {
  subjects: Subject[];
  targetId?: string | null;
  onBack?: () => void;
}) {
  const target = useQuery({
    queryKey: ["review-items", targetId],
    queryFn: () => api<ReviewItem>("/review-items/" + targetId),
    enabled: !!targetId,
  });
  const query = useInfiniteQuery({
    queryKey: ["review-items"],
    initialPageParam: "",
    enabled: !targetId,
    queryFn: ({ pageParam }) =>
      api<Page<ReviewItem>>(
        "/review-items" +
          (pageParam ? "?cursor=" + encodeURIComponent(pageParam) : ""),
      ),
    getNextPageParam: (p) => p.nextCursor || undefined,
  });
  const tasks = useInfiniteQuery({
    queryKey: ["tasks", "review-picker"],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Page<Task>>(
        "/tasks?limit=100" +
          (pageParam ? "&cursor=" + encodeURIComponent(pageParam) : ""),
      ),
    getNextPageParam: (p) => p.nextCursor || undefined,
  });
  const items = targetId
    ? target.data
      ? [target.data]
      : []
    : query.data?.pages.flatMap((p) => p.items) || [];
  return (
    <>
      <div className="section-bar">
        <div>
          <h2>Needs attention</h2>
          <p className="text-secondary">
            Imported work DueCare could not settle on its own. Nothing here is a
            task until you confirm it. Work for another division or batch is
            ignored, not shown here.
          </p>
        </div>
      </div>
      {targetId && (
        <Button variant="ghost" onClick={onBack}>
          All items needing attention
        </Button>
      )}
      <ErrorNotice
        error={targetId ? target.error : query.error}
        retry={() => (targetId ? target.refetch() : query.refetch())}
      />
      {(targetId ? target.isPending : query.isPending) ? (
        <p className="empty-small" role="status">
          Loading items…
        </p>
      ) : items.length === 0 ? (
        <div className="empty panel">
          <Inbox size={28} />
          <h3>Nothing needs your attention</h3>
          <p>Questions about imported work will appear here.</p>
        </div>
      ) : (
        <div className="review-list">
          {items.map((item) => (
            <ReviewCard
              key={item.id + item.revision}
              item={item}
              subjects={subjects}
              tasks={tasks.data?.pages.flatMap((p) => p.items) || []}
            />
          ))}
        </div>
      )}
      {!targetId && query.hasNextPage && (
        <Button
          className="mt-4"
          variant="outline"
          onClick={() => query.fetchNextPage()}
        >
          Load more
        </Button>
      )}
      {tasks.hasNextPage && (
        <Button
          variant="ghost"
          disabled={tasks.isFetchingNextPage}
          onClick={() => tasks.fetchNextPage()}
        >
          Load more tasks for linking
        </Button>
      )}
    </>
  );
}
