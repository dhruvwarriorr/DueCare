"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "./ui/button";
import { ErrorNotice } from "./ui/field";
type Result = { status: string; stage: string; errorCode: string | null };
export function AccountDeletion() {
  const [job, setJob] = useState<Result | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const resume = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      let result = await api<Result>("/privacy/account-deletion");
      setJob(result);
      while (
        result.status !== "completed" &&
        document.visibilityState === "visible"
      ) {
        result = await api<Result>("/privacy/account-deletion", "POST");
        setJob(result);
        if (result.status === "waiting_retry") break;
      }
    } catch (e) {
      setError(e as Error);
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => void resume(), 0);
    return () => clearTimeout(timer);
  }, [resume]);
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
          : "Your workspace is frozen. Keep this page open to complete deletion. You can return to this page in this browser to resume saved progress."}
      </p>
      <ErrorNotice error={error} />
      {job?.status !== "completed" && (
        <>
          <p role="status">
            {busy
              ? "Working on: " + (job?.stage || "saved progress")
              : job?.errorCode
                ? "Google could not be reached. Retry to finish revoking access."
                : "Ready to resume"}
          </p>
          <Button disabled={busy} onClick={() => resume()}>
            {busy ? "Deleting…" : "Resume deletion"}
          </Button>
          <Link href="/?view=settings">Return to account settings</Link>
        </>
      )}
      {job?.status === "completed" && (
        <Link href="/sign-in">Back to sign in</Link>
      )}
    </main>
  );
}
