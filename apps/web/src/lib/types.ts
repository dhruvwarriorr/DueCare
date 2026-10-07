export type Profile = {
  id: string;
  revision: number;
  identity: {
    id: string;
    email: string;
    name: string | null;
    photo: string | null;
  };
  onboardingComplete: boolean;
  theme: "system" | "light" | "dark";
  institution?: string;
  programme?: string;
  department?: string;
  admissionYear?: number;
  classYear?: string;
  currentSemester?: number;
  division?: string;
  generalBatch?: string;
  rollNumber?: string;
};
export type Subject = {
  id: string;
  revision: number;
  name: string;
  kind: "theory" | "lab" | "tutorial";
  code?: string | null;
  aliases: string[];
  term?: string | null;
  classCode?: string | null;
  classroomMappings?: ClassroomMapping[];
};
export type Task = {
  id: string;
  revision: number;
  title: string;
  type: "assignment" | "test";
  status: "due" | "completed" | "overdue" | "missed";
  subjectId: string | null;
  subjectName: string | null;
  subjectKind: string | null;
  generalBatch: string | null;
  priority: "low" | "medium" | "high" | "critical";
  priorityOverride: string | null;
  dueAt: string | null;
  dueDate: string | null;
  timingMode: string;
  instructions: string;
  notes: string;
  estimatedEffortMinutes: number | null;
  assessmentLabel: string | null;
  deliverableLabel: string | null;
  location: string | null;
  syllabus: string | null;
  permittedTools: string | null;
  preparationInstructions: string | null;
  submissionOpensAt: string | null;
  availabilityOpensAt: string | null;
  availabilityClosesAt: string | null;
  loginByAt: string | null;
  reportingAt: string | null;
  startsAt: string | null;
  endsAt: string | null;
  dateWindowStart: string | null;
  dateWindowEnd: string | null;
  durationMinutes: number | null;
  completedAt: string | null;
  completionOrigin: string | null;
  createdAt: string;
  source: string;
};
export type Slot = {
  id?: string;
  weekday: number;
  startTime: string;
  endTime: string;
  location?: string | null;
  instructor?: string | null;
  validFrom?: string | null;
  validUntil?: string | null;
  semesterContext?: number;
  termContext?: string;
};
export type Page<T> = { items: T[]; nextCursor: string | null };
export type History = {
  id: string;
  action: string;
  actor: string;
  changes: Record<string, unknown>;
  recordedAt: string;
};
export type ClassroomMapping = {
  connectionId: string;
  externalCourseId: string;
  courseName: string | null;
  section: string | null;
  sourceAvailable: boolean;
  subjectKind: string | null;
  accountEmail: string | null;
};
export type SyncJob = {
  id: string;
  connectionId: string;
  mode: "import" | "reprocess";
  phase: string;
  status:
    | "queued"
    | "running"
    | "waiting_retry"
    | "completed"
    | "failed"
    | "cancelled";
  progress: Record<string, number>;
  attempts: number;
  nextRetryAt: string | null;
  error: { code: string; message: string; at?: string } | null;
  leased: boolean;
  createdAt: string;
  finishedAt: string | null;
};
export type Connection = {
  id: string;
  service: "gmail" | "classroom";
  status: "active" | "needs_reauth" | "disconnected";
  revision: number;
  account: {
    id: string;
    email: string;
    name: string | null;
    photo: string | null;
  };
  permissions: string[];
  lastAttemptAt: string | null;
  lastSuccessAt: string | null;
  retryAt: string | null;
  lastError: { code: string; message: string; at?: string } | null;
  activeJob: SyncJob | null;
  lastJob: SyncJob | null;
  records: {
    awaitingInterpretation: number;
    duplicates: number;
    blocked: number;
    ignored: number;
  };
};
export type ClassroomCourse = {
  externalCourseId: string;
  name: string;
  section: string | null;
  courseState: string | null;
  alternateLink: string | null;
  available: boolean;
  mappings: { subjectId: string; subjectName: string; subjectKind: string }[];
};
export type SenderPreference = {
  email: string;
  action: "include" | "block";
  revision: number;
  createdAt: string;
  updatedAt: string;
};
