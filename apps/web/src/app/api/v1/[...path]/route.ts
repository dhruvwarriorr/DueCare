import { NextResponse } from "next/server";
import { backend, csrf, sessionCookie, cookieOptions } from "@/lib/server";
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
];
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
  const response = await backend(
    "/api/v1/" +
      path.map(encodeURIComponent).join("/") +
      new URL(request.url).search,
    {
      method: request.method,
      body: request.method === "GET" ? undefined : await request.text(),
      headers: {
        "Idempotency-Key": request.headers.get("idempotency-key") || "",
      },
    },
    path[0] === "sync-jobs" && path[2] === "advance" ? 140000 : 25000,
  );
  const res = new NextResponse(await response.text(), {
    status: response.status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      "X-Request-ID": response.headers.get("x-request-id") || "",
    },
  });
  if (response.status === 401)
    res.cookies.set(sessionCookie, "", { ...cookieOptions, maxAge: 0 });
  return res;
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PATCH,
  proxy as PUT,
  proxy as DELETE,
};
