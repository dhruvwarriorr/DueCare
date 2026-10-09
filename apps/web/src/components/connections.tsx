"use client";
import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Mail,
  GraduationCap,
  RefreshCw,
  Unplug,
  Link2,
  X,
  ShieldBan,
  UserPlus,
  Trash2,
  RotateCcw,
} from "lucide-react";
import { api, formatTime } from "@/lib/api";
import { useSync } from "@/lib/sync";
import type {
  ClassroomCourse,
  Connection,
  Page,
  SenderPreference,
  Subject,
  SyncJob,
} from "@/lib/types";
import { FacultyApproval } from "./faculty-approval";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { ErrorNotice, Field } from "./ui/field";

const services = {
  gmail: {
    label: "Gmail",
    icon: Mail,
    detail: "Read-only access to messages for academic notices.",
  },
  classroom: {
    label: "Google Classroom",
    icon: GraduationCap,
    detail:
      "Read-only courses, announcements, coursework, and your own submissions.",
  },
} as const;
const permissionLabels: Record<string, string> = {
  "https://www.googleapis.com/auth/gmail.readonly": "Read Gmail messages",
  "https://www.googleapis.com/auth/classroom.courses.readonly":
    "See Classroom courses",
  "https://www.googleapis.com/auth/classroom.coursework.me.readonly":
    "See your coursework and submissions",
  "https://www.googleapis.com/auth/classroom.announcements.readonly":
    "See course announcements",
};
const errorText: Record<string, string> = {
  AUTHORIZATION_DECLINED: "Google access was not granted.",
  AUTHORIZATION_EXPIRED: "That connection attempt expired. Start it again.",
  AUTHORIZATION_FAILED: "Google could not complete the connection. Try again.",
  PERMISSION_NOT_GRANTED:
    "Allow every requested read-only permission to connect this service.",
  OFFLINE_ACCESS_REQUIRED:
    "Reconnect and allow DueCare to keep read-only access.",
  ACCOUNT_UNVERIFIED: "Connect a Google account with a verified email.",
  SOURCE_CONFIGURATION: "Gmail and Classroom connections are not set up yet.",
};

