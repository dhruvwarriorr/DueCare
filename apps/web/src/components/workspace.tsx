"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Plus, LogOut, Bell, Search, ListTodo } from "lucide-react";
import { api, classroomNote, deadline } from "@/lib/api";
import { useCutoffRefresh } from "@/lib/use-cutoff-refresh";
import type { Profile, Page, Task, Subject } from "@/lib/types";
import { Button } from "./ui/button";
import { Logo } from "./ui/logo";
import { Dialog } from "./ui/dialog";
import { ErrorNotice } from "./ui/field";
import { ProfileForm } from "./profile-form";
import { KtPreference } from "./kt-preference";
import { TaskEditor } from "./task-editor";
import { TaskDetail } from "./task-detail";
import {
  DoneButton,
  QuickCompleteProvider,
  useQuickComplete,
} from "@/lib/quick-complete";
import { Subjects } from "./subjects";
import { Connections } from "./connections";
import { SyncProvider } from "@/lib/sync";
import { NeedsAttention } from "./needs-attention";
import { Rules } from "./rules";
import { ActivityInbox } from "./activity";
import { PrivacyControls } from "./privacy";
import { WeekSheet } from "./week-sheet";

const views = [
  "week",
  "tasks",
  "attention",
  "subjects",
  "settings",
  "connections",
  "rules",
] as const;
type View = (typeof views)[number];
const destinations: [View, string][] = [
  ["week", "Week"],
  ["tasks", "Tasks"],
  ["attention", "Review"],
  ["subjects", "Subjects"],
  ["settings", "Settings"],
];
const settingsPages: [View, string][] = [
  ["settings", "Profile & privacy"],
  ["connections", "Sources"],
  ["rules", "Rules"],
];
const isSettings = (v: View) =>
  v === "settings" || v === "connections" || v === "rules";

