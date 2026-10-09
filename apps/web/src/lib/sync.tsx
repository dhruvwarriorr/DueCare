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
import { api } from "./api";
import type { Connection, SyncJob } from "./types";

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
// The API worker advances saved jobs; the browser only enqueues and observes them.
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
    refetchIntervalInBackground: true,
    refetchInterval: (q) =>
      q.state.data?.items.some((c) => c.activeJob) ? 5000 : false,
  });
  const running = useRef(new Set<string>());
  const [driving, setDriving] = useState(new Set<string>());
  const [failures, setFailures] = useState<Record<string, Error>>({});
  const refresh = useCallback(async () => {
    await Promise.all(
      [
        "connections",
        "overview",
        "classroom-courses",
        "subjects",
        "activity",
        "review-items",
        "review-item",
        "tasks",
        "task",
        "history",
        "evidence",
        "approved-faculty",
        "me",
      ].map((key) => client.invalidateQueries({ queryKey: [key] })),
    );
  }, [client]);
  const hasActiveJob =
    query.data?.items.some((c) => c.activeJob) || driving.size > 0;
  useEffect(() => {
    if (!enabled || !hasActiveJob) return;
    let refreshing = false;
    // An advance can be busy downloading/using AI for up to its work budget. Fetch
    // committed tasks during that request so the dashboard and calendar update live.
    const timer = setInterval(async () => {
      if (refreshing) return;
      refreshing = true;
      try {
        await refresh();
      } finally {
        refreshing = false;
      }
    }, 5000);
    return () => clearInterval(timer);
  }, [enabled, hasActiveJob, refresh]);
  const drive = useCallback(
    async (id: string, trigger: Trigger, existing?: SyncJob) => {
      if (running.current.has(id)) return;
      running.current.add(id);
      setDriving(new Set(running.current));
      setFailures((f) => {
        const rest = { ...f };
        delete rest[id];
        return rest;
      });
      try {
        if (!existing)
          await api("/connections/" + id + "/sync", "POST", { trigger });
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
      if (c.status === "active" && !c.privacyJobId)
        void drive(c.id, "open", c.activeJob || undefined);
  }, [items, drive]);
  useEffect(() => {
    const onVisible = async () => {
      if (document.visibilityState !== "visible" || !enabled) return;
      const latest = await client.fetchQuery({
        queryKey: ["connections"],
        queryFn: () => api<{ items: Connection[] }>("/connections"),
      });
      // Refresh progress on return; the worker continues while the browser is hidden.
      for (const c of latest.items)
        if (c.status === "active" && !c.privacyJobId)
          void drive(c.id, "focus", c.activeJob || undefined);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [client, drive, enabled]);
  const reprocess = useCallback(
    async (id: string) => {
      await api("/connections/" + id + "/reprocess", "POST");
      await refresh();
    },
    [refresh],
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
