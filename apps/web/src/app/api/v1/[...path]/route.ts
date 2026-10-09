import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import {
  backend,
  csrf,
  sessionCookie,
  cookieOptions,
  deletionCookie,
} from "@/lib/server";
// A sync advance uses a 90-second work budget plus provider and response overhead.
export const maxDuration = 150;
const routes = [
  "me",
  "overview",
  "tasks",
  "subjects",
  "connections",
  "sync-jobs",
  "sender-preferences",
  "review-items",
  "rules",
  "task-merges",
  "evidence",
  "activity",
  "privacy",
  "suppression-records",
  "timetable-imports",
];
// Timetable uploads: one PDF or two pictures, 20 MB in total, plus multipart overhead.
const maxUploadBytes = 20 * 1024 * 1024 + 512 * 1024;
async function proxy(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  if (
    !routes.includes(path[0]) ||
    // OAuth callbacks arrive only through /connections/callback, which redirects the browser.
    (path[0] === "connections" && path[1] === "oauth") ||
    path.some((p) => p === ".." || p.includes("/"))
  ) {
    return NextResponse.json({ message: "Not found" }, { status: 404 });
  }
  if (request.method !== "GET" && !(await csrf(request)))
    return NextResponse.json(
      { message: "Refresh the page and try again" },
      { status: 403 },
    );
  const route = path.join("/");
  const uploading = route === "timetable-imports/extract";
  if (uploading) {
    const size = Number(request.headers.get("content-length"));
    if (!size || size > maxUploadBytes)
      return NextResponse.json(
        {
          code: "FILE_TOO_LARGE",
          message: "Uploads are limited to 20 MB in total",
        },
        { status: 413 },
      );
    if (
      !request.headers.get("content-type")?.startsWith("multipart/form-data")
    )
      return NextResponse.json(
        { code: "UNSUPPORTED_FILE", message: "Upload the timetable as a file" },
        { status: 415 },
      );
  }
  const deleting = route === "privacy/account-deletion";
  const ticket = deleting
    ? (await cookies()).get(deletionCookie)?.value
    : undefined;
  const resuming =
    deleting && ticket && ["GET", "POST"].includes(request.method);
  const response = await backend(
    resuming
      ? "/internal/privacy/account-deletion"
      : "/api/v1/" +
          path.map(encodeURIComponent).join("/") +
          new URL(request.url).search,
    {
      method: resuming ? "POST" : request.method,
      body: resuming
        ? JSON.stringify({ token: ticket, advance: request.method === "POST" })
        : request.method === "GET"
          ? undefined
          : uploading
            ? // Binary files pass through unchanged with their multipart boundary.
              await request.arrayBuffer()
            : await request.text(),
      headers: {
        "Idempotency-Key": request.headers.get("idempotency-key") || "",
        ...(uploading
          ? { "Content-Type": request.headers.get("content-type") as string }
          : {}),
      },
    },
    path[0] === "sync-jobs" && path[2] === "advance"
      ? 140000
      : // Reading allows 45 seconds (pictures use a vision model); organizing allows 60.
        uploading
        ? 60000
        : route === "timetable-imports/interpret"
          ? 75000
          : 25000,
  );
  let payload = await response.text();
  let resumeToken: string | undefined;
  let deleted = false;
  if (deleting && response.ok) {
    const data = JSON.parse(payload);
    resumeToken = data.resumeToken;
    delete data.resumeToken;
    deleted = data.status === "completed";
    payload = JSON.stringify(data);
  }
  const res = new NextResponse(payload, {
    status: response.status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      "X-Request-ID": response.headers.get("x-request-id") || "",
    },
  });
  if (response.status === 401)
    res.cookies.set(sessionCookie, "", { ...cookieOptions, maxAge: 0 });
  if (resumeToken)
    res.cookies.set(deletionCookie, resumeToken, {
      ...cookieOptions,
      maxAge: 30 * 86400,
    });
  if (deleted) {
    res.cookies.set(sessionCookie, "", { ...cookieOptions, maxAge: 0 });
    // Keep the minimal completion receipt available for refresh/retry for thirty days.
  }
  return res;
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PATCH,
  proxy as PUT,
  proxy as DELETE,
};
