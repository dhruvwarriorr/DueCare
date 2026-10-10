"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { clearSavedData } from "@/lib/offline";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ErrorNotice } from "./ui/field";
type Result = { status: string; stage: string; errorCode: string | null };
export function AccountDeletion() {
  // Tasks saved in this browser belong to a signed-in session; none survive it.
  useEffect(() => clearSavedData(), []);
  const [client] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={client}>
      <DeletionProgress />
    </QueryClientProvider>
  );
}

// The server deletes the account in these steps; this page only shows how far it has got.
const steps: [string, string][] = [
  ["revoke", "Disconnect Google access"],
  ["data", "Erase your tasks and imported data"],
  ["auth", "Remove your DueCare login"],
];

function DeletionProgress() {
  const query = useQuery({
    queryKey: ["account-deletion"],
    queryFn: () => api<Result>("/privacy/account-deletion"),
    refetchInterval: (q) =>
      q.state.data?.status === "completed" ? false : 2000,
    refetchIntervalInBackground: true,
  });
  const job = query.data;
  const done = job?.status === "completed";
  const current = done
    ? steps.length
    : steps.findIndex(([s]) => s === job?.stage);
  return (
    <main id="main" className="deletion-page">
      <Link href="/sign-in" className="brand">
        DueCare
      </Link>
      <h1>
        {done ? "Your account has been deleted" : "Deleting your account"}
      </h1>
      {done && (
        <p>
          Your workspace, source credentials, and DueCare login were removed.
          Your Google mail and Classroom work remain in Google.
        </p>
      )}
      <ol className="deletion-steps" aria-label="Deletion steps">
        {steps.map(([key, label], i) => (
          <li
            key={key}
            className={i < current ? "done" : i === current ? "current" : ""}
          >
            {label}
            {i < current
              ? " · done"
              : i === current && !done
                ? job?.errorCode
                  ? " · Google is busy, retrying automatically"
                  : " · in progress"
                : ""}
          </li>
        ))}
      </ol>
      <ErrorNotice error={query.error} retry={() => query.refetch()} />
      {!done && (
        <p className="text-secondary text-sm" role="status">
          This page updates by itself.
        </p>
      )}
      {done && <Link href="/sign-in">Back to sign in</Link>}
    </main>
  );
}
