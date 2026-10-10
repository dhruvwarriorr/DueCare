// Custom dispatcher authentication is checked by a service-only, fixed-purpose RPC.
// Never log headers, filenames, request bodies or Storage credentials.
Deno.serve(async (request: Request) => {
  if (request.method !== "POST") return new Response(null, { status: 405 });
  const authorization = request.headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer ")) return new Response(null, { status: 401 });
  const base = Deno.env.get("SUPABASE_URL")!;
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const headers = { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json" };
  try {
    const listed = await fetch(`${base}/rest/v1/rpc/duecare_expired_timetable_uploads`, {
      method: "POST", headers,
      body: JSON.stringify({ dispatch_secret: authorization.slice(7) }),
      signal: AbortSignal.timeout(10000),
    });
    if (!listed.ok) return new Response(null, { status: listed.status >= 500 ? 503 : 401 });
    const rows: { name: string }[] = await listed.json();
    if (rows.length) {
      const removed = await fetch(`${base}/storage/v1/object/duecare-timetable-temp`, {
        method: "DELETE", headers, body: JSON.stringify({ prefixes: rows.map((r) => r.name) }),
        signal: AbortSignal.timeout(15000),
      });
      if (!removed.ok) return new Response(null, { status: 503 });
    }
    return Response.json({ removed: rows.length });
  } catch {
    return new Response(null, { status: 503 });
  }
});
