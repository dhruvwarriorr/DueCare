"use client";
import { useEffect, useMemo, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { DoneButton, useQuickComplete } from "@/lib/quick-complete";
import { api, deadline, dueWindow, formatTime } from "@/lib/api";
import { useCutoffRefresh } from "@/lib/use-cutoff-refresh";
import type { Page, Slot, Subject, Task } from "@/lib/types";
import { Button } from "./ui/button";
import { ErrorNotice } from "./ui/field";
import { Calendar } from "./calendar";

const IST = "Asia/Kolkata";
const HOUR = 58;
const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const kindShort: Record<string, string> = {
  theory: "Theory",
  lab: "Lab",
  tutorial: "Tutorial",
};
const dateFmt = new Intl.DateTimeFormat("en-CA", { timeZone: IST });
const timeFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: IST,
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
export const dayKey = (d: Date) => dateFmt.format(d);
function addDays(key: string, n: number) {
  const d = new Date(key + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
function mondayOf(key: string) {
  const d = new Date(key + "T00:00:00Z");
  return addDays(key, -((d.getUTCDay() + 6) % 7));
}
function minutesOf(iso: string) {
  const [h, m] = timeFmt.format(new Date(iso)).split(":").map(Number);
  return h * 60 + m;
}
const clock = (min: number) =>
  String(Math.floor(min / 60)).padStart(2, "0") +
  ":" +
  String(min % 60).padStart(2, "0");
const hhmm = (t: string) => t.slice(0, 5);
const toMinutes = (t: string) => {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + (m || 0);
};
const shortDate = (key: string) =>
  new Date(key + "T00:00:00Z").toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
function rangeLabel(monday: string) {
  const sunday = addDays(monday, 6);
  const a = new Date(monday + "T00:00:00Z");
  const b = new Date(sunday + "T00:00:00Z");
  const sameMonth = a.getUTCMonth() === b.getUTCMonth();
  const end = b.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
  return (sameMonth ? a.getUTCDate() : shortDate(monday)) + " – " + end;
}
function countdown(ms: number) {
  const min = Math.max(0, Math.round(ms / 60000));
  if (min < 60) return min + " min";
  const h = Math.floor(min / 60);
  if (h < 24) return h + " h " + (min % 60) + " min";
  return Math.floor(h / 24) + " d " + (h % 24) + " h";
}
export function useNow(step = 30000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), step);
    return () => clearInterval(timer);
  }, [step]);
  return now;
}
type Overview = {
  counts: Record<string, number>;
  undated: number;
  tasks: Task[];
  reviewCount: number;
};
type PlacedSlot = Slot & {
  subject: Subject;
  start: number;
  end: number;
  lane: number;
  lanes: number;
};
type Due = { task: Task; day: string; min: number };

const statusWord: Record<string, string> = {
  missed: "missed",
  completed: "done",
};
function dueTime(d: Due) {
  const t = d.task;
  // A window or a date without an announced time has no clock to show on the day.
  const when = dueWindow(t)
    ? "last day of window"
    : t.dueDate && t.type === "test"
      ? "time TBA"
      : t.dueDate
        ? "23:59"
        : clock(d.min);
  return t.timingTentative ? when + " · tentative" : when;
}
function DueItem({
  due,
  onOpen,
  detail,
}: {
  due: Due;
  onOpen: (id: string) => void;
  detail?: boolean;
}) {
  const t = due.task;
  const word = statusWord[t.status];
  const { state } = useQuickComplete();
  if (state(t.id) === "gone") return null;
  return (
    <div className={"due-item " + t.status + " " + state(t.id)}>
      {t.status === "completed" ? (
        <span className="done-mark" aria-hidden="true">
          <Check size={10} strokeWidth={3} />
        </span>
      ) : (
        <DoneButton task={t} compact />
      )}
      <button
        className="due-open"
        onClick={() => onOpen(t.id)}
        title={t.title + " · " + deadline(t).main}
      >
        <span className="due-title">{t.title}</span>
        <span className="due-meta">
          {dueTime(due)}
          {detail &&
            " · " +
              (t.type === "test" ? "Test" : "Assignment") +
              (t.subjectName ? " · " + t.subjectName : "")}
          {word && <strong> · {word}</strong>}
        </span>
      </button>
    </div>
  );
}

function SlotBox({
  slot,
  style,
}: {
  slot: PlacedSlot;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className={"slot-box " + slot.subject.kind}
      style={style}
      title={
        slot.subject.name +
        " · " +
        hhmm(slot.startTime) +
        "–" +
        hhmm(slot.endTime) +
        (slot.location ? " · " + slot.location : "")
      }
    >
      <span className="slot-name">
        {slot.subject.code || slot.subject.name}
      </span>
      <span className="slot-time">
        {kindShort[slot.subject.kind]}
        {slot.location ? " · " + slot.location : ""}
      </span>
    </div>
  );
}

