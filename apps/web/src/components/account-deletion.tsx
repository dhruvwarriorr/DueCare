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
import { Button } from "./ui/button";
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

function DeletionProgress() {
  const query = useQuery({
    queryKey: ["account-deletion"],
    queryFn: () => api<Result>("/privacy/account-deletion"),
    refetchInterval: (q) =>
      q.state.data?.status === "completed" ? false : 2000,
    refetchIntervalInBackground: true,
  });
  const job = query.data;
  return (
    <main id="main" className="deletion-page">
      <Link href="/sign-in" className="brand">
        DueCare
      </Link>
      <h1>
        {job?.status === "completed"
          ? "Your account has been deleted"
          : "Deleting your account"}
      </h1>
      <p>
        {job?.status === "completed"
          ? "Your workspace, source credentials, and DueCare login were removed. Your Google mail and Classroom work remain in Google."
          : "Your workspace is frozen while deletion runs in the background. You can switch tabs, use another app, or close this page. Return here to see progress."}
      </p>
      <ErrorNotice error={query.error} retry={() => query.refetch()} />
      {job?.status !== "completed" && (
        <>
          <p role="status">
            {job?.errorCode
              ? "Google is temporarily unavailable. Deletion will retry automatically."
              : "Working on: " + (job?.stage || "saved progress")}
          </p>
          <Button disabled={query.isFetching} onClick={() => query.refetch()}>
            {query.isFetching ? "Refreshing…" : "Refresh progress"}
          </Button>
        </>
      )}
      {job?.status === "completed" && (
        <Link href="/sign-in">Back to sign in</Link>
      )}
    </main>
  );
}
