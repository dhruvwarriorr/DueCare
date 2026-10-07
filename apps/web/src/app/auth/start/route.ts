import { NextResponse } from "next/server";
import { backend, csrf, stateCookie, cookieOptions } from "@/lib/server";
export async function POST(request: Request) {
  if (!(await csrf(request)))
    return NextResponse.json(
      { message: "Refresh the page and try again" },
      { status: 403 },
    );
  const input = await request.json().catch(() => ({}));
  // consent re-asks Google for Gmail and Classroom access (e.g. after it was declined or revoked).
  const response = await backend("/internal/auth/start", {
    method: "POST",
    body: JSON.stringify({ consent: Boolean(input?.consent) }),
  });
  const body = await response.json();
  if (!response.ok) return NextResponse.json(body, { status: response.status });
  const res = NextResponse.json(
    { url: body.url },
    { headers: { "Cache-Control": "no-store" } },
  );
  res.cookies.set(stateCookie, body.state, { ...cookieOptions, maxAge: 600 });
  return res;
}
