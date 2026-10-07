"use client";
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Task } from "./types";

// Refresh active views at the next status boundary, including an idle open tab.
export function useCutoffRefresh(tasks: readonly Task[]) {
  const client = useQueryClient();
  const cutoffs = tasks
    .filter((t) => !t.completedAt && t.dueAt)
    .map((t) => t.dueAt)
    .sort()
    .join(",");
  const statuses = tasks.map((t) => t.status).join(",");
  useEffect(() => {
    const now = Date.now();
    const next = Math.min(
      ...cutoffs
        .split(",")
        .filter(Boolean)
        .map((t) => new Date(t).getTime())
        .filter((t) => t > now),
    );
    if (!Number.isFinite(next)) return;
    const timer = setTimeout(
      () => {
        void client.invalidateQueries({ queryKey: ["tasks"] });
        void client.invalidateQueries({ queryKey: ["task"] });
        void client.invalidateQueries({ queryKey: ["overview"] });
      },
      Math.min(Math.max(next - Date.now() + 25, 0), 2147483647),
    );
    return () => clearTimeout(timer);
  }, [cutoffs, statuses, client]);
}
