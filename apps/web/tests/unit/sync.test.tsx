import { render, waitFor, act, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { SyncProvider } from "@/lib/sync";

const connection = {
  id: "c1",
  service: "gmail",
  status: "active",
  revision: 1,
  account: { id: "a1", email: "source@example.com", name: null, photo: null },
  permissions: [],
  lastAttemptAt: null,
  lastSuccessAt: null,
  retryAt: null,
  lastError: null,
  activeJob: null,
  lastJob: null,
  records: { awaitingInterpretation: 0, duplicates: 0, blocked: 0, ignored: 0 },
};
function job(status: string) {
  return {
    id: "j1",
    connectionId: "c1",
    status,
    progress: {},
    nextRetryAt: null,
  };
}
function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
}
function server() {
  const calls: string[] = [];
  let advances = 0;
  global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push((init?.method || "GET") + " " + url);
    const body = (data: unknown) =>
      new Response(JSON.stringify(data), { status: 200 });
    if (url === "/auth/csrf") return body({ token: "t" });
    if (url === "/api/v1/connections") return body({ items: [connection] });
    if (url.endsWith("/sync")) {
      const trigger = JSON.parse(String(init?.body)).trigger;
      calls.push("trigger " + trigger);
      return body({ job: job("queued") });
    }
    if (url.endsWith("/advance")) {
      advances += 1;
      // Each bounded request finishes some work; the third completes the job.
      return body(job(advances >= 3 ? "completed" : "queued"));
    }
    return body({});
  }) as typeof fetch;
  return { calls, advances: () => advances };
}
function mount() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <SyncProvider enabled>
        <span />
      </SyncProvider>
    </QueryClientProvider>,
  );
}
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  setVisibility("visible");
});

// The API worker advances saved jobs; the browser only starts syncs and watches their progress.
describe("browser sync", () => {
  it("starts a sync on open and leaves advancing it to the worker", async () => {
    setVisibility("visible");
    const s = server();
    mount();
    await waitFor(() => expect(s.calls).toContain("trigger open"));
    await new Promise((r) => setTimeout(r, 50));
    expect(s.advances()).toBe(0);
  });

  it("refreshes tasks every few seconds while a job runs", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setVisibility("visible");
    const s = server();
    const fetch = global.fetch;
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/v1/connections")
        return new Response(
          JSON.stringify({ items: [{ ...connection, activeJob: job("running") }] }),
          { status: 200 },
        );
      return fetch(input, init);
    }) as typeof fetch;
    let reads = 0;
    function Tasks() {
      const tasks = useQuery({ queryKey: ["tasks"], queryFn: async () => ++reads });
      return <span>{tasks.data}</span>;
    }
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SyncProvider enabled><Tasks /></SyncProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(reads > 0).toBe(true));
    const before = reads;
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(reads).toBeGreaterThan(before);
    expect(s.advances()).toBe(0);
  });

  it("starts a sync with the focus rule when the page becomes visible again", async () => {
    setVisibility("hidden");
    const s = server();
    mount();
    await waitFor(() => expect(s.calls).toContain("GET /api/v1/connections"));
    setVisibility("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await waitFor(() => expect(s.calls).toContain("trigger focus"));
    expect(s.advances()).toBe(0);
  });
});
