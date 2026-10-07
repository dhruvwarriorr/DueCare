import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { backend, sessionCookie } from "@/lib/server";
// Google redirects here after source authorization. The DueCare session cookie is required;
// the one-use OAuth state is bound server-side to the student who started the flow.
export async function GET(request: Request) {
  const origin = process.env.WEB_ORIGIN || "http://localhost:3000";
  const params = new URL(request.url).searchParams;
  if (!(await cookies()).get(sessionCookie))
    return NextResponse.redirect(new URL("/sign-in", origin));
  const query = new URLSearchParams();
  for (const key of ["state", "code", "error"]) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  const response = await backend("/api/v1/connections/oauth/callback?" + query);
  const target = new URL("/", origin);
  target.searchParams.set("view", "connections");
  if (response.ok) {
    const body = await response.json();
    target.searchParams.set("connected", body.service);
  } else {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401)
      return NextResponse.redirect(new URL("/sign-in", origin));
    target.searchParams.set(
      "connectionError",
      String(body.code || "CONNECTION_FAILED"),
    );
  }
  const res = NextResponse.redirect(target);
  res.headers.set("Cache-Control", "no-store");
  res.headers.set("Referrer-Policy", "no-referrer");
  return res;
}
