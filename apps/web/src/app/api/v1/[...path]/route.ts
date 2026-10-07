import { NextResponse } from "next/server";
import { backend, csrf, sessionCookie, cookieOptions } from "@/lib/server";
async function proxy(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  if (
    !["me", "overview", "tasks", "subjects"].includes(path[0]) ||
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
