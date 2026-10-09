"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, UserCheck } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "./ui/button";
import { ErrorNotice } from "./ui/field";

type Faculty = { email: string; origin: string; approvedAt: string };

export function FacultyApproval({
  emails = [],
  manage = false,
}: {
  emails?: string[];
  manage?: boolean;
}) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["approved-faculty"],
    queryFn: () => api<{ items: Faculty[] }>("/approved-faculty"),
    enabled: manage || emails.length > 0,
    staleTime: 30_000,
  });
  const mutation = useMutation({
    mutationFn: ({ email, remove }: { email: string; remove: boolean }) =>
      api(
        "/approved-faculty/" + encodeURIComponent(email),
        remove ? "DELETE" : "PUT",
      ),
    onSuccess: async () => {
      await Promise.all(
        [
          "approved-faculty",
          "review-items",
          "tasks",
          "task",
          "overview",
          "connections",
          "me",
        ].map((key) => client.invalidateQueries({ queryKey: [key] })),
      );
    },
  });
  const approved = new Set(query.data?.items.map((item) => item.email));
  const visible = manage
    ? query.data?.items.map((item) => item.email) || []
    : [...new Set(emails)];
  if (!manage && !emails.length) return null;
  return (
    <div className={manage ? "panel p-6 space-y-3" : "faculty-actions"}>
      {manage && (
        <>
          <h2>Approved faculty</h2>
          <p className="text-sm text-secondary">
            Accepted academic mail remembers the exact faculty address. Missing
            class or division details from approved faculty will not need
            confirmation. Other class, batch, and nonacademic mail checks still
            apply.
          </p>
        </>
      )}
      <ErrorNotice
        error={query.error || mutation.error}
        retry={() => query.refetch()}
      />
      {manage && query.isPending && (
        <p role="status">Loading approved faculty…</p>
      )}
      {manage && query.isSuccess && !visible.length && (
        <p className="text-sm text-secondary">
          No faculty approved yet. Approve a sender from Needs attention or a
          task.
        </p>
      )}
      {visible.map((email) => (
        <div key={email} className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-secondary break-all">{email}</span>
          {approved.has(email) ? (
            <>
              <span className="inline-flex items-center gap-1">
                <Check size={13} />
                Approved faculty
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={mutation.isPending}
                aria-label={"Remove faculty approval for " + email}
                onClick={() => mutation.mutate({ email, remove: true })}
              >
                Remove approval
              </Button>
            </>
          ) : (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={mutation.isPending || !query.isSuccess}
              aria-label={"Approve faculty " + email}
              onClick={() => mutation.mutate({ email, remove: false })}
            >
              <UserCheck size={14} />
              Approve faculty
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}
