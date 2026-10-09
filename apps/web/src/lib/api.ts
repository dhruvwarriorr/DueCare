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
    headers["Idempotency-Key"] =
      options.idempotencyKey || crypto.randomUUID();
  }
  const response = await fetch(
    path.startsWith("/auth") ? path : "/api/v1" + path,
    {
      method,
      headers,
      body:
        body === undefined ? undefined : form ? body : JSON.stringify(body),
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
    : "No precise cutoff";
}
