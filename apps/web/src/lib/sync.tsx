"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./api";
import type { Connection, SyncJob } from "./types";

const ACTIVE = ["queued", "running", "waiting_retry"];
type Trigger = "open" | "focus" | "manual";
type SyncState = {
  connections: Connection[];
  isPending: boolean;
  error: Error | null;
  refetch: () => void;
  driving: Set<string>;
  failures: Record<string, Error>;
  syncNow: (id: string) => void;
  reprocess: (id: string) => Promise<void>;
};
const Context = createContext<SyncState | null>(null);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const visible = () => document.visibilityState === "visible";

// The active browser drives bounded sync requests. Work stops being started while the page is
// hidden or closed; an already running request may finish and the server keeps its checkpoint.
export function SyncProvider({
  enabled,
  children,
}: {
  enabled: boolean;
  children: React.ReactNode;
}) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["connections"],
    queryFn: () => api<{ items: Connection[] }>("/connections"),
    enabled,
    refetchInterval: (q) =>
      q.state.data?.items.some((c) => c.activeJob) ? 10000 : false,
  });
  const running = useRef(new Set<string>());
  const [driving, setDriving] = useState(new Set<string>());
  const [failures, setFailures] = useState<Record<string, Error>>({});
  const refresh = useCallback(async () => {
    await client.invalidateQueries({ queryKey: ["connections"] });
    await client.invalidateQueries({ queryKey: ["overview"] });
    // Discovery can add Classroom courses or change a linked course's availability.
    await client.invalidateQueries({ queryKey: ["classroom-courses"] });
    await client.invalidateQueries({ queryKey: ["subjects"] });
  }, [client]);
  const drive = useCallback(
    async (id: string, trigger: Trigger, existing?: SyncJob) => {
      if (running.current.has(id) || !visible()) return;
      running.current.add(id);
      setDriving(new Set(running.current));
      setFailures((f) => {
        const rest = { ...f };
        delete rest[id];
        return rest;
      });
      try {
        let job =
          existing ||
          (
            await api<{ job: SyncJob | null }>(
              "/connections/" + id + "/sync",
              "POST",
              { trigger },
            )
          ).job;
        while (job && ACTIVE.includes(job.status) && visible()) {
          if (job.status === "waiting_retry" && job.nextRetryAt) {
            const wait = new Date(job.nextRetryAt).getTime() - Date.now();
            if (wait > 0) {
              await refresh();
              await sleep(Math.min(wait + 250, 30000));
              continue;
            }
          }
          try {
            job = await api<SyncJob>(
              "/sync-jobs/" + job.id + "/advance",
              "POST",
            );
          } catch (e) {
            // Another tab holds this connection's lease: watch it rather than duplicating work.
            if (!(e instanceof ApiError) || e.status !== 409) throw e;
            await sleep(5000);
            job = await api<SyncJob>("/sync-jobs/" + job.id);
          }
          await refresh(); // Show partial results as each bounded request completes.
        }
      } catch (e) {
        setFailures((f) => ({ ...f, [id]: e as Error }));
      } finally {
        running.current.delete(id);
        setDriving(new Set(running.current));
        await refresh();
      }
    },
    [refresh],
  );
  const items = query.data?.items;
  const started = useRef(false);
  useEffect(() => {
    if (!items || started.current) return;
    started.current = true;
    for (const c of items)
      if (c.status === "active")
        void drive(c.id, "open", c.activeJob || undefined);
  }, [items, drive]);
  useEffect(() => {
    const onVisible = async () => {
      if (!visible() || !enabled) return;
      const latest = await client.fetchQuery({
        queryKey: ["connections"],
        queryFn: () => api<{ items: Connection[] }>("/connections"),
      });
      // Resume unfinished work on return; otherwise the server applies the 15-minute rule.
      for (const c of latest.items)
        if (c.status === "active")
          void drive(c.id, "focus", c.activeJob || undefined);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [client, drive, enabled]);
  const reprocess = useCallback(
    async (id: string) => {
      const { job } = await api<{ job: SyncJob }>(
        "/connections/" + id + "/reprocess",
        "POST",
      );
      await drive(id, "manual", job);
    },
    [drive],
  );
  return (
    <Context.Provider
      value={{
        connections: items || [],
        isPending: query.isPending && enabled,
        error: query.error,
        refetch: () => void query.refetch(),
        driving,
        failures,
        syncNow: (id) => void drive(id, "manual"),
        reprocess,
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useSync() {
  const value = useContext(Context);
  if (!value) throw new Error("SyncProvider is missing");
  return value;
}
