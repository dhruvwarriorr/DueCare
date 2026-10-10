"use client";
import { useCutoffRefresh } from "@/lib/use-cutoff-refresh";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { api, deadline } from "@/lib/api";
import type { Page, Task } from "@/lib/types";
import { Button } from "./ui/button";
import { ErrorNotice } from "./ui/field";
const todayIST = () =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(
    new Date(),
  );
export function Calendar({
  onOpen,
  controls,
  children,
}: {
  onOpen: (id: string) => void;
  controls?: React.ReactNode;
  children?: React.ReactNode;
}) {
  const [month, setMonth] = useState(() => todayIST().slice(0, 7));
  const [selected, setSelected] = useState(todayIST());
  const [year, m] = month.split("-").map(Number);
  const first = new Date(Date.UTC(year, m - 1, 1));
  const next = new Date(Date.UTC(year, m, 1));
  const dateStart = month + "-01T00:00:00+05:30";
  const dateEnd = next.toISOString().slice(0, 10) + "T00:00:00+05:30";
  const query = useQuery({
    queryKey: ["tasks", "calendar", month],
    queryFn: async () => {
      let cursor = "",
        items: Task[] = [];
      do {
        const params = new URLSearchParams({
          limit: "100",
          dateFrom: dateStart,
          dateTo: dateEnd,
        });
        if (cursor) params.set("cursor", cursor);
        const p = await api<Page<Task>>("/tasks?" + params);
        items = [...items, ...p.items];
        cursor = p.nextCursor || "";
      } while (cursor);
      return items;
    },
  });
  function move(delta: number) {
    const d = new Date(Date.UTC(year, m - 1 + delta, 1));
    setMonth(d.toISOString().slice(0, 7));
    setSelected(d.toISOString().slice(0, 10));
  }
  const rows = query.data || [];
  useCutoffRefresh(rows);
  const slots = Array.from({ length: 42 }, (_, i) => {
    const date = new Date(
      Date.UTC(year, m - 1, 1 - ((first.getUTCDay() + 6) % 7) + i),
    );
    const key = date.toISOString().slice(0, 10);
    return {
      key,
      day: date.getUTCDate(),
      current: date.getUTCMonth() === m - 1,
    };
  });
  const byDay = (date: string) =>
    rows.filter(
      (t) =>
        new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(
          new Date(t.dueAt!),
        ) === date,
    );
  return (
    <>
      <div className="section-bar">
        <div>
          <h2>
            {first.toLocaleDateString("en-IN", {
              month: "long",
              year: "numeric",
              timeZone: "UTC",
            })}
          </h2>
          <p className="text-secondary">
            Confirmed cutoffs in IST. Unknown exam times stay off the calendar.
          </p>
        </div>
        <div className="week-controls">
          {controls}
          <Button
            variant="outline"
            size="icon"
            aria-label="Previous month"
            onClick={() => move(-1)}
          >
            <ChevronLeft size={18} />
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              setMonth(todayIST().slice(0, 7));
              setSelected(todayIST());
            }}
          >
            Today
          </Button>
          <Button
            variant="outline"
            size="icon"
            aria-label="Next month"
            onClick={() => move(1)}
          >
            <ChevronRight size={18} />
          </Button>
        </div>
      </div>
      {children}
      <ErrorNotice error={query.error} retry={() => query.refetch()} />
      {query.isPending && <p role="status">Loading calendar…</p>}
      <div className="calendar panel">
        <div className="calendar-grid calendar-week">
          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
            <div key={d}>{d}</div>
          ))}
        </div>
        <div className="calendar-grid">
          {slots.map((d) => (
            <button
              className={
                "calendar-day " +
                (!d.current ? "outside " : "") +
                (d.key === selected ? "selected" : "")
              }
              key={d.key}
              onClick={() => setSelected(d.key)}
              aria-label={d.key + ", " + byDay(d.key).length + " tasks"}
            >
              <span className={d.key === todayIST() ? "today" : ""}>
                {d.day}
              </span>
              <div className="day-items">
                {byDay(d.key)
                  .slice(0, 2)
                  .map((t) => (
                    <span key={t.id} className={"day-task " + t.status}>
                      {t.title}
                    </span>
                  ))}
                {byDay(d.key).length > 2 && (
                  <span className="text-xs">
                    +{byDay(d.key).length - 2} more
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>
      <section className="mt-6 panel p-5">
        <h3>
          {new Date(selected + "T00:00:00Z").toLocaleDateString("en-IN", {
            weekday: "long",
            day: "numeric",
            month: "long",
            timeZone: "UTC",
          })}
        </h3>
        {byDay(selected).length === 0 ? (
          <p className="text-secondary mt-3">
            No confirmed cutoffs on this day.
          </p>
        ) : (
          byDay(selected).map((t) => (
            <button
              key={t.id}
              className="task-row w-full"
              onClick={() => onOpen(t.id)}
            >
              <strong>{t.title}</strong>
              <span className={"status " + t.status}>{t.status}</span>
              {deadline(t).note && (
                <span className="text-xs text-secondary">
                  {deadline(t).note}
                </span>
              )}
            </button>
          ))
        )}
      </section>
    </>
  );
}