async function allSubjects() {
  let cursor = "",
    items: Subject[] = [];
  do {
    const p = await api<Page<Subject>>(
      "/subjects?limit=100" +
        (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
    );
    items = [...items, ...p.items];
    cursor = p.nextCursor || "";
  } while (cursor);
  return items;
}
function Brand() {
  return (
    <Link href="/" className="brand" aria-label="DueCare, this week">
      <Logo />
    </Link>
  );
}
const sourceName: Record<string, string> = {
  gmail: "Gmail",
  classroom: "Classroom",
};
function TaskRows({
  items,
  onOpen,
  selected,
  onToggle,
}: {
  items: Task[];
  onOpen: (id: string) => void;
  /** When set, rows are chosen for a bulk action instead of opened. */
  selected?: Set<string>;
  onToggle?: (id: string) => void;
}) {
  const { state } = useQuickComplete();
  return (
    <div className="task-list">
      {items
        .filter((t) => state(t.id) !== "gone")
        .map((t) => (
          <div
            key={t.id}
            className={
              "task-item " +
              state(t.id) +
              (selected?.has(t.id) ? " selected" : "")
            }
          >
            {selected ? (
              <input
                type="checkbox"
                className="task-select"
                aria-label={"Select " + t.title}
                checked={selected.has(t.id)}
                onChange={() => onToggle?.(t.id)}
              />
            ) : (
              <DoneButton task={t} />
            )}
            <button
              className={"task-row " + t.status}
              onClick={() => (selected ? onToggle?.(t.id) : onOpen(t.id))}
            >
              <span className="task-main">
                <strong>
                  {t.title}
                  {t.status === "due" &&
                    (t.priority === "critical" || t.priority === "high") && (
                      <span className="priority-flag">{t.priority}</span>
                    )}
                </strong>
                <span>
                  {t.type === "test" ? "Test" : "Assignment"}
                  {" · " + (t.subjectName || "No subject")}
                  {sourceName[t.source]
                    ? " · from " + sourceName[t.source]
                    : ""}
                  {classroomNote(t) && (
                    <span className="classroom-note">
                      {" · " + classroomNote(t)}
                    </span>
                  )}
                </span>
              </span>
              <span
                className="task-deadline"
                title={t.timingTentative?.question || undefined}
              >
                {deadline(t).main}
                {deadline(t).note && <small>{deadline(t).note}</small>}
              </span>
              <span className={"status " + t.status}>
                {t.status === "completed" ? "done" : t.status}
              </span>
            </button>
          </div>
        ))}
    </div>
  );
}
const statusOptions = [
  ["", "All"],
  ["due", "Due"],
  ["missed", "Missed"],
  ["completed", "Completed"],
] as const;
/** Actions on every selected task at once, applied together by the server. */
function BulkBar({
  selected,
  visible,
  subjects,
  onSelect,
  onDone,
}: {
  selected: Set<string>;
  visible: Task[];
  subjects: Subject[];
  onSelect: (s: Set<string>) => void;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const [subject, setSubject] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const bulk = useMutation({
    mutationFn: (body: { action: string; subjectId?: string }) =>
      api("/tasks/bulk", "POST", { taskIds: [...selected], ...body }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["tasks"] });
      await client.invalidateQueries({ queryKey: ["overview"] });
      setConfirmDelete(false);
      onDone();
    },
  });
  const count = selected.size;
  const none = count === 0 || bulk.isPending;
  return (
    <div className="bulk-bar" role="toolbar" aria-label="Selected tasks">
      <strong>{count} selected</strong>
      <button
        type="button"
        className="link-button"
        onClick={() =>
          onSelect(
            count === visible.length
              ? new Set()
              : new Set(visible.map((t) => t.id)),
          )
        }
      >
        {count === visible.length && count > 0 ? "Clear" : "Select all shown"}
      </button>
      <div className="bulk-actions">
        <Button
          disabled={none}
          onClick={() => bulk.mutate({ action: "complete" })}
        >
          Mark done
        </Button>
        <Button
          variant="outline"
          disabled={none}
          onClick={() => bulk.mutate({ action: "reopen" })}
        >
          Reopen
        </Button>
        <label className="bulk-subject">
          <span className="sr-only">Move to subject</span>
          <select value={subject} onChange={(e) => setSubject(e.target.value)}>
            <option value="">Move to subject…</option>
            {subjects.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} · {s.kind}
              </option>
            ))}
          </select>
        </label>
        <Button
          variant="outline"
          disabled={none || !subject}
          onClick={() => bulk.mutate({ action: "subject", subjectId: subject })}
        >
          Move
        </Button>
        {confirmDelete ? (
          <Button
            variant="destructive"
            disabled={none}
            onClick={() => bulk.mutate({ action: "delete" })}
          >
            Delete {count} {count === 1 ? "task" : "tasks"}?
          </Button>
        ) : (
          <Button
            variant="ghost"
            disabled={none}
            onClick={() => setConfirmDelete(true)}
          >
            Delete
          </Button>
        )}
      </div>
      <ErrorNotice error={bulk.error} />
    </div>
  );
}
function TaskList({
  subjects,
  onOpen,
  initialStatus,
  batch,
}: {
  subjects: Subject[];
  onOpen: (id: string) => void;
  initialStatus: string;
  batch?: string;
}) {
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [status, setStatus] = useState(
    initialStatus === "undated" ? "" : initialStatus,
  );
  const [undated, setUndated] = useState(initialStatus === "undated");
  const [showHidden, setShowHidden] = useState(false);
  const [source, setSource] = useState("");
  const [batchFilter, setBatchFilter] = useState("");
  const [type, setType] = useState("");
  const [subject, setSubject] = useState("");
  const [kind, setKind] = useState("");
  const [priority, setPriority] = useState("");
  const [date, setDate] = useState("");
  const [sort, setSort] = useState<"date" | "priority">(() => {
    try {
      return localStorage.getItem("duecare.taskSort") === "priority"
        ? "priority"
        : "date";
    } catch {
      return "date";
    }
  });
  function chooseSort(value: "date" | "priority") {
    setSort(value);
    try {
      localStorage.setItem("duecare.taskSort", value);
    } catch {}
  }
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(search), 250);
    return () => clearTimeout(timer);
  }, [search]);
  const params = new URLSearchParams({ sort });
  if (debounced) params.set("q", debounced);
  if (undated) params.set("undated", "true");
  if (showHidden) params.set("hidden", "true");
  if (status) params.set("status", status);
  if (source) params.set("source", source);
  if (batchFilter) params.set("batch", batchFilter);
  if (type) params.set("type", type);
  if (subject) params.set("subjectId", subject);
  if (kind) params.set("subjectKind", kind);
  if (priority) params.set("priority", priority);
  if (date) {
    params.set("dateFrom", date + "T00:00:00+05:30");
    const next = new Date(date + "T00:00:00Z");
    next.setUTCDate(next.getUTCDate() + 1);
    params.set("dateTo", next.toISOString().slice(0, 10) + "T00:00:00+05:30");
  }
  const extra = [
    source,
    batchFilter,
    type,
    subject,
    kind,
    priority,
    date,
  ].filter(Boolean).length;
  const query = useInfiniteQuery({
    queryKey: ["tasks", params.toString()],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Page<Task>>(
        "/tasks?" +
          params +
          (pageParam ? "&cursor=" + encodeURIComponent(pageParam) : ""),
      ),
    getNextPageParam: (p) => p.nextCursor || undefined,
    refetchInterval: 60000,
  });
  const items = query.data?.pages.flatMap((p) => p.items) || [];
  const [selected, setSelected] = useState<Set<string> | null>(null);
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  useCutoffRefresh(items);
  function reset() {
    setSearch("");
    setStatus("");
    setUndated(false);
    setShowHidden(false);
    setSource("");
    setBatchFilter("");
    setType("");
    setSubject("");
    setKind("");
    setPriority("");
    setDate("");
  }
  return (
    <>
      <div className="section-bar">
        <div>
          <h2>All tasks</h2>
          <p className="text-secondary">
            {sort === "date"
              ? "Upcoming work soonest first, then missed, undated and completed."
              : "Upcoming work by priority, then missed and completed."}
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => setSelected(selected ? null : new Set())}
        >
          {selected ? "Done selecting" : "Select"}
        </Button>
        <label className="sort-select">
          <span>Sort by</span>
          <select
            value={sort}
            onChange={(e) => chooseSort(e.target.value as "date" | "priority")}
          >
            <option value="date">Due date</option>
            <option value="priority">Priority</option>
          </select>
        </label>
      </div>
      <div className="filters">
        <div className="filter-main">
          <label className="search">
            <span className="sr-only">Search tasks</span>
            <Search size={17} aria-hidden="true" />
            <input
              type="search"
              placeholder="Search tasks or notes"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <fieldset className="bubble-row">
            <legend>Status filter</legend>
            {statusOptions.map(([value, label]) => (
              <label className="bubble-opt" key={label}>
                <input
                  type="radio"
                  name="task-status"
                  value={value}
                  checked={status === value}
                  onChange={() => setStatus(value)}
                />
                {label}
              </label>
            ))}
          </fieldset>
        </div>
        <details className="more-filters" open={extra > 0 || undefined}>
          <summary>
            More filters
            {extra > 0 && <span className="filter-count">{extra}</span>}
          </summary>
          <div className="filter-grid">
            <label>
              <span className="sr-only">Type filter</span>
              <span aria-hidden="true">Type</span>
              <select value={type} onChange={(e) => setType(e.target.value)}>
                <option value="">All types</option>
                <option>assignment</option>
                <option>test</option>
              </select>
            </label>
            <label>
              <span className="sr-only">Subject filter</span>
              <span aria-hidden="true">Subject</span>
              <select
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
              >
                <option value="">All subjects</option>
                {subjects.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} · {s.kind}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="sr-only">Subject kind filter</span>
              <span aria-hidden="true">Kind</span>
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="">All subject kinds</option>
                {["theory", "lab", "tutorial"].map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
            </label>
            <label>
              <span className="sr-only">Priority filter</span>
              <span aria-hidden="true">Priority</span>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
              >
                <option value="">All priorities</option>
                {["critical", "high", "medium", "low"].map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
            </label>
            <label>
              <span className="sr-only">Cutoff date filter</span>
              <span aria-hidden="true">Cutoff date</span>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </label>
            <label>
              <span className="sr-only">Source filter</span>
              <span aria-hidden="true">Source</span>
              <select
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="">All sources</option>
                <option value="manual">Student entered</option>
                <option value="gmail">Gmail</option>
                <option value="classroom">Classroom</option>
              </select>
            </label>
            <label>
              <span className="sr-only">Batch filter</span>
              <span aria-hidden="true">Batch</span>
              <select
                value={batchFilter}
                onChange={(e) => setBatchFilter(e.target.value)}
              >
                <option value="">All applicable batches</option>
                {batch && <option value={batch}>Batch {batch}</option>}
              </select>
            </label>
            <label className="undated-filter">
              <input
                type="checkbox"
                checked={undated}
                onChange={(e) => setUndated(e.target.checked)}
              />{" "}
              No due date yet
            </label>
            <label className="undated-filter">
              <input
                type="checkbox"
                checked={showHidden}
                onChange={(e) => setShowHidden(e.target.checked)}
              />{" "}
              Only work hidden by rules
            </label>
            <Button variant="ghost" onClick={reset}>
              Reset filters
            </Button>
          </div>
        </details>
      </div>
      <ErrorNotice error={query.error} retry={() => query.refetch()} />
      <div className="panel">
        {query.isPending ? (
          <p className="empty-small" role="status">
            Loading tasks…
          </p>
        ) : items.length ? (
          <>
            {selected && (
              <BulkBar
                selected={selected}
                visible={items}
                subjects={subjects}
                onSelect={setSelected}
                onDone={() => setSelected(new Set())}
              />
            )}
            <TaskRows
              items={items}
              onOpen={onOpen}
              selected={selected ?? undefined}
              onToggle={toggle}
            />
          </>
        ) : (
          <div className="empty">
            <ListTodo size={28} />
            <h3>No tasks in this view</h3>
            <p>Try another filter, or add something you need to do.</p>
          </div>
        )}
      </div>
      <div className="list-foot">
        <span>
          {items.length
            ? items.length + (query.hasNextPage ? "+ " : " ") + "shown"
            : ""}
        </span>
        {query.hasNextPage && (
          <Button
            variant="outline"
            disabled={query.isFetchingNextPage}
            onClick={() => query.fetchNextPage()}
          >
            Load more tasks
          </Button>
        )}
      </div>
    </>
  );
}
function App() {
  const client = useQueryClient();
  const profile = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Profile>("/me"),
    retry: false,
  });
  const ready = Boolean(profile.data?.onboardingComplete);
  const subjects = useQuery({
    queryKey: ["subjects"],
    queryFn: allSubjects,
    enabled: ready,
  });
  const [view, setView] = useState<View>("week");
  const [sheetMode, setSheetMode] = useState<"week" | "month">("week");
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: () => api<{ reviewCount: number }>("/overview"),
    enabled: ready,
  });
  const reviewCount = overview.data?.reviewCount || 0;
  const activity = useQuery({
    queryKey: ["activity", "count"],
    queryFn: () => api<{ unreadCount: number }>("/activity?limit=1"),
    enabled: ready,
    refetchInterval: 30000,
  });
  const unread = activity.data?.unreadCount || 0;
  const [tray, setTray] = useState(false);
  const [account, setAccount] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!account) return;
    const close = (e: Event) => {
      if (
        e instanceof KeyboardEvent
          ? e.key === "Escape"
          : !accountRef.current?.contains(e.target as Node)
      )
        setAccount(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, [account]);
  const [reviewTarget, setReviewTarget] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const [taskStatus, setTaskStatus] = useState("");
  const [editor, setEditor] = useState<Task | null | undefined>(undefined);
  const [detail, setDetail] = useState<string | null>(null);
  const [logoutError, setLogoutError] = useState<Error | null>(null);
  const [notice, setNotice] = useState<{ connected?: string; error?: string }>(
    {},
  );
  const theme = profile.data?.theme || "system";
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const root = document.documentElement.classList;
      root.toggle(
        "dark",
        theme === "dark" || (theme === "system" && media.matches),
      );
      root.toggle("light", theme === "light");
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
  useEffect(() => {
    const restore = () => {
      const params = new URLSearchParams(window.location.search);
      const v = params.get("view");
      // Earlier addresses keep working after the navigation was regrouped.
      if (v === "dashboard") setView("week");
      else if (v === "calendar") {
        setView("week");
        setSheetMode("month");
      } else if (v === "activity") {
        setView("week");
        setTray(true);
      } else if (views.some((k) => k === v)) setView(v as View);
      // Source authorization returns here; keep the notice, then drop it from the address bar.
      const connected = params.get("connected") || undefined;
      const error = params.get("connectionError") || undefined;
      if (connected || error) {
        setNotice({ connected, error });
        window.history.replaceState(null, "", "/?view=" + (v || "connections"));
      }
    };
    restore();
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  useEffect(() => {
    if (!menu) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setMenu(false);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menu]);
  function navigate(v: View) {
    setView(v);
    setMenu(false);
    window.history.pushState(null, "", "/?view=" + v);
    window.scrollTo({ top: 0 });
  }
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);
  async function logout() {
    setSigningOut(true);
    setLogoutError(null);
    try {
      await api("/auth/logout", "POST");
      client.clear();
      router.replace("/sign-in");
      router.refresh();
    } catch (e) {
      setLogoutError(e as Error);
      setSigningOut(false);
    }
  }
  const p = profile.data;
  if (!p)
    return (
      <main id="main" className="app-loading">
        <Brand />
        {profile.isPending ? (
          <>
            <span className="load-rail" aria-hidden="true">
              <span className="tmark" />
              <span className="tmark" />
              <span className="tmark" />
              <span className="tmark" />
            </span>
            <p role="status">Opening your workspace…</p>
          </>
        ) : (
          <ErrorNotice error={profile.error} retry={() => profile.refetch()} />
        )}
      </main>
    );
  const navItem = ([key, label]: [View, string]) => {
    const active = key === "settings" ? isSettings(view) : view === key;
    return (
      <button
        key={key}
        onClick={() => navigate(key)}
        className={"nav-item" + (active ? " active" : "")}
        aria-current={active ? "page" : undefined}
      >
        {label}
        {key === "attention" && reviewCount > 0 && (
          <span className="nav-badge" aria-label={reviewCount + " open"}>
            {reviewCount}
          </span>
        )}
      </button>
    );
  };
  const academic = [
    p.classYear,
    p.branchCode,
    p.division && "Div " + p.division,
    p.generalBatch && "Batch " + p.generalBatch,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <SyncProvider enabled={ready}>
      <QuickCompleteProvider>
        <div className="app-shell">
          <header className="masthead">
            <div className="masthead-brand">
              <Brand />
            </div>
            {ready ? (
              <nav aria-label="Main navigation" className="topnav">
                {destinations.map(navItem)}
              </nav>
            ) : (
              <span />
            )}
            <div className="masthead-actions">
              {ready && (
                <>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="tray-button"
                    aria-label={
                      "Activity" + (unread ? ", " + unread + " unread" : "")
                    }
                    onClick={() => setTray(true)}
                  >
                    <Bell size={20} />
                    {unread > 0 && (
                      <span className="tray-count" aria-hidden="true">
                        {unread > 99 ? "99+" : unread}
                      </span>
                    )}
                  </Button>
                  <Button className="add-task" onClick={() => setEditor(null)}>
                    <Plus size={18} />
                    Add task
                  </Button>
                </>
              )}
              <div className="account" ref={accountRef}>
                <button
                  className="avatar"
                  aria-label="Account"
                  aria-expanded={account}
                  onClick={() => setAccount(!account)}
                >
                  {p.identity.name?.slice(0, 1) || "S"}
                </button>
                {account && (
                  <div className="account-menu">
                    <strong>{p.identity.name || "Student"}</strong>
                    <span>{p.identity.email}</span>
                    {academic && <span>{academic}</span>}
                    <span>All times are in IST</span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={signingOut}
                      onClick={logout}
                    >
                      <LogOut size={15} />
                      Sign out
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </header>
          <aside
            className={"sidebar " + (menu ? "open" : "")}
            aria-label="Navigation"
          >
            <Brand />
            {ready && (
              <nav aria-label="Main navigation" className="nav-group">
                {destinations.map(navItem)}
              </nav>
            )}
            <div className="sidebar-bottom">
              <div className="profile-mini">
                <span className="avatar">
                  {p.identity.name?.slice(0, 1) || "S"}
                </span>
                <div>
                  <strong>{p.identity.name || "Student"}</strong>
                  <span>{p.identity.email}</span>
                </div>
              </div>
              <span className="ist-note">All times in IST</span>
              <Button variant="ghost" disabled={signingOut} onClick={logout}>
                <LogOut size={16} />
                Sign out
              </Button>
            </div>
          </aside>
          {menu && (
            <button
              aria-label="Close navigation"
              className="nav-overlay"
              onClick={() => setMenu(false)}
            />
          )}
          <div className="main-wrap">
            <main id="main" className="main-content">
              <ErrorNotice error={logoutError} />
              {!ready ? (
                <div className="page-pad">
                  <div className="intro">
                    <h1>Fill in your answer sheet</h1>
                    <p className="text-secondary">
                      Six details tell DueCare which notices and classes apply
                      to you.
                    </p>
                  </div>
                  <ProfileForm profile={p} />
                  <PrivacyControls />
                </div>
              ) : (
                <>
                  <ErrorNotice
                    error={subjects.error}
                    retry={() => subjects.refetch()}
                  />
                  {view === "week" && (
                    <WeekSheet
                      subjects={subjects.data || []}
                      mode={sheetMode}
                      onMode={(m) => {
                        setSheetMode(m);
                        window.history.replaceState(
                          null,
                          "",
                          "/?view=" + (m === "month" ? "calendar" : "week"),
                        );
                      }}
                      onSubjects={() => navigate("subjects")}
                      onAttention={() => navigate("attention")}
                      onAdd={() => setEditor(null)}
                      onOpen={setDetail}
                      onTasks={(s) => {
                        setTaskStatus(s);
                        navigate("tasks");
                      }}
                    />
                  )}
                  {view === "tasks" && (
                    <TaskList
                      key={taskStatus}
                      initialStatus={taskStatus}
                      subjects={subjects.data || []}
                      batch={p.generalBatch}
                      onOpen={setDetail}
                    />
                  )}
                  {view === "subjects" && (
                    <Subjects
                      subjects={subjects.data || []}
                      batch={p.generalBatch}
                    />
                  )}
                  {view === "attention" && (
                    <NeedsAttention
                      subjects={subjects.data || []}
                      targetId={reviewTarget}
                      onBack={() => setReviewTarget(null)}
                    />
                  )}
                  {isSettings(view) && (
                    <div
                      className="settings-tabs"
                      role="tablist"
                      aria-label="Settings sections"
                    >
                      {settingsPages.map(([key, label]) => (
                        <button
                          key={key}
                          role="tab"
                          aria-selected={view === key}
                          onClick={() => navigate(key)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  )}
                  {view === "rules" && <Rules subjects={subjects.data || []} />}
                  {view === "connections" && (
                    <Connections
                      notice={notice}
                      onDismiss={() => setNotice({})}
                    />
                  )}
                  {view === "settings" && (
                    <>
                      <div className="section-bar">
                        <div>
                          <h2>Profile &amp; privacy</h2>
                          <p className="text-secondary">
                            Your academic details, notice preferences, and what
                            DueCare keeps.
                          </p>
                        </div>
                      </div>
                      <ProfileForm key={p.revision} profile={p} />
                      <KtPreference profile={p} />
                      <PrivacyControls />
                    </>
                  )}
                </>
              )}
            </main>
          </div>
          {ready && (
            <nav
              className="bottom-bar"
              aria-label="Quick navigation"
              aria-hidden={menu || undefined}
              inert={menu || undefined}
            >
              {(
                [
                  ["week", "Week"],
                  ["tasks", "Tasks"],
                ] as [View, string][]
              ).map(([key, label]) => (
                <button
                  key={key}
                  className={view === key ? "active" : ""}
                  onClick={() => navigate(key)}
                >
                  {label}
                </button>
              ))}
              <button
                className="add"
                aria-label="Add task"
                onClick={() => setEditor(null)}
              >
                <Plus size={18} aria-hidden="true" />
              </button>
              <button
                className={view === "attention" ? "active" : ""}
                onClick={() => navigate("attention")}
              >
                Review
                {reviewCount > 0 && (
                  <span className="bb-count" aria-label={reviewCount + " open"}>
                    {reviewCount}
                  </span>
                )}
              </button>
              <button
                aria-label="Open navigation"
                aria-expanded={menu}
                className={
                  view === "subjects" || isSettings(view) ? "active" : ""
                }
                onClick={() => setMenu(true)}
              >
                More
              </button>
            </nav>
          )}
          {!ready && (
            <nav className="bottom-bar" aria-label="Quick navigation">
              <span />
              <span />
              <span />
              <span />
              <button
                aria-label="Open navigation"
                onClick={() => setMenu(true)}
              >
                More
              </button>
            </nav>
          )}
          <Dialog
            open={tray}
            onOpenChange={setTray}
            side="right"
            title="Activity"
            description="New work, changes, and sync issues."
          >
            <div className="dialog-body">
              <ActivityInbox
                onOpen={(item) => {
                  setTray(false);
                  if (item.targetType === "task") setDetail(item.targetId);
                  else if (item.targetType === "review") {
                    setReviewTarget(item.targetId);
                    navigate("attention");
                  } else navigate("connections");
                }}
              />
            </div>
          </Dialog>
          {editor !== undefined && (
            <TaskEditor
              task={editor || undefined}
              subjects={subjects.data || []}
              onClose={() => setEditor(undefined)}
            />
          )}
          {detail && (
            <TaskDetail
              id={detail}
              onClose={() => setDetail(null)}
              onEdit={(t) => {
                setDetail(null);
                setEditor(t);
              }}
            />
          )}
        </div>
      </QuickCompleteProvider>
    </SyncProvider>
  );
}
export function Workspace() {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 15000, retry: 1, refetchOnWindowFocus: true },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  );
}
