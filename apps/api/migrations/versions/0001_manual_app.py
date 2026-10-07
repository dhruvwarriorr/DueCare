"""Phase 1 private application schema. Supabase auth tables are never owned here."""

from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    op.execute("create schema if not exists duecare")
    op.execute("create schema if not exists duecare_internal")
    op.execute(
        "CREATE TABLE duecare.profiles (\n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tdata JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (user_id)\n)"
    )
    op.execute(
        "CREATE TABLE duecare.subjects (\n\tname VARCHAR(200) NOT NULL, \n\tkind VARCHAR(20) NOT NULL, \n\tdata JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (id, user_id), \n\tCHECK (kind in ('theory','lab','tutorial'))\n)"
    )
    op.execute("CREATE INDEX ix_duecare_subjects_user_id ON duecare.subjects (user_id)")
    op.execute(
        "CREATE TABLE duecare_internal.web_sessions (\n\tid VARCHAR(64) NOT NULL, \n\tuser_id UUID NOT NULL, \n\ttokens VARCHAR NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)"
    )
    op.execute(
        "CREATE TABLE duecare_internal.login_states (\n\tid VARCHAR(64) NOT NULL, \n\tverifier VARCHAR NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)"
    )
    op.execute(
        "CREATE TABLE duecare.operations (\n\tkey VARCHAR(100) NOT NULL, \n\tfingerprint VARCHAR(64) NOT NULL, \n\tresult JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, key)\n)"
    )
    op.execute("CREATE INDEX ix_duecare_operations_user_id ON duecare.operations (user_id)")
    op.execute(
        "CREATE TABLE duecare.subject_timetable_slots (\n\tsubject_id UUID NOT NULL, \n\tdata JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(subject_id, user_id) REFERENCES duecare.subjects (id, user_id) ON DELETE CASCADE\n)"
    )
    op.execute(
        "CREATE INDEX ix_duecare_subject_timetable_slots_subject_id ON duecare.subject_timetable_slots (subject_id)"
    )
    op.execute(
        "CREATE INDEX ix_duecare_subject_timetable_slots_user_id ON duecare.subject_timetable_slots (user_id)"
    )
    op.execute(
        "CREATE TABLE duecare.tasks (\n\tsubject_id UUID, \n\ttitle VARCHAR(300) NOT NULL, \n\ttype VARCHAR(20) NOT NULL, \n\tdue_at TIMESTAMP WITH TIME ZONE, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tstatus VARCHAR(20) NOT NULL, \n\tdata JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (id, user_id), \n\tFOREIGN KEY(subject_id, user_id) REFERENCES duecare.subjects (id, user_id), \n\tCHECK (type in ('assignment','test')), \n\tCHECK (status in ('due','completed','overdue','missed')), \n\tCHECK (status != 'overdue' or type = 'assignment'), \n\tCHECK (status != 'missed' or type = 'test')\n)"
    )
    op.execute("CREATE INDEX ix_duecare_tasks_completed_at ON duecare.tasks (completed_at)")
    op.execute("CREATE INDEX ix_duecare_tasks_due_at ON duecare.tasks (due_at)")
    op.execute("CREATE INDEX ix_duecare_tasks_user_id ON duecare.tasks (user_id)")
    op.execute("CREATE INDEX ix_duecare_tasks_subject_id ON duecare.tasks (subject_id)")
    op.execute(
        "CREATE TABLE duecare.task_history (\n\ttask_id UUID NOT NULL, \n\taction VARCHAR(30) NOT NULL, \n\tchanges JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(task_id, user_id) REFERENCES duecare.tasks (id, user_id) ON DELETE CASCADE\n)"
    )
    op.execute("CREATE INDEX ix_duecare_task_history_task_id ON duecare.task_history (task_id)")
    op.execute("CREATE INDEX ix_duecare_task_history_user_id ON duecare.task_history (user_id)")
    op.execute("revoke all on schema duecare, duecare_internal from public")
    op.execute("""do $$ begin
        if not exists (select 1 from pg_roles where rolname='duecare_runtime') then
            create role duecare_runtime nologin nosuperuser nobypassrls;
        end if;
    end $$""")
    op.execute("grant usage on schema duecare,duecare_internal to duecare_runtime")
    op.execute(
        "grant select,insert,update,delete on all tables in schema duecare,duecare_internal to duecare_runtime"
    )
    for table in ["profiles", "subjects", "subject_timetable_slots", "tasks", "task_history", "operations"]:
        op.execute(f"alter table duecare.{table} enable row level security")
        op.execute(f"alter table duecare.{table} force row level security")
        op.execute(f"""create policy owner on duecare.{table} to duecare_runtime
            using (user_id = nullif(current_setting('app.user_id',true),'')::uuid)
            with check (user_id = nullif(current_setting('app.user_id',true),'')::uuid)""")
    op.execute("create index task_owner_cutoff on duecare.tasks (user_id,completed_at,due_at)")


def downgrade():
    op.drop_table("task_history", schema="duecare")
    op.drop_table("subject_timetable_slots", schema="duecare")
    op.drop_table("tasks", schema="duecare")
    op.drop_table("subjects", schema="duecare")
    op.drop_table("operations", schema="duecare")
    op.drop_table("profiles", schema="duecare")
    op.drop_table("web_sessions", schema="duecare_internal")
    op.drop_table("login_states", schema="duecare_internal")
    op.execute("drop schema duecare_internal")
    op.execute("drop schema duecare")
