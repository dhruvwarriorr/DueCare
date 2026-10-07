import { NextResponse } from "next/server";
import { backend, csrf, stateCookie, cookieOptions } from "@/lib/server";
export async function POST(request: Request) {
  if (!(await csrf(request)))
    return NextResponse.json(
      { message: "Refresh the page and try again" },
      { status: 403 },
    );
  const response = await backend("/internal/auth/start", { method: "POST" });
  const body = await response.json();
  if (!response.ok) return NextResponse.json(body, { status: response.status });
  const res = NextResponse.json(
    { url: body.url },
    { headers: { "Cache-Control": "no-store" } },
  );
  res.cookies.set(stateCookie, body.state, { ...cookieOptions, maxAge: 600 });
  return res;
}
