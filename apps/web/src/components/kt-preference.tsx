"use client";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Profile } from "@/lib/types";
import { ErrorNotice } from "./ui/field";

// KT (ATKT/backlog) notices only concern students re-taking a failed subject.
export function KtPreference({ profile }: { profile: Profile }) {
  const client = useQueryClient();
  // The choice shows at once and reverts if saving fails.
  const [ignore, setIgnore] = useState(profile.ignoreKtNotices);
  const save = useMutation({
    mutationFn: (value: boolean) =>
      api<Profile>("/me", "PATCH", {
        revision: profile.revision,
        ignoreKtNotices: value,
      }),
    onSuccess: (p) => client.setQueryData(["me"], p),
    onError: () => setIgnore(profile.ignoreKtNotices),
  });
  const choose = (value: boolean) => {
    setIgnore(value);
    save.mutate(value);
  };
  return (
    <section className="panel form-panel kt-panel">
      <h2>KT notices</h2>
      <p className="text-secondary mt-2">
        Emails and Classroom posts meant only for students with a KT (ATKT
        exams, KT forms and fees, KT results) can be skipped.
      </p>
      <fieldset className="mode-choice" disabled={save.isPending}>
        <legend className="sr-only">KT notices</legend>
        <label>
          <input
            type="radio"
            name="kt"
            checked={!ignore}
            onChange={() => choose(false)}
          />
          <span>
            Show KT notices
            <small>I have a KT subject, or I want to see them.</small>
          </span>
        </label>
        <label>
          <input
            type="radio"
            name="kt"
            checked={ignore}
            onChange={() => choose(true)}
          />
          <span>
            Ignore KT notices
            <small>
              Gmail and Classroom items only for KT students create no tasks or
              reviews.
            </small>
          </span>
        </label>
      </fieldset>
      <p className="form-help">
        Notices for regular and KT students together are always kept, and work
        you already track keeps receiving updates. The choice applies to newly
        processed messages; after switching to Show, use Reprocess on Sources to
        bring back earlier KT notices.
      </p>
      <p role="status" className="text-xs text-secondary">
        {save.isSuccess ? "Saved" : ""}
      </p>
      <ErrorNotice error={save.error} />
    </section>
  );
}
