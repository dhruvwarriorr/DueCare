import type { Task } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public fields?: Record<string, string>,
    public code?: string,
  ) {
    super(message);
  }
}
let csrfRequest: Promise<string> | undefined;
async function token() {
  if (!csrfRequest)
    csrfRequest = fetch("/auth/csrf", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error("Could not secure this request");
        return (await r.json()).token as string;
      })
      .catch((e) => {
        csrfRequest = undefined;
        throw e;
      });
  return csrfRequest;
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  // A retry of an uncertain write reuses its key so the server replays, never repeats, it.
  options: { idempotencyKey?: string } = {},
): Promise<T> {
  const form = body instanceof FormData;
  // The browser sets the multipart boundary itself for FormData uploads.
  const headers: Record<string, string> = form
    ? {}
    : { "Content-Type": "application/json" };
  if (method !== "GET") {
    headers["X-CSRF-Token"] = await token();
    headers["Idempotency-Key"] = options.idempotencyKey || crypto.randomUUID();
  }
  const response = await fetch(
    path.startsWith("/auth") ? path : "/api/v1" + path,
    {
      method,
      headers,
      body: body === undefined ? undefined : form ? body : JSON.stringify(body),
      cache: "no-store",
    },
  );
  // A proxy, restart, or crash can return non-JSON; report it as a normal request error.
  const text = await response.text();
  let data: {
    message?: string;
    code?: string;
    fieldErrors?: Record<string, string>;
  } = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = {
      message: response.ok
        ? "DueCare returned an unexpected response. Please try again"
        : "DueCare is temporarily unavailable. Please try again",
    };
    if (response.ok) throw new ApiError(data.message as string, 502, undefined);
  }
  if (!response.ok) {
    // Every browser tab must stop exposing private cached work once deletion begins.
    if (data.code === "ACCOUNT_DELETING")
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/privacy/deletion");
    // A full navigation clears in-memory private query data after session expiry.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    if (response.status === 401) window.location.assign("/sign-in");
    throw new ApiError(
      data.message || "Please try again",
      response.status,
      data.fieldErrors,
      data.code,
    );
  }
  return data as T;
}
export const datetimeFields = [
  "dueAt",
  "submissionOpensAt",
  "availabilityOpensAt",
  "availabilityClosesAt",
  "loginByAt",
  "reportingAt",
  "startsAt",
  "endsAt",
] as const;
export function localTime(value: string | null | undefined) {
  if (!value) return "";
  return new Date(new Date(value).getTime() + 330 * 60000)
    .toISOString()
    .slice(0, 16);
}
export function utcTime(value: string) {
  return value ? new Date(value + ":00+05:30").toISOString() : null;
}
export function formatTime(value: string | null | undefined) {
  return value
    ? new Intl.DateTimeFormat("en-IN", {
        timeZone: "Asia/Kolkata",
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }).format(new Date(value))
    : "No due date yet";
}
const dayFormat = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "numeric",
  month: "short",
});
// Calendar dates (YYYY-MM-DD) are India dates; read them at IST midday so no zone shifts the day.
function day(value: string, withYear = false) {
  const d = new Date(value + "T12:00:00+05:30");
  return withYear
    ? dayFormat.format(d) + " " + value.slice(0, 4)
    : dayFormat.format(d);
}
type Dated = Pick<
  Task,
  | "dueAt"
  | "dueDate"
  | "type"
  | "dateWindowStart"
  | "dateWindowEnd"
  | "timingProvenance"
  | "timingTentative"
>;
/** The days a window-derived deadline stands for, when the exact day is not announced. */
export function dueWindow(t: Dated) {
  const basis = t.timingProvenance?.dueAt?.basis || "";
  return t.dateWindowStart && t.dateWindowEnd && basis.endsWith("window-end")
    ? { start: t.dateWindowStart, end: t.dateWindowEnd }
    : null;
}
export function formatRange(start: string, end: string) {
  const sameYear = start.slice(0, 4) === end.slice(0, 4);
  return day(start, !sameYear) + " – " + day(end, true);
}
/** What Classroom shows for the student's turn-in: a returned grade, or that it was late. */
export function classroomNote(t: Pick<Task, "classroom">) {
  const c = t.classroom;
  if (!c) return null;
  const parts: string[] = [];
  if (c.grade !== null && c.grade !== undefined)
    parts.push("graded " + c.grade + (c.maxPoints ? "/" + c.maxPoints : ""));
  else if (c.state === "RETURNED") parts.push("returned");
  if (c.late && (c.state === "TURNED_IN" || c.state === "RETURNED"))
    parts.push("turned in late");
  return parts.length ? parts.join(" · ") : null;
}
/** One description of when work is due, shared by every view. */
export function deadline(t: Dated): { main: string; note: string | null } {
  if (!t.dueAt) return { main: "No due date yet", note: null };
  const tentative = t.timingTentative ? "Tentative · " : "";
  const w = dueWindow(t);
  if (w)
    return {
      main: formatRange(w.start, w.end),
      note: tentative + "exact day not announced",
    };
  if (t.dueDate)
    return {
      main: day(t.dueDate, true),
      note:
        tentative +
        (t.type === "test" ? "time not announced" : "date only · due by 23:59"),
    };
  return {
    main: formatTime(t.dueAt),
    note: t.timingTentative ? "Tentative" : null,
  };
}
