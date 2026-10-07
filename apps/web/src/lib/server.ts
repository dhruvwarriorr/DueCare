import "server-only";
import { cookies } from "next/headers";
import { timingSafeEqual } from "node:crypto";
export const secure = process.env.NODE_ENV === "production";
export const sessionCookie = secure
  ? "__Host-duecare-session"
  : "duecare-session";
export const stateCookie = secure ? "__Host-duecare-login" : "duecare-login";
export const csrfCookie = secure ? "__Host-duecare-csrf" : "duecare-csrf";
export const cookieOptions = {
  httpOnly: true,
  secure,
  sameSite: "lax" as const,
  path: "/",
};
export function equal(a: string, b: string) {
  const x = Buffer.from(a),
    y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}
export async function csrf(request: Request) {
  const origin = process.env.WEB_ORIGIN;
  if (!origin || request.headers.get("origin") !== origin) return false;
  const token = (await cookies()).get(csrfCookie)?.value;
  return Boolean(
    token && equal(token, request.headers.get("x-csrf-token") || ""),
  );
}
export async function backend(path: string, init: RequestInit = {}) {
  if (!process.env.API_URL || !process.env.GATEWAY_SECRET) {
    return Response.json(
      {
        code: "CONFIGURATION_REQUIRED",
        message: "Application setup is not complete",
      },
      { status: 503 },
    );
  }
  const store = await cookies();
  try {
    return await fetch(process.env.API_URL + path, {
      ...init,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Gateway-Secret": process.env.GATEWAY_SECRET,
        "X-Session": store.get(sessionCookie)?.value || "",
        ...init.headers,
      },
      signal: AbortSignal.timeout(25000),
    });
  } catch {
    return Response.json(
      {
        code: "API_UNAVAILABLE",
        message: "Cannot reach DueCare. Please try again",
      },
      { status: 503 },
    );
  }
}