function jobSummary(job: SyncJob | null) {
  if (!job) return null;
  const p = job.progress;
  const count = (n: number | undefined, one: string, many: string) =>
    n ? `${n} ${n === 1 ? one : many}` : null;
  const parts = [
    count(p.stored, "imported", "imported"),
    count(p.updated, "updated", "updated"),
    count(p.duplicates, "duplicate", "duplicates"),
    count(p.blocked, "blocked", "blocked"),
    count(p.ignored, "not academic", "not academic"),
    count(p.courses, "course found", "courses found"),
    count(p.tasksCreated, "task added", "tasks added"),
    count(p.tasksUpdated, "task updated", "tasks updated"),
    count(p.completed, "completed from evidence", "completed from evidence"),
    count(p.reviews, "needs attention", "need attention"),
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "Nothing new";
}

function SyncStatus({ c, driving }: { c: Connection; driving: boolean }) {
  const job = c.activeJob;
  if (c.status === "needs_reauth")
    return (
      <p className="sync-line warn" role="status">
        {c.lastError?.message || "Reconnect this account to keep syncing."}
      </p>
    );
  if (c.status === "disconnected")
    return (
      <p className="sync-line">
        Disconnected. Imported records and your tasks were kept.
      </p>
    );
  if (job?.status === "waiting_retry")
    return (
      <p className="sync-line warn" role="status">
        {job.error?.message || "Google is temporarily unavailable."} Retrying at{" "}
        {formatTime(job.nextRetryAt)}.
      </p>
    );
  if (job)
    return (
      <p className="sync-line active" role="status">
        <RefreshCw size={14} className={driving ? "spin" : ""} />
        {driving || job.leased
          ? job.phase === "interpreting"
            ? "Adding tasks"
            : "Syncing and adding tasks"
          : "Paused until you return"}
        {" · "}
        {jobSummary(job)}
      </p>
    );
  return (
    <p className="sync-line" role="status">
      {c.lastSuccessAt
        ? "Last synced " + formatTime(c.lastSuccessAt)
        : "Not synced yet"}
      {c.lastJob?.status === "completed" && " · " + jobSummary(c.lastJob)}
      {c.lastError && c.lastJob?.status === "failed" && (
        <span className="block warn">{c.lastError.message}</span>
      )}
    </p>
  );
}

async function allSubjects() {
  let cursor = "",
    items: Subject[] = [];
  do {
    const p = await api<Page<Subject>>(
      "/subjects?limit=100" +
        (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
    );
    items = [...items, ...p.items];
    cursor = p.nextCursor || "";
  } while (cursor);
  return items;
}

function CourseLinks({ connection }: { connection: Connection }) {
  const client = useQueryClient();
  const courses = useQuery({
    queryKey: ["classroom-courses", connection.id],
    queryFn: () =>
      api<Page<ClassroomCourse>>(
        "/connections/" + connection.id + "/classroom-courses?limit=100",
      ),
  });
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: allSubjects });
  const [choice, setChoice] = useState<Record<string, string>>({});
  const change = useMutation({
    mutationFn: ({
      subjectId,
      courseId,
      remove,
    }: {
      subjectId: string;
      courseId: string;
      remove?: boolean;
    }) =>
      api(
        `/subjects/${subjectId}/classroom-mappings/${connection.id}/${encodeURIComponent(courseId)}`,
        remove ? "DELETE" : "PUT",
      ),
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: ["classroom-courses", connection.id],
      });
      await client.invalidateQueries({ queryKey: ["subjects"] });
    },
  });
  const items = courses.data?.items || [];
  return (
    <div className="course-links">
      <h4>Link Classroom courses to your subjects</h4>
      <p className="text-secondary text-xs">
        Courses link to your subjects automatically on each sync, by name or
        short form and with AI when needed (marked “auto”). Change or add links
        here; a course you unlink stays unlinked. Only linked courses are
        imported, and courses are never added as subjects.
      </p>
      <ErrorNotice error={courses.error} retry={() => courses.refetch()} />
      <ErrorNotice error={change.error} />
      {courses.isPending ? (
        <p className="empty-small" role="status">
          Loading courses…
        </p>
      ) : items.length === 0 ? (
        <p className="empty-small">
          Sync this connection to discover your courses.
        </p>
      ) : (
        <ul className="course-list">
          {items.map((course) => {
            const linked = new Set(course.mappings.map((m) => m.subjectId));
            const options = (subjects.data || []).filter(
              (s) => !linked.has(s.id),
            );
            const selectId = "link-" + course.externalCourseId;
            return (
              <li key={course.externalCourseId} className="course-row">
                <div className="course-name">
                  <strong>{course.name}</strong>
                  <span>
                    {course.section || "No section"}
                    {!course.available && " · No longer available from Google"}
                  </span>
                </div>
                <div className="course-subjects">
                  {course.mappings.map((m) => (
                    <span key={m.subjectId} className="chip">
                      {m.subjectName} · {m.subjectKind}
                      {m.automatic && (
                        <small title="Linked automatically from the course name">
                          {" "}
                          · auto
                        </small>
                      )}
                      <button
                        type="button"
                        aria-label={`Unlink ${m.subjectName} from ${course.name}`}
                        disabled={change.isPending}
                        onClick={() =>
                          change.mutate({
                            subjectId: m.subjectId,
                            courseId: course.externalCourseId,
                            remove: true,
                          })
                        }
                      >
                        <X size={12} />
                      </button>
                    </span>
                  ))}
                  {options.length > 0 && (
                    <span className="link-control">
                      <label className="sr-only" htmlFor={selectId}>
                        Subject for {course.name}
                      </label>
                      <select
                        id={selectId}
                        value={choice[course.externalCourseId] || ""}
                        onChange={(e) =>
                          setChoice({
                            ...choice,
                            [course.externalCourseId]: e.target.value,
                          })
                        }
                      >
                        <option value="">Choose a subject</option>
                        {options.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.name} · {s.kind}
                          </option>
                        ))}
                      </select>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={
                          !choice[course.externalCourseId] || change.isPending
                        }
                        onClick={() =>
                          change.mutate({
                            subjectId: choice[course.externalCourseId],
                            courseId: course.externalCourseId,
                          })
                        }
                      >
                        <Link2 size={14} />
                        Link
                      </Button>
                    </span>
                  )}
                  {subjects.data?.length === 0 && (
                    <span className="text-xs text-secondary">
                      Add subjects first to link this course.
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ConnectionCard({
  c,
  onConnect,
}: {
  c: Connection;
  onConnect: () => void;
}) {
  const client = useQueryClient();
  const sync = useSync();
  const [confirm, setConfirm] = useState(false);
  const driving = sync.driving.has(c.id);
  const meta = services[c.service];
  const Icon = meta.icon;
  const disconnect = useMutation({
    mutationFn: () =>
      api("/connections/" + c.id + "?revision=" + c.revision, "DELETE"),
    onSuccess: async () => {
      setConfirm(false);
      await client.invalidateQueries({ queryKey: ["connections"] });
      await client.invalidateQueries({ queryKey: ["overview"] });
    },
  });
  const reprocess = useMutation({ mutationFn: () => sync.reprocess(c.id) });
  return (
    <article className="panel connection-card">
      <div className="connection-head">
        <span className="task-icon">
          <Icon size={18} />
        </span>
        <div className="connection-title">
          <h3>{meta.label}</h3>
          <span>{c.account.email}</span>
        </div>
        <span className={"conn-status " + c.status}>
          {c.status === "needs_reauth"
            ? "Reconnect needed"
            : c.status === "active"
              ? "Connected"
              : "Disconnected"}
        </span>
      </div>
      <SyncStatus c={c} driving={driving} />
      {c.privacyJobId && (
        <p role="status" className="text-secondary">
          A privacy operation is in progress.{" "}
          <Link href="/?view=settings">Open Settings to resume it.</Link>
        </p>
      )}
      <ErrorNotice error={sync.failures[c.id] || null} />
      {c.status !== "disconnected" && (
        <>
          <ul className="permission-list" aria-label="Granted permissions">
            {c.permissions.map((p) => (
              <li key={p}>{permissionLabels[p] || p}</li>
            ))}
          </ul>
          <p className="text-xs text-secondary">
            {[
              c.records.interpreted > 0 &&
                `${c.records.interpreted} interpreted`,
              c.records.needsReview > 0 &&
                `${c.records.needsReview} need your attention`,
              c.records.awaitingInterpretation - c.records.aiPaused > 0 &&
                `${c.records.awaitingInterpretation - c.records.aiPaused} waiting to be interpreted`,
              c.records.aiPaused > 0 &&
                `${c.records.aiPaused} waiting for AI interpretation (retries automatically in the background)`,
              c.records.ignored > 0 &&
                `${c.records.ignored} not academic or not for you`,
              c.records.blocked > 0 &&
                `${c.records.blocked} from blocked senders`,
            ]
              .filter(Boolean)
              .join(" · ") || "Nothing imported yet."}
          </p>
        </>
      )}
      <div className="subject-actions flex-wrap">
        {c.status === "active" && (
          <Button
            size="sm"
            disabled={
              !!c.privacyJobId || driving || Boolean(c.activeJob?.leased)
            }
            onClick={() => sync.syncNow(c.id)}
          >
            <RefreshCw size={14} />
            Sync now
          </Button>
        )}
        {c.status !== "active" && (
          <Button
            size="sm"
            disabled={!!c.privacyJobId}
            onClick={() => onConnect()}
          >
            Reconnect
          </Button>
        )}
        {c.status === "active" && (
          <Button
            size="sm"
            variant="outline"
            disabled={!!c.privacyJobId || driving || reprocess.isPending}
            onClick={() => reprocess.mutate()}
          >
            <RotateCcw size={14} />
            Reprocess
          </Button>
        )}
        {c.status !== "disconnected" && (
          <Button
            size="sm"
            variant="ghost"
            disabled={!!c.privacyJobId}
            onClick={() => setConfirm(true)}
          >
            <Unplug size={14} />
            Disconnect
          </Button>
        )}
      </div>
      <ErrorNotice error={reprocess.error} />
      {c.service === "classroom" && c.status === "active" && (
        <CourseLinks connection={c} />
      )}
      {confirm && (
        <Dialog
          open
          title={`Disconnect ${meta.label}?`}
          description="DueCare stops syncing this service. Your tasks and imported records are kept."
          onOpenChange={(v) => {
            if (!v) setConfirm(false);
          }}
        >
          <div className="dialog-body">
            <p>
              {c.account.email} · {meta.label}
            </p>
            <p className="text-sm text-secondary mt-2">
              Google access is revoked when no other DueCare service uses this
              account.
            </p>
            <ErrorNotice error={disconnect.error} />
          </div>
          <div className="dialog-footer">
            <Button variant="outline" onClick={() => setConfirm(false)}>
              Keep connected
            </Button>
            <Button
              variant="destructive"
              disabled={disconnect.isPending}
              onClick={() => disconnect.mutate()}
            >
              Disconnect
            </Button>
          </div>
        </Dialog>
      )}
    </article>
  );
}

function SenderPreferences() {
  const client = useQueryClient();
  const prefs = useQuery({
    queryKey: ["sender-preferences"],
    queryFn: () => api<Page<SenderPreference>>("/sender-preferences?limit=100"),
  });
  const [email, setEmail] = useState("");
  const [action, setAction] = useState<"include" | "block">("include");
  const done = async () => {
    await client.invalidateQueries({ queryKey: ["sender-preferences"] });
    await client.invalidateQueries({ queryKey: ["connections"] });
  };
  const save = useMutation({
    mutationFn: (v: {
      email: string;
      action: "include" | "block";
      revision?: number;
    }) =>
      api("/sender-preferences/" + encodeURIComponent(v.email.trim()), "PUT", {
        action: v.action,
        revision: v.revision,
      }),
    onSuccess: async () => {
      setEmail("");
      await done();
    },
  });
  const remove = useMutation({
    mutationFn: (p: SenderPreference) =>
      api(
        "/sender-preferences/" +
          encodeURIComponent(p.email) +
          "?revision=" +
          p.revision,
        "DELETE",
      ),
    onSuccess: done,
  });
  const items = prefs.data?.items || [];
  return (
    <section className="panel sender-panel" aria-labelledby="senders">
      <div className="panel-heading">
        <div>
          <h2 id="senders">Sender preferences</h2>
          <p className="text-secondary text-sm">
            Match exact sender addresses. Including a sender makes their mail
            eligible for academic checks. A complete block stops all processing
            of that sender, including submission receipts, and takes precedence
            over every include and rule.
          </p>
        </div>
      </div>
      <form
        className="sender-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (email.trim()) save.mutate({ email, action });
        }}
      >
        <Field id="sender-email" label="Sender email">
          <input
            id="sender-email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="faculty@somaiya.edu"
          />
        </Field>
        <Field id="sender-action" label="Preference">
          <select
            id="sender-action"
            value={action}
            onChange={(e) => setAction(e.target.value as "include" | "block")}
          >
            <option value="include">Include sender</option>
            <option value="block">Block completely</option>
          </select>
        </Field>
        <Button disabled={save.isPending}>Save sender</Button>
      </form>
      <div className="px-6">
        <ErrorNotice error={save.error || remove.error} />
        <ErrorNotice error={prefs.error} retry={() => prefs.refetch()} />
      </div>
      {prefs.isPending ? (
        <p className="empty-small" role="status">
          Loading sender preferences…
        </p>
      ) : items.length === 0 ? (
        <p className="empty-small">
          No sender preferences yet. College and faculty addresses are already
          considered.
        </p>
      ) : (
        <ul className="sender-list">
          {items.map((p) => (
            <li key={p.email}>
              {p.action === "block" ? (
                <ShieldBan size={16} className="warn" />
              ) : (
                <UserPlus size={16} />
              )}
              <span className="sender-email">{p.email}</span>
              <span className={"tag " + p.action}>
                {p.action === "block" ? "Blocked" : "Included"}
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={save.isPending}
                onClick={() =>
                  save.mutate({
                    email: p.email,
                    action: p.action === "block" ? "include" : "block",
                    revision: p.revision,
                  })
                }
              >
                {p.action === "block" ? "Include instead" : "Block"}
              </Button>
              <Button
                size="icon"
                variant="ghost"
                aria-label={"Remove " + p.email}
                disabled={remove.isPending}
                onClick={() => remove.mutate(p)}
              >
                <Trash2 size={15} />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <p className="form-help px-6 pb-6">
        Blocking applies inside DueCare only; it does not change Gmail.
        Unblocking affects future mail. Use “Reprocess” on a source to
        reconsider earlier items with your current senders, profile, subjects,
        and rules.
      </p>
    </section>
  );
}

export function Connections({
  notice,
  onDismiss,
}: {
  notice: { connected?: string; error?: string };
  onDismiss: () => void;
}) {
  const sync = useSync();
  // Gmail and Classroom access is granted at Google sign-in; re-asking means signing in with consent.
  const grant = useMutation({
    mutationFn: () =>
      api<{ url: string }>("/auth/start", "POST", { consent: true }),
    onSuccess: ({ url }) => window.location.assign(url),
  });
  const onConnect = () => grant.mutate();
  const visible = sync.connections.filter((c) => c.status !== "disconnected");
  const disconnected = sync.connections.filter(
    (c) => c.status === "disconnected",
  );
  const status = (service: Connection["service"]) =>
    visible.find((c) => c.service === service)?.status;
  const allActive =
    status("gmail") === "active" && status("classroom") === "active";
  const account = visible[0]?.account.email;
  return (
    <>
      <div className="section-bar">
        <div>
          <h2>Sources</h2>
          <p className="text-secondary">
            DueCare reads your Gmail and Google Classroom (read-only) using the
            access you granted when you signed in with Google.
          </p>
        </div>
      </div>
      {(notice.connected || notice.error) && (
        <div
          className={notice.error ? "error-notice" : "success-notice"}
          role="status"
        >
          <p>
            {notice.connected
              ? `${notice.connected
                  .split(",")
                  .map((s) => services[s as Connection["service"]]?.label || s)
                  .join(
                    " and ",
                  )} ${notice.connected.includes(",") ? "are" : "is"} connected. Syncing will start now.`
              : errorText[notice.error || ""] ||
                "The connection could not be completed."}
          </p>
          <button type="button" onClick={onDismiss}>
            Dismiss
          </button>
        </div>
      )}
      {!sync.isPending && (
        <section
          className={"panel access-panel " + (allActive ? "ok" : "missing")}
          aria-labelledby="access-heading"
        >
          <div className="access-text">
            <h3 id="access-heading">
              {allActive
                ? "Gmail and Classroom are connected"
                : "Gmail and Classroom access is needed"}
            </h3>
            <p className="text-secondary text-sm">
              {allActive
                ? `Granted at sign-in for ${account}. Sync continues in the background, including when you switch tabs or close this page.`
                : "Allow read-only access on Google's sign-in screen so your assignments and tests appear automatically. Your password is never shared with DueCare."}
            </p>
          </div>
          <ul className="access-status">
            {(Object.keys(services) as Connection["service"][]).map(
              (service) => {
                const meta = services[service];
                const Icon = meta.icon;
                const state = status(service);
                return (
                  <li key={service} className={state || "none"}>
                    <Icon size={16} />
                    {meta.label}
                    <strong>
                      {state === "active"
                        ? "Connected"
                        : state === "needs_reauth"
                          ? "Reconnect needed"
                          : "Not connected"}
                    </strong>
                  </li>
                );
              },
            )}
          </ul>
          {!allActive && (
            <Button disabled={grant.isPending} onClick={onConnect}>
              Allow Gmail and Classroom access
            </Button>
          )}
        </section>
      )}
      <ErrorNotice error={grant.error} />
      <ErrorNotice error={sync.error} retry={sync.refetch} />
      {sync.isPending ? (
        <p className="empty-small" role="status">
          Loading connections…
        </p>
      ) : visible.length === 0 ? (
        <p className="empty-small">
          Manual tasks keep working without Gmail or Classroom.
        </p>
      ) : (
        <div className="connection-list">
          {visible.map((c) => (
            <ConnectionCard key={c.id} c={c} onConnect={onConnect} />
          ))}
        </div>
      )}
      {disconnected.length > 0 && (
        <details className="panel disconnected-list">
          <summary>
            {disconnected.length} disconnected source
            {disconnected.length === 1 ? "" : "s"}
          </summary>
          {disconnected.map((c) => (
            <ConnectionCard key={c.id} c={c} onConnect={onConnect} />
          ))}
        </details>
      )}
      <FacultyApproval manage />
      <SenderPreferences />
    </>
  );
}

export function SyncOverview({ onOpen }: { onOpen: () => void }) {
  const sync = useSync();
  const items = sync.connections.filter((c) => c.status !== "disconnected");
  if (!items.length) return null;
  return (
    <section className="panel sync-overview" aria-labelledby="sync-heading">
      <div className="panel-heading">
        <div>
          <h2 id="sync-heading">Sources</h2>
          <p className="text-secondary text-sm">
            Imported mail and Classroom work become tasks after academic checks;
            unclear items go to Needs attention.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onOpen}>
          Manage
        </Button>
      </div>
      <ul className="sync-rows">
        {items.map((c) => (
          <li key={c.id}>
            <strong>
              {services[c.service].label} · {c.account.email}
            </strong>
            <SyncStatus c={c} driving={sync.driving.has(c.id)} />
          </li>
        ))}
      </ul>
    </section>
  );
}
