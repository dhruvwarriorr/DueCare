"use client";
// Opening DueCare shows the last saved tasks at once and refreshes them; data is reloaded only
// when the server says something changed. Saved data lives in this browser only and is cleared
// on sign-out, on the sign-in page, and when the account is deleted.
import { useEffect, useRef, useState } from "react";
import {
  dehydrate,
  hydrate,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { api, ApiError, formatTime } from "./api";

const KEY = "duecare.saved.v1";
// What is worth showing before the network answers: lists, counts, subjects, the profile.
const SAVED = new Set([
  "tasks",
  "overview",
  "subjects",
  "me",
  "rules",
  "timetable",
  "activity",
]);
const LIMIT = 2_000_000; // Characters; a very large workspace simply is not saved.

export function clearSavedData() {
  try {
    localStorage.removeItem(KEY);
  } catch {}
}

/** Put the last saved data into the cache; returns when it was saved, or null. Saved data only
 * fills gaps: a query that already has data, or is already loading, keeps the fresh answer. */
export function restoreSaved(client: QueryClient): string | null {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "null");
    if (!saved?.state?.queries) return null;
    const cache = client.getQueryCache();
    const missing = saved.state.queries.filter((q: { queryHash: string }) => {
      const existing = cache.get(q.queryHash);
      return (
        !existing ||
        (!existing.state.dataUpdatedAt && existing.state.fetchStatus === "idle")
      );
    });
    // Saved data is always stale: it shows at once, and a fresh load always follows.
    const stale = missing.map((q: { state: object }) => ({
      ...q,
      state: { ...q.state, dataUpdatedAt: 1 },
    }));
    hydrate(client, { ...saved.state, queries: stale });
    return saved.at;
  } catch {
    return null;
  }
}

/** Keep saving the cache (a moment after it changes) while the app is open. */
export function useSaveData(client: QueryClient, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const save = () => {
      const state = dehydrate(client, {
        shouldDehydrateQuery: (q) =>
          q.state.status === "success" && SAVED.has(String(q.queryKey[0])),
      });
      try {
        const text = JSON.stringify({ at: new Date().toISOString(), state });
        if (text.length <= LIMIT) localStorage.setItem(KEY, text);
      } catch {}
    };
    const unsubscribe = client.getQueryCache().subscribe((event) => {
      if (event.type !== "updated" || event.action.type !== "success") return;
      clearTimeout(timer);
      timer = setTimeout(save, 2000);
    });
    return () => {
      clearTimeout(timer);
      unsubscribe();
    };
  }, [client, enabled]);
}

const RELOAD = ["tasks", "task", "overview", "review-items", "review-item", "activity",
  "evidence", "history", "rules", "subjects", "me"]; // prettier-ignore

/** Poll a tiny change stamp; reload data only when it moves. Reports whether the server answers. */
export function useChangeWatch(enabled: boolean) {
  const client = useQueryClient();
  const last = useRef<string | null>(null);
  const stamp = useQuery({
    queryKey: ["changes"],
    queryFn: () => api<{ version: string }>("/changes"),
    enabled,
    refetchInterval: 20000,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const version = stamp.data?.version;
  useEffect(() => {
    if (!version) return;
    if (last.current && last.current !== version)
      for (const key of RELOAD)
        void client.invalidateQueries({ queryKey: [key] });
    last.current = version;
  }, [version, client]);
  // Only a failed connection means the server is unreachable; an error answer is a server reply.
  return { reachable: !(stamp.isError && !(stamp.error instanceof ApiError)) };
}

/** Shown when the server cannot be reached: what is on screen is the saved copy. */
export function OfflineBanner({
  reachable,
  savedAt,
}: {
  reachable: boolean;
  savedAt: string | null;
}) {
  const [online, setOnline] = useState(true);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  if (online && reachable) return null;
  return (
    <p className="offline-banner" role="status">
      {online ? "Can’t reach DueCare right now" : "You’re offline"}
      {savedAt
        ? " · showing what was saved at " +
          formatTime(savedAt) +
          ". Changes will need a connection."
        : ". Changes will need a connection."}
    </p>
  );
}
