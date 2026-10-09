"use client";
import { useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { Bell, ArrowUpRight, CheckCheck } from "lucide-react";
import { api, formatTime } from "@/lib/api";
import type { Page } from "@/lib/types";
import { Button } from "./ui/button";
import { ErrorNotice } from "./ui/field";
export type ActivityItem = {
  id: string;
  message: string;
  eventType: string;
  targetType: string;
  targetId: string;
  readAt: string | null;
  createdAt: string;
  revision: number;
};
export function ActivityInbox({
  onOpen,
}: {
  onOpen: (item: ActivityItem) => void;
}) {
  const [filter, setFilter] = useState("");
  const client = useQueryClient();
  const query = useInfiniteQuery({
    queryKey: ["activity", filter],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Page<ActivityItem> & { unreadCount: number }>(
        "/activity?" +
          new URLSearchParams({
            ...(filter ? { read: filter } : {}),
            ...(pageParam ? { cursor: pageParam } : {}),
          }),
      ),
    getNextPageParam: (p) => p.nextCursor || undefined,
    refetchInterval: 30000,
  });
  const mark = useMutation({
    mutationFn: ({ item, read }: { item: ActivityItem; read: boolean }) =>
      api("/activity/" + item.id, "PATCH", { read, revision: item.revision }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["activity"] }),
  });
  const markAll = useMutation({
    mutationFn: () => api("/activity/read-all", "POST"),
    onSuccess: () => client.invalidateQueries({ queryKey: ["activity"] }),
  });
  const items = query.data?.pages.flatMap((p) => p.items) || [];
  const unread = query.data?.pages[0]?.unreadCount || 0;
  return (
    <>
      <div className="section-bar">
        <div>
          <h2>Activity</h2>
          <p className="text-secondary">
            New work, changes, and items that need your attention.
          </p>
        </div>
        <div className="activity-tools">
          {unread > 0 && (
            <Button
              variant="outline"
              size="sm"
              disabled={markAll.isPending}
              onClick={() => markAll.mutate()}
            >
              <CheckCheck size={15} />
              Mark all as read
            </Button>
          )}
          <label>
            <span className="sr-only">Activity filter</span>
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">All activity</option>
              <option value="false">Unread</option>
              <option value="true">Read</option>
            </select>
          </label>
        </div>
      </div>
      <ErrorNotice
        error={query.error || mark.error || markAll.error}
        retry={() => query.refetch()}
      />
      <section className="panel activity-list" aria-label="Activity inbox">
        {query.isPending ? (
          <p className="empty-small" role="status">
            Loading activity…
          </p>
        ) : items.length ? (
          items.map((item) => (
            <article
              className={"activity-item " + (!item.readAt ? "unread" : "")}
              key={item.id}
            >
              <Bell size={18} aria-hidden="true" />
              <div>
                <p>{item.message}</p>
                <small className="text-secondary">
                  {formatTime(item.createdAt)} ·{" "}
                  {item.readAt ? "Read" : "Unread"}
                </small>
                <div className="activity-actions">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      onOpen(item);
                      if (!item.readAt) mark.mutate({ item, read: true });
                    }}
                  >
                    Open <ArrowUpRight size={14} />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={mark.isPending}
                    onClick={() => mark.mutate({ item, read: !item.readAt })}
                  >
                    {item.readAt ? "Mark unread" : "Mark read"}
                  </Button>
                </div>
              </div>
            </article>
          ))
        ) : (
          <div className="empty">
            <Bell size={28} />
            <h3>No activity here yet</h3>
            <p>Updates will appear as you add work and sync sources.</p>
          </div>
        )}
      </section>
      {query.hasNextPage && (
        <Button
          variant="outline"
          disabled={query.isFetchingNextPage}
          onClick={() => query.fetchNextPage()}
        >
          Load more activity
        </Button>
      )}
    </>
  );
}
