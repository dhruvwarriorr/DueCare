import { NextResponse } from "next/server";
import { backend, csrf, sessionCookie, csrfCookie, cookieOptions } from "@/lib/server";
export async function POST(request: Request) {
  if (!(await csrf(request)))
    return NextResponse.json(
      { message: "Refresh the page and try again" },
      { status: 403 },
    );
  const response = await backend("/internal/auth/logout", { method: "POST" });
  const res = NextResponse.json(await response.json(), {
    status: response.status,
  });
  if (response.ok) {
    res.cookies.set(sessionCookie, "", { ...cookieOptions, maxAge: 0 });
    res.cookies.set(csrfCookie, "", { ...cookieOptions, maxAge: 0 });
  }
  return res;
}
