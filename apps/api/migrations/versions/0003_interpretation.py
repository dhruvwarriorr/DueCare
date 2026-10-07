"""Phase 3 interpretation: source events, task evidence, review items, rules, and merges."""

from alembic import op

revision = "0003"
down_revision = "0002"

STATES = "'awaiting_interpretation','duplicate','blocked','ignored','unavailable'"
# Frozen definitions; later model changes need their own migrations.
STATEMENTS = [
    "CREATE TABLE duecare.source_events (\n\tsource_record_id UUID NOT NULL, \n\tevent_key VARCHAR(200) NOT NULL, \n\tevent_type VARCHAR(20) NOT NULL, \n\tidentity_key VARCHAR(600), \n\toccurred_at TIMESTAMP WITH TIME ZONE, \n\toutcome VARCHAR(30) NOT NULL, \n\ttask_id UUID, \n\tprocessing_version VARCHAR(50) NOT NULL, \n\tdata JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (id, user_id), \n\tUNIQUE (source_record_id, event_key), \n\tFOREIGN KEY(source_record_id, user_id) REFERENCES duecare.source_records (id, user_id) ON DELETE CASCADE, \n\tCHECK (event_type in ('new_work','revision','due_notice','supporting','submission','unsubmission','withdrawal','unknown'))\n)",
    "CREATE INDEX ix_duecare_source_events_identity_key ON duecare.source_events (identity_key)",
    "CREATE INDEX ix_duecare_source_events_source_record_id ON duecare.source_events (source_record_id)",
    "CREATE INDEX ix_duecare_source_events_task_id ON duecare.source_events (task_id)",
    "CREATE INDEX ix_duecare_source_events_user_id ON duecare.source_events (user_id)",
    "CREATE TABLE duecare.task_evidence (\n\ttask_id UUID NOT NULL, \n\tevent_id UUID NOT NULL, \n\tmethod VARCHAR(30) NOT NULL, \n\tstate VARCHAR(20) NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (id, user_id), \n\tUNIQUE (task_id, event_id), \n\tFOREIGN KEY(task_id, user_id) REFERENCES duecare.tasks (id, user_id) ON DELETE CASCADE, \n\tFOREIGN KEY(event_id, user_id) REFERENCES duecare.source_events (id, user_id) ON DELETE CASCADE, \n\tCHECK (state in ('active','reassigned'))\n)",
    "CREATE INDEX ix_duecare_task_evidence_event_id ON duecare.task_evidence (event_id)",
    "CREATE INDEX ix_duecare_task_evidence_task_id ON duecare.task_evidence (task_id)",
    "CREATE INDEX ix_duecare_task_evidence_user_id ON duecare.task_evidence (user_id)",
    "CREATE TABLE duecare.review_items (\n\tissue_type VARCHAR(40) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\ttask_id UUID, \n\tsource_record_id UUID, \n\tevent_id UUID, \n\tsender_email VARCHAR(320), \n\tquestion VARCHAR(500) NOT NULL, \n\tdata JSONB NOT NULL, \n\tresolved_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (id, user_id), \n\tFOREIGN KEY(source_record_id, user_id) REFERENCES duecare.source_records (id, user_id) ON DELETE CASCADE, \n\tCHECK (status in ('open','resolved','dismissed','suppressed'))\n)",
    "CREATE INDEX ix_duecare_review_items_sender_email ON duecare.review_items (sender_email)",
    "CREATE INDEX ix_duecare_review_items_source_record_id ON duecare.review_items (source_record_id)",
    "CREATE INDEX ix_duecare_review_items_task_id ON duecare.review_items (task_id)",
    "CREATE INDEX ix_duecare_review_items_user_id ON duecare.review_items (user_id)",
    "CREATE TABLE duecare.rules (\n\tname VARCHAR(200) NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tposition INTEGER NOT NULL, \n\tdata JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (id, user_id)\n)",
    "CREATE INDEX ix_duecare_rules_user_id ON duecare.rules (user_id)",
    "CREATE TABLE duecare.merge_operations (\n\tsurviving_task_id UUID NOT NULL, \n\tabsorbed_task_id UUID NOT NULL, \n\tdata JSONB NOT NULL, \n\tundone_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(surviving_task_id, user_id) REFERENCES duecare.tasks (id, user_id) ON DELETE CASCADE, \n\tFOREIGN KEY(absorbed_task_id, user_id) REFERENCES duecare.tasks (id, user_id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix_duecare_merge_operations_absorbed_task_id ON duecare.merge_operations (absorbed_task_id)",
    "CREATE INDEX ix_duecare_merge_operations_surviving_task_id ON duecare.merge_operations (surviving_task_id)",
    "CREATE INDEX ix_duecare_merge_operations_user_id ON duecare.merge_operations (user_id)",
]
OWNED = ["source_events", "task_evidence", "review_items", "rules", "merge_operations"]


def replace_state_check(states):
    # 0002 created this check without an explicit name; drop whichever name PostgreSQL assigned.
    op.execute("""do $$ declare c text; begin
        for c in select conname from pg_constraint where conrelid='duecare.source_records'::regclass
            and contype='c' and pg_get_constraintdef(oid) like '%processing_state%' loop
            execute format('alter table duecare.source_records drop constraint %I', c);
        end loop; end $$""")
    op.execute(
        f"alter table duecare.source_records add constraint source_records_state check (processing_state in ({states}))"
    )


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)
    replace_state_check(STATES + ",'interpreted','needs_review'")
    op.execute("create index review_items_open on duecare.review_items (user_id,status)")
    op.execute("create index source_events_task on duecare.source_events (user_id,task_id)")
    op.execute(
        "grant select,insert,update,delete on all tables in schema duecare,duecare_internal to duecare_runtime"
    )
    for table in OWNED:
        op.execute(f"alter table duecare.{table} enable row level security")
        op.execute(f"alter table duecare.{table} force row level security")
        op.execute(f"""create policy owner on duecare.{table} to duecare_runtime
            using (user_id = nullif(current_setting('app.user_id',true),'')::uuid)
            with check (user_id = nullif(current_setting('app.user_id',true),'')::uuid)""")


def downgrade():
    for table in reversed(OWNED):
        op.drop_table(table, schema="duecare")
    op.execute(
        "update duecare.source_records set processing_state='awaiting_interpretation' "
        "where processing_state in ('interpreted','needs_review')"
    )
    replace_state_check(STATES)
