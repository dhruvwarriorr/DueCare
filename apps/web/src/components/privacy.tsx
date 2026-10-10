"use client";
import { useEffect, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Connection, Page } from "@/lib/types";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { ErrorNotice } from "./ui/field";
export type PrivacyJob = {
  id: string;
  kind: string;
  connectionId: string;
  status: string;
  stage: string;
  progress: Record<string, number>;
  errorCode: string | null;
};
export function PrivacyControls() {
  const client = useQueryClient();
  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: () => api<{ items: Connection[] }>("/connections"),
  });
  const jobs = useInfiniteQuery({
    queryKey: ["privacy-jobs"],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Page<PrivacyJob>>(
        "/privacy/jobs?" +
          new URLSearchParams(pageParam ? { cursor: pageParam } : {}),
      ),
    getNextPageParam: (p) => p.nextCursor || undefined,
    refetchInterval: (q) =>
      q.state.data?.pages.some((p) =>
        p.items.some((j) => j.status !== "completed"),
      )
        ? 2000
        : false,
    refetchIntervalInBackground: true,
  });
  const [confirm, setConfirm] = useState<Connection | "account" | null>(null);
  const [word, setWord] = useState("");
  const [notice, setNotice] = useState("");
  const refresh = async () => {
    await client.invalidateQueries();
  };
  const remove = useMutation({
    mutationFn: (c: Connection) =>
      api<PrivacyJob>("/privacy/source-data-deletions", "POST", {
        connectionId: c.id,
        revision: c.revision,
      }),
    onSuccess: async () => {
      setConfirm(null);
      await refresh();
    },
  });
  const reimport = useMutation({
    mutationFn: (id: string) => api("/connections/" + id + "/reimport", "POST"),
    onSuccess: async () => {
      setNotice("Reimport queued. Open Sources to follow its progress.");
      await refresh();
    },
  });
  const account = useMutation({
    mutationFn: () =>
      api("/privacy/account-deletion", "POST", { confirmation: word }),
    onSuccess: () => {
      client.clear();
      // A full navigation also discards private component state during account deletion.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/privacy/deletion");
    },
  });
  const busy = remove.isPending || account.isPending;
  const completed =
    jobs.data?.pages
      .flatMap((p) => p.items)
      .filter((j) => j.status === "completed")
      .map((j) => j.id)
      .join(",") || "";
  useEffect(() => {
    if (!completed) return;
    for (const key of [
      "connections",
      "tasks",
      "overview",
      "review-items",
      "evidence",
      "history",
    ])
      void client.invalidateQueries({ queryKey: [key] });
  }, [client, completed]);
  return (
    <section className="panel privacy-panel">
      <h2>Privacy and your data</h2>
      <p className="text-secondary">
        Disconnect in Sources to stop syncing while keeping your work. Deleting
        imported data removes its evidence and reviews. Student-created tasks,
        student edits, and work supported by another source are preserved.
      </p>
      <ErrorNotice
        error={
          connections.error ||
          jobs.error ||
          remove.error ||
          reimport.error ||
          account.error
        }
        retry={() => refresh()}
      />
      {notice && <p role="status">{notice}</p>}
      {connections.isPending ? (
        <p role="status">Loading sources…</p>
      ) : !connections.data?.items.length ? (
        <p>No imported sources to delete.</p>
      ) : (
        connections.data.items.map((c) => (
          <div className="privacy-row" key={c.id}>
            <div>
              <strong>{c.service === "gmail" ? "Gmail" : "Classroom"}</strong>
              <p className="text-secondary">{c.account.email}</p>
            </div>
            <div className="privacy-actions">
              <Button
                variant="outline"
                disabled={!!busy || !!c.privacyJobId}
                onClick={() => setConfirm(c)}
              >
                Delete imported data
              </Button>
              <Button
                variant="ghost"
                disabled={
                  !!busy ||
                  !!c.privacyJobId ||
                  c.status !== "active" ||
                  reimport.isPending
                }
                onClick={() => reimport.mutate(c.id)}
              >
                Reimport
              </Button>
            </div>
          </div>
        ))
      )}
      <p className="text-secondary text-sm">
        Deleted imports stay deleted during future syncs. Reimport fetches the
        normal source history window again; it does not restore deleted data
        from a backup.
      </p>
      {jobs.data?.pages
        .flatMap((p) => p.items)
        .map((j) => (
          <div className="privacy-row" key={j.id}>
            <div>
              <strong>
                {j.kind === "disconnect"
                  ? "Disconnect"
                  : "Imported data deletion"}
              </strong>
              <p className="text-secondary">
                {j.status === "completed" ? "Complete" : "Step: " + j.stage}
                {j.errorCode ? " · Retrying automatically" : ""}
              </p>
              {j.status === "completed" && (
                <small>
                  {j.progress.deletedTasks || 0} tasks removed ·{" "}
                  {j.progress.preservedTasks || 0} preserved
                </small>
              )}
            </div>
            {j.status !== "completed" && (
              <Button disabled={jobs.isFetching} onClick={() => jobs.refetch()}>
                {jobs.isFetching ? "Refreshing…" : "Refresh progress"}
              </Button>
            )}
          </div>
        ))}
      {jobs.hasNextPage && (
        <Button variant="ghost" onClick={() => jobs.fetchNextPage()}>
          Load more privacy operations
        </Button>
      )}
      <div className="privacy-row">
        <div>
          <h3>Delete your account</h3>
          <p className="text-secondary">
            Permanently remove your workspace, source credentials, and DueCare
            login. Google mail and Classroom work remain in Google.
          </p>
        </div>
        <Button
          variant="outline"
          disabled={!!busy}
          onClick={() => {
            setConfirm("account");
            setWord("");
          }}
        >
          Delete account
        </Button>
      </div>
      <Dialog
        open={!!confirm}
        onOpenChange={(v) => {
          if (!v) setConfirm(null);
        }}
        title={
          confirm === "account"
            ? "Delete your DueCare account?"
            : "Delete imported data?"
        }
        description={
          confirm === "account"
            ? "This cannot be undone. Processing stops immediately. Deletion continues in saved steps and can be resumed if interrupted."
            : "Source-only tasks are removed. Student-created and edited work, and tasks with another source, stay. Removed imports stay deleted during future syncs."
        }
      >
        {confirm === "account" && (
          <label className="privacy-confirm">
            Type DELETE to confirm
            <input
              value={word}
              onChange={(e) => setWord(e.target.value)}
              autoComplete="off"
            />
          </label>
        )}
        <ErrorNotice error={remove.error || account.error} />
        <div className="dialog-actions">
          <Button variant="ghost" onClick={() => setConfirm(null)}>
            Cancel
          </Button>
          <Button
            disabled={
              remove.isPending ||
              account.isPending ||
              (confirm === "account" && word !== "DELETE")
            }
            onClick={() => {
              if (confirm === "account") account.mutate();
              else if (confirm) remove.mutate(confirm);
            }}
          >
            {confirm === "account"
              ? "Permanently delete account"
              : "Confirm deletion"}
          </Button>
        </div>
      </Dialog>
    </section>
  );
}
