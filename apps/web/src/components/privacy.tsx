"use client";
import { useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api, formatTime } from "@/lib/api";
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
type Suppression = { id: string; createdAt: string; revision: number };
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
  });
  const suppressed = useInfiniteQuery({
    queryKey: ["suppressions"],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Page<Suppression>>(
        "/suppression-records?" +
          new URLSearchParams(pageParam ? { cursor: pageParam } : {}),
      ),
    getNextPageParam: (p) => p.nextCursor || undefined,
  });
  const [confirm, setConfirm] = useState<Connection | "account" | null>(null);
  const [word, setWord] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [notice, setNotice] = useState("");
  const refresh = async () => {
    await client.invalidateQueries();
  };
  async function drive(job: PrivacyJob) {
    setBusy(job.id);
    setError(null);
    try {
      while (
        job.status !== "completed" &&
        document.visibilityState === "visible"
      ) {
        job = await api<PrivacyJob>(
          "/privacy/jobs/" + job.id + "/advance",
          "POST",
        );
        if (job.status === "waiting_retry") break;
      }
      await refresh();
    } catch (e) {
      setError(e as Error);
      await refresh();
    } finally {
      setBusy(null);
    }
  }
  const remove = useMutation({
    mutationFn: (c: Connection) =>
      api<PrivacyJob>("/privacy/source-data-deletions", "POST", {
        connectionId: c.id,
        revision: c.revision,
      }),
    onSuccess: (job) => {
      setConfirm(null);
      void drive(job);
    },
  });
  const restore = useMutation({
    mutationFn: (id: string) =>
      api("/suppression-records/" + id + "/restore", "POST"),
    onSuccess: async () => {
      setNotice(
        "Import restored. Choose Reimport on the matching source to fetch it again.",
      );
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
          error ||
          connections.error ||
          jobs.error ||
          suppressed.error ||
          remove.error ||
          restore.error ||
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
        Deleted activities stay suppressed during future syncs. Restoring an
        import makes it eligible again; reimport fetches the normal source
        history window. It does not restore deleted data from a backup.
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
                {j.errorCode ? " · Retry needed" : ""}
              </p>
              {j.status === "completed" && (
                <small>
                  {j.progress.deletedTasks || 0} tasks removed ·{" "}
                  {j.progress.preservedTasks || 0} preserved
                </small>
              )}
            </div>
            {j.status !== "completed" && (
              <Button disabled={!!busy} onClick={() => drive(j)}>
                {busy === j.id ? "Working…" : "Resume"}
              </Button>
            )}
          </div>
        ))}
      {jobs.hasNextPage && (
        <Button variant="ghost" onClick={() => jobs.fetchNextPage()}>
          Load more privacy operations
        </Button>
      )}
      <details>
        <summary>Restore deleted imports</summary>
        <p className="text-secondary text-sm">
          Only hashed source identifiers and deletion times remain. Each row
          represents a suppressed activity; source content is not retained.
        </p>
        {suppressed.isPending ? (
          <p role="status">Loading deleted imports…</p>
        ) : suppressed.data?.pages.some((p) => p.items.length) ? (
          suppressed.data.pages
            .flatMap((p) => p.items)
            .map((s) => (
              <div className="privacy-row" key={s.id}>
                <div>
                  <strong>Deleted import {s.id.slice(0, 8)}</strong>
                  <p className="text-secondary">{formatTime(s.createdAt)}</p>
                </div>
                <Button
                  disabled={restore.isPending || !!busy}
                  variant="outline"
                  onClick={() => restore.mutate(s.id)}
                >
                  Restore import
                </Button>
              </div>
            ))
        ) : (
          <p>No deleted imports to restore.</p>
        )}
        {suppressed.hasNextPage && (
          <Button variant="ghost" onClick={() => suppressed.fetchNextPage()}>
            Load more deleted imports
          </Button>
        )}
      </details>
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
            : "Source-only tasks are removed. Student-created and edited work, and tasks with another source, stay. Removed imports remain suppressed until you restore them."
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
