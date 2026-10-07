"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  LayoutDashboard,
  ListTodo,
  CalendarDays,
  BookOpen,
  Settings,
  Plus,
  ArrowUpRight,
  LogOut,
  Menu,
  ArrowRight,
  Clock3,
  Plug,
} from "lucide-react";
import { api, formatTime } from "@/lib/api";
import { useCutoffRefresh } from "@/lib/use-cutoff-refresh";
import type { Profile, Page, Task, Subject } from "@/lib/types";
import { Button } from "./ui/button";
import { ErrorNotice } from "./ui/field";
import { ProfileForm } from "./profile-form";
import { TaskEditor } from "./task-editor";
import { TaskDetail } from "./task-detail";
import { Subjects } from "./subjects";
import { Calendar } from "./calendar";
import { Connections, SyncOverview } from "./connections";
import { SyncProvider } from "@/lib/sync";
const views = [
  ["dashboard", "Overview", LayoutDashboard],
  ["tasks", "Tasks", ListTodo],
  ["calendar", "Calendar", CalendarDays],
  ["subjects", "Subjects", BookOpen],
  ["connections", "Sources", Plug],
  ["settings", "Settings", Settings],
] as const;
type View = (typeof views)[number][0];
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
function TaskRows({
  items,
  onOpen,
}: {
  items: Task[];
  onOpen: (id: string) => void;
}) {
  return (
    <div className="task-list">
      {items.map((t) => (
        <button className="task-row" key={t.id} onClick={() => onOpen(t.id)}>
          <span className={"task-icon " + t.type}>
            {t.type === "test" ? <Clock3 size={17} /> : <ListTodo size={17} />}
          </span>
          <span className="task-main">
            <strong>{t.title}</strong>
            <span>
              {t.subjectName || "No subject"}
              {t.subjectKind ? " · " + t.subjectKind : ""}
            </span>
          </span>
          <span className="task-deadline">
            {formatTime(t.dueAt)}
            {t.dueDate && t.type === "assignment" && (
              <small>Date only · 23:59 IST</small>
            )}
          </span>
          <span className={"priority " + t.priority}>{t.priority}</span>
          <span className={"status " + t.status}>{t.status}</span>
          <ArrowUpRight size={16} className="text-secondary" />
        </button>
      ))}
    </div>
  );
}
function Dashboard({
  onOpen,
  onTasks,
  onAdd,
  onSources,
}: {
  onOpen: (id: string) => void;
  onTasks: (status: string) => void;
  onAdd: () => void;
  onSources: () => void;
}) {
  const query = useQuery({
    queryKey: ["overview"],
    queryFn: () =>
      api<{ counts: Record<string, number>; undated: number; tasks: Task[] }>(
        "/overview",
      ),
  });
  const client = useQueryClient();
  useEffect(() => {
    const upcoming =
      query.data?.tasks
        .map((t) => (t.dueAt ? new Date(t.dueAt).getTime() : Infinity))
        .filter((t) => t > Date.now()) || [];
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
  }, [query.data, client]);
  return (
    <>
      <div className="intro">
        <p className="eyebrow">A LITTLE CLARITY FOR YOUR DAY</p>
        <h1>Your work, in view.</h1>
        <p className="text-secondary">
          Keep the next deadline close and the rest in perspective.
        </p>
      </div>
      <ErrorNotice error={query.error} retry={() => query.refetch()} />
      <div className="stats">
        {(["due", "overdue", "missed", "completed"] as const).map((s, i) => (
          <button key={s} onClick={() => onTasks(s)} className="stat">
            <span>
              {["Due", "Overdue assignments", "Missed tests", "Completed"][i]}
            </span>
            <strong>
              {query.isPending ? "—" : query.data?.counts[s] || 0}
            </strong>
            <ArrowUpRight size={16} />
          </button>
        ))}
      </div>
      <SyncOverview onOpen={onSources} />
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>On your radar</h2>
            <p className="text-secondary text-sm">
              Outstanding work, ordered by cutoff.
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => onTasks("")}>
            All tasks
            <ArrowRight size={16} />
          </Button>
        </div>
        {query.isPending ? (
          <p className="empty-small" role="status">
            Loading your tasks…
          </p>
        ) : query.data?.tasks.length ? (
          <TaskRows items={query.data.tasks} onOpen={onOpen} />
        ) : (
          <div className="empty">
            <BookOpen size={28} />
            <h3>A fresh start</h3>
            <p>Add your first assignment or test to bring it into view.</p>
            <Button variant="outline" onClick={onAdd}>
              <Plus size={15} />
              Add a task
            </Button>
          </div>
        )}
      </section>
      <button className="undated-banner" onClick={() => onTasks("undated")}>
        <Clock3 size={20} />
        <span>
          <strong>{query.data?.undated || 0} undated tasks</strong>
          <small>Keep work visible even before the exact time is known.</small>
        </span>
        <ArrowRight size={18} />
      </button>
    </>
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
  const [source, setSource] = useState("");
  const [batchFilter, setBatchFilter] = useState("");
  const [type, setType] = useState("");
  const [subject, setSubject] = useState("");
  const [kind, setKind] = useState("");
  const [priority, setPriority] = useState("");
  const [date, setDate] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(search), 250);
    return () => clearTimeout(timer);
  }, [search]);
  const params = new URLSearchParams();
  if (debounced) params.set("q", debounced);
  if (undated) params.set("undated", "true");
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
  useCutoffRefresh(query.data?.pages.flatMap((p) => p.items) || []);
  return (
    <>
      <div className="section-bar">
        <div>
          <h2>All tasks</h2>
          <p className="text-secondary">
            Your assignments and tests. Batch {batch || "not set"} · manual
            source.
          </p>
        </div>
      </div>
      <div className="filters">
        <label className="search">
          <span className="sr-only">Search tasks</span>
          <input
            placeholder="Search tasks or notes"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label>
          <span className="sr-only">Status filter</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {["due", "completed", "overdue", "missed"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="sr-only">Type filter</span>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All types</option>
            <option>assignment</option>
            <option>test</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Subject filter</span>
          <select value={subject} onChange={(e) => setSubject(e.target.value)}>
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
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All subject kinds</option>
            {["theory", "lab", "tutorial"].map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="sr-only">Priority filter</span>
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
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label>
          <span className="sr-only">Source filter</span>
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">All sources</option>
            <option value="manual">Student entered</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Batch filter</span>
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
          No precise cutoff
        </label>
        <Button
          variant="ghost"
          onClick={() => {
            setSearch("");
            setStatus("");
            setUndated(false);
            setSource("");
            setBatchFilter("");
            setType("");
            setSubject("");
            setKind("");
            setPriority("");
            setDate("");
          }}
        >
          Reset filters
        </Button>
      </div>
      <ErrorNotice error={query.error} retry={() => query.refetch()} />
      <div className="panel">
        {query.isPending ? (
          <p className="empty-small" role="status">
            Loading tasks…
          </p>
        ) : query.data?.pages.some((p) => p.items.length) ? (
          <TaskRows
            items={query.data.pages.flatMap((p) => p.items)}
            onOpen={onOpen}
          />
        ) : (
          <div className="empty">
            <ListTodo size={28} />
            <h3>No tasks in this view</h3>
            <p>Try another filter, or add something you need to do.</p>
          </div>
        )}
      </div>
      {query.hasNextPage && (
        <Button
          className="mt-4"
          variant="outline"
          disabled={query.isFetchingNextPage}
          onClick={() => query.fetchNextPage()}
        >
          Load more tasks
        </Button>
      )}
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
  const subjects = useQuery({
    queryKey: ["subjects"],
    queryFn: allSubjects,
    enabled: Boolean(profile.data?.onboardingComplete),
  });
  const [view, setView] = useState<View>("dashboard");
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
    const apply = () =>
      document.documentElement.classList.toggle(
        "dark",
        theme === "dark" || (theme === "system" && media.matches),
      );
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
  useEffect(() => {
    const restore = () => {
      const params = new URLSearchParams(window.location.search);
      const v = params.get("view");
      if (views.some(([k]) => k === v)) setView(v as View);
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
  function navigate(v: View) {
    setView(v);
    setMenu(false);
    window.history.pushState(null, "", "/?view=" + v);
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
        <span className="brand">DueCare</span>
        {profile.isPending ? (
          <p role="status">Opening your workspace…</p>
        ) : (
          <ErrorNotice error={profile.error} retry={() => profile.refetch()} />
        )}
      </main>
    );
  return (
    <SyncProvider enabled={p.onboardingComplete}>
      <div className="app-shell">
        <aside className={"sidebar " + (menu ? "open" : "")}>
          <Link href="/" className="brand">
            DueCare<span className="brand-mark">d.</span>
          </Link>
          <p className="sidebar-caption">Your academic workspace</p>
          <nav aria-label="Main navigation">
            {views.map(([key, label, Icon]) => (
              <button
                key={key}
                onClick={() => navigate(key)}
                className={view === key ? "active" : ""}
                aria-current={view === key ? "page" : undefined}
              >
                <Icon size={19} />
                {label}
              </button>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="profile-mini">
              <span className="avatar">
                {p.identity.name?.slice(0, 1) || "S"}
              </span>
              <div>
                <strong>{p.identity.name || "Student"}</strong>
                <span>
                  {p.classYear || "Complete your profile"}
                  {p.division ? " · " + p.division : ""}
                </span>
              </div>
            </div>
            <Button variant="ghost" disabled={signingOut} onClick={logout}>
              <LogOut size={16} />
              Sign out
            </Button>
            <ErrorNotice error={logoutError} />
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
          <header className="topbar">
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="icon"
                className="mobile-menu"
                aria-label="Open navigation"
                onClick={() => setMenu(!menu)}
              >
                <Menu size={20} />
              </Button>
              <span>{views.find(([k]) => k === view)?.[1]}</span>
            </div>
            <div className="flex items-center gap-4">
              <span className="term-label">
                {p.currentSemester
                  ? "Semester " + p.currentSemester
                  : "Let’s get started"}
              </span>
              {p.onboardingComplete && (
                <Button onClick={() => setEditor(null)}>
                  <Plus size={17} />
                  Add task
                </Button>
              )}
            </div>
          </header>
          <main id="main" className="main-content">
            {!p.onboardingComplete ? (
              <ProfileForm profile={p} />
            ) : (
              <>
                <ErrorNotice
                  error={subjects.error}
                  retry={() => subjects.refetch()}
                />
                {view === "dashboard" && (
                  <Dashboard
                    onSources={() => navigate("connections")}
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
                {view === "calendar" && <Calendar onOpen={setDetail} />}
                {view === "subjects" && (
                  <Subjects
                    subjects={subjects.data || []}
                    batch={p.generalBatch}
                  />
                )}
                {view === "connections" && (
                  <Connections
                    notice={notice}
                    onDismiss={() => setNotice({})}
                  />
                )}
                {view === "settings" && (
                  <>
                    <ProfileForm key={p.revision} profile={p} />
                    <section className="panel settings-link">
                      <div>
                        <h2>Sources and senders</h2>
                        <p className="text-secondary text-sm">
                          Manage Gmail and Classroom connections, Classroom
                          course links, and included or blocked senders.
                        </p>
                      </div>
                      <Button
                        variant="outline"
                        onClick={() => navigate("connections")}
                      >
                        <Plug size={16} />
                        Open sources
                      </Button>
                    </section>
                  </>
                )}
              </>
            )}
          </main>
          <footer className="app-footer">
            Your pace. Your progress.<span>All times in IST</span>
          </footer>
        </div>
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
