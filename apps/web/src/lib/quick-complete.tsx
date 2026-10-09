"use client";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { api } from "@/lib/api";
import type { Task } from "@/lib/types";

// The bubble fills, then the item folds away; keep in step with .leaving in globals.css.
const LEAVE_MS = 520;
type Notice = { task: Task; error?: string };
const Ctx = createContext<{
  complete: (task: Task) => void;
  state: (id: string) => "" | "leaving" | "gone";
}>({ complete: () => {}, state: () => "" });

export function QuickCompleteProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const client = useQueryClient();
  const [leaving, setLeaving] = useState<Set<string>>(new Set());
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<Notice | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const edit = (set: typeof setLeaving, id: string, add: boolean) =>
    set((s) => {
      const next = new Set(s);
      if (add) next.add(id);
      else next.delete(id);
      return next;
    });
  const refresh = () =>
    Promise.all(
      ["tasks", "overview", "task", "history"].map((key) =>
        client.invalidateQueries({ queryKey: [key] }),
      ),
    );
  useEffect(() => {
    if (!notice) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(timer.current);
  }, [notice]);

  function complete(task: Task) {
    edit(setLeaving, task.id, true);
    const saving = api<Task>("/tasks/" + task.id, "PATCH", {
      revision: task.revision,
      status: "completed",
    });
    const folded = new Promise((r) => setTimeout(r, LEAVE_MS));
    saving
      .then(async (saved) => {
        await folded;
        edit(setGone, task.id, true);
        edit(setLeaving, task.id, false);
        setNotice({ task: saved });
        await refresh();
      })
      .catch((e: Error) => {
        edit(setLeaving, task.id, false);
        setNotice({ task, error: e.message });
      });
  }
  async function undo(task: Task) {
    setNotice(null);
    try {
      await api("/tasks/" + task.id, "PATCH", {
        revision: task.revision,
        status: "due",
      });
      edit(setGone, task.id, false);
      await refresh();
    } catch (e) {
      setNotice({ task, error: (e as Error).message });
    }
  }
  return (
    <Ctx.Provider
      value={{
        complete,
        state: (id) =>
          gone.has(id) ? "gone" : leaving.has(id) ? "leaving" : "",
      }}
    >
      {children}
      {notice && (
        <div className={"toast" + (notice.error ? " error" : "")} role="status">
          {notice.error ? (
            <span>
              Couldn’t mark “{notice.task.title}” done. {notice.error}
            </span>
          ) : (
            <>
              <Check size={18} aria-hidden="true" />
              <span>
                Marked done: <strong>{notice.task.title}</strong>
              </span>
              <button onClick={() => undo(notice.task)}>Undo</button>
            </>
          )}
        </div>
      )}
    </Ctx.Provider>
  );
}

export const useQuickComplete = () => useContext(Ctx);

export function DoneButton({
  task,
  compact,
}: {
  task: Task;
  compact?: boolean;
}) {
  const { complete, state } = useQuickComplete();
  if (task.status === "completed") return null;
  return (
    <button
      type="button"
      className={"done-button" + (compact ? " compact" : "")}
      aria-label={"Mark done: " + task.title}
      title="Mark done"
      disabled={state(task.id) !== ""}
      onClick={() => complete(task)}
    >
      <span className="bubble" aria-hidden="true">
        <Check size={compact ? 9 : 11} strokeWidth={3} />
      </span>
    </button>
  );
}
