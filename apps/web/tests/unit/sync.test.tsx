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

describe("active-browser sync", () => {
  it("refreshes tasks while an advance request is still running", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setVisibility("visible");
    server();
    const fetch = global.fetch;
    let release!: () => void;
    let advancing = false;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/advance")) {
        advancing = true;
        await gate;
        return new Response(JSON.stringify(job("completed")), { status: 200 });
      }
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
    await waitFor(() => expect(advancing && reads > 0).toBe(true));
    try {
      const before = reads;
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(reads).toBeGreaterThan(before);
      setVisibility("hidden");
      const hidden = reads;
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(reads).toBe(hidden);
    } finally {
      await act(async () => { release(); });
    }
  });

  it("starts on open and keeps advancing bounded requests until the job finishes", async () => {
    setVisibility("visible");
    const s = server();
    mount();
    await waitFor(() => expect(s.advances()).toBe(3));
    expect(s.calls).toContain("trigger open");
  });

  it("starts no work while hidden and resumes with the focus rule on return", async () => {
    setVisibility("hidden");
    const s = server();
    mount();
    await waitFor(() => expect(s.calls).toContain("GET /api/v1/connections"));
    await new Promise((r) => setTimeout(r, 50));
    expect(s.calls.some((c) => c.endsWith("/sync"))).toBe(false);
    expect(s.advances()).toBe(0);
    setVisibility("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await waitFor(() => expect(s.advances()).toBe(3));
    expect(s.calls).toContain("trigger focus");
  });
});