export function WeekSheet({
  subjects,
  onOpen,
  onTasks,
  onAttention,
  onAdd,
  onSubjects,
  mode,
  onMode,
}: {
  subjects: Subject[];
  onOpen: (id: string) => void;
  onTasks: (status: string) => void;
  onAttention: () => void;
  onAdd: () => void;
  onSubjects: () => void;
  mode: "week" | "month";
  onMode: (m: "week" | "month") => void;
}) {
  const now = useNow();
  const today = dayKey(new Date(now));
  const [monday, setMonday] = useState(() => mondayOf(dayKey(new Date())));
  const [selected, setSelected] = useState<string>(today);
  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(monday, i)),
    [monday],
  );
  const client = useQueryClient();

  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: () => api<Overview>("/overview"),
  });
  const week = useQuery({
    queryKey: ["tasks", "week", monday],
    queryFn: async () => {
      let cursor = "",
        items: Task[] = [];
      do {
        const params = new URLSearchParams({
          limit: "100",
          dateFrom: monday + "T00:00:00+05:30",
          dateTo: addDays(monday, 7) + "T00:00:00+05:30",
        });
        if (cursor) params.set("cursor", cursor);
        const p = await api<Page<Task>>("/tasks?" + params);
        items = [...items, ...p.items];
        cursor = p.nextCursor || "";
      } while (cursor);
      return items;
    },
  });
  const timetables = useQueries({
    queries: subjects.map((s) => ({
      queryKey: ["timetable", s.id],
      queryFn: () =>
        api<{ slots: Slot[]; revision: number }>(
          "/subjects/" + s.id + "/timetable",
        ),
      staleTime: 300000,
    })),
  });
  useCutoffRefresh(week.data || []);
  // Overview counts change the moment the nearest cutoff passes.
  useEffect(() => {
    const upcoming = (overview.data?.tasks || [])
      .map((t) => (t.dueAt ? new Date(t.dueAt).getTime() : Infinity))
      .filter((t) => t > Date.now());
    const next = Math.min(...upcoming);
    if (!Number.isFinite(next)) return;
    const timer = setTimeout(
      () => {
        client.invalidateQueries({ queryKey: ["overview"] });
        client.invalidateQueries({ queryKey: ["tasks"] });
      },
      Math.min(next - Date.now() + 25, 2147483647),
    );
    return () => clearTimeout(timer);
  }, [overview.data, client]);

  const slotsByDay = useMemo(() => {
    const map: Record<string, PlacedSlot[]> = {};
    days.forEach((date, i) => {
      const list: PlacedSlot[] = [];
      timetables.forEach((q, n) => {
        const subject = subjects[n];
        for (const s of q.data?.slots || []) {
          if (s.weekday !== i + 1 || !s.startTime || !s.endTime) continue;
          if (s.validFrom && s.validFrom.slice(0, 10) > date) continue;
          if (s.validUntil && s.validUntil.slice(0, 10) < date) continue;
          list.push({
            ...s,
            subject,
            start: toMinutes(s.startTime),
            end: toMinutes(s.endTime),
            lane: 0,
            lanes: 1,
          });
        }
      });
      list.sort((a, b) => a.start - b.start || a.end - b.end);
      // Parallel slots share the column side by side.
      const laneEnds: number[] = [];
      for (const s of list) {
        let lane = laneEnds.findIndex((end) => end <= s.start);
        if (lane < 0) lane = laneEnds.length;
        laneEnds[lane] = s.end;
        s.lane = lane;
      }
      list.forEach((s) => (s.lanes = Math.max(1, laneEnds.length)));
      map[date] = list;
    });
    return map;
  }, [days, timetables, subjects]);

  const allSlots = Object.values(slotsByDay).flat();
  const dues: Due[] = useMemo(
    () =>
      (week.data || [])
        .filter((t) => t.dueAt)
        .sort((a, b) => a.dueAt!.localeCompare(b.dueAt!))
        .map((task) => ({
          task,
          day: dayKey(new Date(task.dueAt!)),
          min: minutesOf(task.dueAt!),
        })),
    [week.data],
  );
  const dueOn = (date: string) => dues.filter((d) => d.day === date);
  const startH = Math.max(
    6,
    Math.min(8, ...allSlots.map((s) => Math.floor(s.start / 60))),
  );
  const endH = Math.min(
    21,
    Math.max(17, ...allSlots.map((s) => Math.ceil(s.end / 60))),
  );
  const total = (endH - startH) * HOUR;
  const hours = Array.from({ length: endH - startH }, (_, i) => startH + i);
  const pos = (min: number) =>
    Math.min(Math.max(((min - startH * 60) / 60) * HOUR, 0), total);
  const nowMin = minutesOf(new Date(now).toISOString());
  const showNow =
    days.includes(today) && nowMin >= startH * 60 && nowMin <= endH * 60;

  const o = overview.data;
  const next = [...(o?.tasks || []), ...(week.data || [])]
    .filter(
      (t) => t.dueAt && t.status === "due" && new Date(t.dueAt).getTime() > now,
    )
    .sort((a, b) => a.dueAt!.localeCompare(b.dueAt!))[0];
  const thisWeek = days.includes(today);
  const offset = Math.round(
    (new Date(monday).getTime() - new Date(mondayOf(today)).getTime()) /
      (7 * 864e5),
  );
  const title =
    offset === 0
      ? "This week"
      : offset === 1
        ? "Next week"
        : offset === -1
          ? "Last week"
          : "Week of " + shortDate(monday);
  const selectedDay = days.includes(selected)
    ? selected
    : thisWeek
      ? today
      : monday;
  const noSlots = !timetables.some((q) => q.isPending) && allSlots.length === 0;

  const summary: [string, number, () => void, string][] = [
    ["due", o?.counts.due || 0, () => onTasks("due"), ""],
    ["missed", o?.counts.missed || 0, () => onTasks("missed"), "alert"],
    ["without a date", o?.undated || 0, () => onTasks("undated"), ""],
    ["to review", o?.reviewCount || 0, onAttention, "review"],
  ];
  const switcher = (
    <div className="seg" role="group" aria-label="Sheet view">
      {(["week", "month"] as const).map((m) => (
        <button key={m} aria-pressed={mode === m} onClick={() => onMode(m)}>
          {m === "week" ? "Week" : "Month"}
        </button>
      ))}
    </div>
  );
  const summaryLine = (
    <>
      <ErrorNotice error={overview.error} retry={() => overview.refetch()} />
      <div className="summary" role="group" aria-label="Your work at a glance">
        {overview.isPending ? (
          <span className="text-secondary">Counting your work…</span>
        ) : (
          summary
            .filter(([label, value]) => label === "due" || value > 0)
            .map(([label, value, go, tone]) => (
              <button
                key={label}
                className={"summary-item " + (value > 0 ? tone : "")}
                onClick={go}
              >
                <strong>{value}</strong> {label}
              </button>
            ))
        )}
      </div>
    </>
  );

  return (
    <>
      {next ? (
        <button className="next-band" onClick={() => onOpen(next.id)}>
          <span className="next-label">Next due</span>
          <span className="next-body">
            <span className="next-title">{next.title}</span>
            <span className="next-meta">
              {next.subjectName ? next.subjectName + " · " : ""}
              {formatTime(next.dueAt)}
            </span>
          </span>
          <span className="next-count">
            <small>in</small>
            {countdown(new Date(next.dueAt!).getTime() - now)}
          </span>
        </button>
      ) : (
        <div className="next-band" role="status">
          <span className="next-label">Next due</span>
          <span className="next-body">
            <span className="next-title">
              {overview.isPending || week.isPending
                ? "Loading…"
                : "Nothing due. You’re all caught up."}
            </span>
          </span>
          <span />
        </div>
      )}
      {mode === "month" ? (
        <Calendar onOpen={onOpen} controls={switcher}>
          {summaryLine}
        </Calendar>
      ) : (
        <>
          <div className="week-head">
            <h1>
              {title}
              <span>{rangeLabel(monday)} · times in IST</span>
            </h1>
            <div className="week-controls">
              <div className="seg" role="group" aria-label="Change week">
                <button
                  aria-label="Previous week"
                  onClick={() => setMonday(addDays(monday, -7))}
                >
                  <ChevronLeft size={18} />
                </button>
                <button
                  aria-pressed={thisWeek}
                  onClick={() => {
                    setMonday(mondayOf(today));
                    setSelected(today);
                  }}
                >
                  Today
                </button>
                <button
                  aria-label="Next week"
                  onClick={() => setMonday(addDays(monday, 7))}
                >
                  <ChevronRight size={18} />
                </button>
              </div>
              {switcher}
            </div>
          </div>
          {summaryLine}
          <ErrorNotice error={week.error} retry={() => week.refetch()} />
          <section
            className="sheet"
            aria-label={"Week of " + rangeLabel(monday)}
            style={{ "--hour": HOUR + "px" } as React.CSSProperties}
          >
            <div className="sheet-head">
              <div />
              {days.map((date, i) => (
                <div
                  key={date}
                  className={"day-head" + (date === today ? " today" : "")}
                >
                  <span className="printed">
                    {date === today ? "Today" : dayNames[i]}
                  </span>
                  <strong>{new Date(date + "T00:00:00Z").getUTCDate()}</strong>
                </div>
              ))}
            </div>
            <div className="sheet-due">
              <div className="row-label">
                <span className="printed">Due</span>
              </div>
              {days.map((date) => (
                <div
                  key={date}
                  className={"due-cell" + (date === today ? " today" : "")}
                >
                  {dueOn(date).map((d) => (
                    <DueItem key={d.task.id} due={d} onOpen={onOpen} />
                  ))}
                </div>
              ))}
            </div>
            <div className="sheet-body" key={monday} style={{ height: total }}>
              <div className="sheet-rail" aria-hidden="true">
                {hours.map((h) => {
                  const at = (h - startH) * HOUR;
                  const under =
                    showNow && Math.abs(pos(nowMin) - (at + 11)) < 22;
                  return (
                    <div key={h} className="rail-hour" style={{ top: at }}>
                      <span className="tmark" />
                      {!under && <span>{String(h).padStart(2, "0")}</span>}
                    </div>
                  );
                })}
              </div>
              {days.map((date) => (
                <div
                  key={date}
                  className={"sheet-col" + (date === today ? " today" : "")}
                >
                  {(slotsByDay[date] || []).map((s, n) => (
                    <SlotBox
                      key={(s.id || n) + s.subject.id}
                      slot={s}
                      style={{
                        top: pos(s.start) + 1,
                        height: Math.max(pos(s.end) - pos(s.start) - 2, 22),
                        left: `calc(3px + (100% - 6px) * ${s.lane} / ${s.lanes})`,
                        width: `calc((100% - 6px) / ${s.lanes} - ${s.lanes > 1 ? 2 : 0}px)`,
                      }}
                    />
                  ))}
                </div>
              ))}
              {showNow && (
                <div
                  className="scanline"
                  style={{ "--now": pos(nowMin) + "px" } as React.CSSProperties}
                  aria-hidden="true"
                >
                  <span>{clock(nowMin)}</span>
                </div>
              )}
            </div>
            {noSlots && (
              <p className="sheet-empty-note">
                Your classes will show here.{" "}
                <button onClick={onSubjects}>Add your timetable</button>
              </p>
            )}
          </section>

          <div className="day-strip" role="group" aria-label="Choose a day">
            {days.map((date, i) => {
              const count = dueOn(date).length;
              return (
                <button
                  key={date}
                  className={date === today ? "today" : ""}
                  aria-pressed={selectedDay === date}
                  aria-label={
                    dayNames[i] + " " + shortDate(date) + ", " + count + " due"
                  }
                  onClick={() => setSelected(date)}
                >
                  <span className="printed">{dayNames[i]}</span>
                  <strong>{new Date(date + "T00:00:00Z").getUTCDate()}</strong>
                  <span className="day-ticks" aria-hidden="true">
                    {dueOn(date)
                      .slice(0, 3)
                      .map((d) => (
                        <i key={d.task.id} className={d.task.status} />
                      ))}
                  </span>
                </button>
              );
            })}
          </div>
          <div className="agenda">
            <h2 className="agenda-head">Due</h2>
            {dueOn(selectedDay).length ? (
              dueOn(selectedDay).map((d) => (
                <DueItem key={d.task.id} due={d} onOpen={onOpen} detail />
              ))
            ) : (
              <p className="agenda-empty">
                {week.isPending ? "Loading…" : "Nothing due this day."}
              </p>
            )}
            <h2 className="agenda-head">Classes</h2>
            {(slotsByDay[selectedDay] || []).length ? (
              <ol className="agenda-classes">
                {(slotsByDay[selectedDay] || []).map((s, n) => (
                  <li key={(s.id || n) + s.subject.id}>
                    <span className="agenda-time">
                      {hhmm(s.startTime)}
                      <small>{hhmm(s.endTime)}</small>
                    </span>
                    <SlotBox slot={s} />
                  </li>
                ))}
              </ol>
            ) : (
              <p className="agenda-empty">
                {noSlots ? (
                  <button onClick={onSubjects}>Add your timetable</button>
                ) : (
                  "No classes this day."
                )}
              </p>
            )}
          </div>
          {!dues.length && !week.isPending && (
            <div className="week-empty">
              <p>Nothing due this week.</p>
              <Button variant="outline" size="sm" onClick={onAdd}>
                <Plus size={15} />
                Add a task
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );
}
