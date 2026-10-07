import { randomBytes } from "node:crypto";
import { NextResponse } from "next/server";
import { csrfCookie, cookieOptions } from "@/lib/server";
export async function GET() {
  const token = randomBytes(32).toString("base64url");
  const res = NextResponse.json(
    { token },
    { headers: { "Cache-Control": "no-store" } },
  );
  res.cookies.set(csrfCookie, token, cookieOptions);
  return res;
}
