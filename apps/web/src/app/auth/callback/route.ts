import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import {
  backend,
  stateCookie,
  sessionCookie,
  cookieOptions,
  deletionCookie,
} from "@/lib/server";
export async function GET(request: Request) {
  const code = new URL(request.url).searchParams.get("code");
  const state = (await cookies()).get(stateCookie)?.value;
  const origin = process.env.WEB_ORIGIN || "http://localhost:3000";
  let session: string | undefined;
  if (code && state) {
    const response = await backend("/internal/auth/callback", {
      method: "POST",
      body: JSON.stringify({ code, state }),
    });
    if (response.ok) session = (await response.json()).session;
  }
  const res = NextResponse.redirect(
    new URL(session ? "/" : "/sign-in?error=callback", origin),
  );
  res.cookies.set(stateCookie, "", { ...cookieOptions, maxAge: 0 });
  if (session) {
    res.cookies.set(deletionCookie, "", { ...cookieOptions, maxAge: 0 });
    res.cookies.set(sessionCookie, session, {
      ...cookieOptions,
      maxAge: 60 * 60 * 24 * 365 * 10,
    });
  }
  return res;
}
