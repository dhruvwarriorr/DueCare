"""Phase 2 source authorization, mappings, source records, sender preferences, and leased sync jobs."""

from alembic import op

revision = "0002"
down_revision = "0001"

# Frozen definitions; later model changes need their own migrations.
STATEMENTS = [
    "CREATE TABLE duecare.google_accounts (\n\tgoogle_sub VARCHAR(255) NOT NULL, \n\temail VARCHAR(320) NOT NULL, \n\tdata JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (id, user_id), \n\tUNIQUE (user_id, google_sub)\n)",
    "CREATE INDEX ix_duecare_google_accounts_user_id ON duecare.google_accounts (user_id)",
    "CREATE TABLE duecare.oauth_grants (\n\taccount_id UUID NOT NULL, \n\tscopes JSONB NOT NULL, \n\trefresh_token VARCHAR, \n\taccess_token VARCHAR, \n\taccess_expires_at TIMESTAMP WITH TIME ZONE, \n\tkey_version VARCHAR(50) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (account_id), \n\tFOREIGN KEY(account_id, user_id) REFERENCES duecare.google_accounts (id, user_id) ON DELETE CASCADE, \n\tCHECK (status in ('active','revoked','invalid'))\n)",
    "CREATE INDEX ix_duecare_oauth_grants_user_id ON duecare.oauth_grants (user_id)",
    "CREATE TABLE duecare.connections (\n\taccount_id UUID NOT NULL, \n\tservice VARCHAR(20) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tscopes JSONB NOT NULL, \n\tlast_attempt_at TIMESTAMP WITH TIME ZONE, \n\tlast_success_at TIMESTAMP WITH TIME ZONE, \n\tretry_at TIMESTAMP WITH TIME ZONE, \n\tcheckpoint JSONB NOT NULL, \n\tdata JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (id, user_id), \n\tUNIQUE (account_id, service), \n\tFOREIGN KEY(account_id, user_id) REFERENCES duecare.google_accounts (id, user_id) ON DELETE CASCADE, \n\tCHECK (service in ('gmail','classroom')), \n\tCHECK (status in ('active','needs_reauth','disconnected'))\n)",
    "CREATE INDEX ix_duecare_connections_account_id ON duecare.connections (account_id)",
    "CREATE INDEX ix_duecare_connections_user_id ON duecare.connections (user_id)",
    "CREATE TABLE duecare.source_courses (\n\tconnection_id UUID NOT NULL, \n\texternal_course_id VARCHAR(100) NOT NULL, \n\tname VARCHAR(500) NOT NULL, \n\tavailable BOOLEAN NOT NULL, \n\tdata JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (connection_id, external_course_id), \n\tFOREIGN KEY(connection_id, user_id) REFERENCES duecare.connections (id, user_id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix_duecare_source_courses_connection_id ON duecare.source_courses (connection_id)",
    "CREATE INDEX ix_duecare_source_courses_user_id ON duecare.source_courses (user_id)",
    "CREATE TABLE duecare.subject_mappings (\n\tsubject_id UUID NOT NULL, \n\tconnection_id UUID NOT NULL, \n\texternal_course_id VARCHAR(100) NOT NULL, \n\tsource_available BOOLEAN NOT NULL, \n\tdata JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (subject_id, connection_id, external_course_id), \n\tFOREIGN KEY(subject_id, user_id) REFERENCES duecare.subjects (id, user_id) ON DELETE CASCADE, \n\tFOREIGN KEY(connection_id, user_id) REFERENCES duecare.connections (id, user_id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix_duecare_subject_mappings_connection_id ON duecare.subject_mappings (connection_id)",
    "CREATE INDEX ix_duecare_subject_mappings_subject_id ON duecare.subject_mappings (subject_id)",
    "CREATE INDEX ix_duecare_subject_mappings_user_id ON duecare.subject_mappings (user_id)",
    "CREATE TABLE duecare.source_records (\n\tconnection_id UUID NOT NULL, \n\tprovider_id VARCHAR(600) NOT NULL, \n\tkind VARCHAR(40) NOT NULL, \n\texternal_course_id VARCHAR(100), \n\tsender_email VARCHAR(320), \n\ttitle VARCHAR(1000), \n\tmessage_id VARCHAR(1000), \n\tthread_id VARCHAR(200), \n\tsent_at TIMESTAMP WITH TIME ZONE, \n\treceived_at TIMESTAMP WITH TIME ZONE, \n\tpublished_at TIMESTAMP WITH TIME ZONE, \n\tsource_updated_at TIMESTAMP WITH TIME ZONE, \n\tcontent_hash VARCHAR(64), \n\tprocessing_state VARCHAR(30) NOT NULL, \n\tprocessing_version VARCHAR(50) NOT NULL, \n\ttargeting_outcome VARCHAR(30), \n\treason VARCHAR(100), \n\texcerpt VARCHAR(2000), \n\texpires_at TIMESTAMP WITH TIME ZONE, \n\tdata JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (id, user_id), \n\tUNIQUE (connection_id, provider_id), \n\tFOREIGN KEY(connection_id, user_id) REFERENCES duecare.connections (id, user_id) ON DELETE CASCADE, \n\tCHECK (processing_state in ('awaiting_interpretation','duplicate','blocked','ignored','unavailable'))\n)",
    "CREATE INDEX ix_duecare_source_records_connection_id ON duecare.source_records (connection_id)",
    "CREATE INDEX ix_duecare_source_records_sender_email ON duecare.source_records (sender_email)",
    "CREATE INDEX ix_duecare_source_records_user_id ON duecare.source_records (user_id)",
    "CREATE TABLE duecare.source_attachments (\n\tsource_record_id UUID NOT NULL, \n\tkind VARCHAR(30) NOT NULL, \n\ttitle VARCHAR(1000), \n\treference VARCHAR(2000), \n\tmedia_type VARCHAR(200), \n\tsize_bytes INTEGER, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(source_record_id, user_id) REFERENCES duecare.source_records (id, user_id) ON DELETE CASCADE\n)",
    "CREATE INDEX ix_duecare_source_attachments_source_record_id ON duecare.source_attachments (source_record_id)",
    "CREATE INDEX ix_duecare_source_attachments_user_id ON duecare.source_attachments (user_id)",
    "CREATE TABLE duecare.sender_preferences (\n\temail VARCHAR(320) NOT NULL, \n\taction VARCHAR(10) NOT NULL, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, email), \n\tCHECK (action in ('include','block'))\n)",
    "CREATE INDEX ix_duecare_sender_preferences_user_id ON duecare.sender_preferences (user_id)",
    "CREATE TABLE duecare.sync_jobs (\n\tconnection_id UUID NOT NULL, \n\tmode VARCHAR(20) NOT NULL, \n\tphase VARCHAR(40) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tcheckpoint JSONB NOT NULL, \n\tprogress JSONB NOT NULL, \n\tlease_owner VARCHAR(64), \n\tlease_expires_at TIMESTAMP WITH TIME ZONE, \n\tnext_retry_at TIMESTAMP WITH TIME ZONE, \n\tattempts INTEGER NOT NULL, \n\terror JSONB, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(connection_id, user_id) REFERENCES duecare.connections (id, user_id) ON DELETE CASCADE, \n\tCHECK (mode in ('import','reprocess')), \n\tCHECK (status in ('queued','running','waiting_retry','completed','failed','cancelled'))\n)",
    "CREATE INDEX ix_duecare_sync_jobs_connection_id ON duecare.sync_jobs (connection_id)",
    "CREATE INDEX ix_duecare_sync_jobs_user_id ON duecare.sync_jobs (user_id)",
    "CREATE TABLE duecare_internal.oauth_states (\n\tid VARCHAR(64) NOT NULL, \n\tuser_id UUID NOT NULL, \n\tservice VARCHAR(20) NOT NULL, \n\tverifier VARCHAR NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)",
]
OWNED = [
    "google_accounts",
    "oauth_grants",
    "connections",
    "source_courses",
    "subject_mappings",
    "source_records",
    "source_attachments",
    "sender_preferences",
    "sync_jobs",
]


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)
    # One active leased job per connection; finished jobs remain as history.
    op.execute(
        "create unique index sync_jobs_one_active on duecare.sync_jobs (connection_id) "
        "where status in ('queued','running','waiting_retry')"
    )
    op.execute("create index source_records_message on duecare.source_records (connection_id,message_id)")
    op.execute("create index source_records_state on duecare.source_records (connection_id,processing_state)")
    op.execute("create index source_records_expiry on duecare.source_records (user_id,expires_at)")
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
    op.drop_table("oauth_states", schema="duecare_internal")
    for table in reversed(OWNED):
        op.drop_table(table, schema="duecare")
