"""One past-deadline status: incomplete work whose cutoff passed is "missed", assignment or test."""

from alembic import op

revision = "0006"
down_revision = "0005"

# The original checks were unnamed, so their generated names can differ between databases.
DROP_STATUS_CHECKS = """do $$ declare c record; begin
    for c in select conname from pg_constraint
        where conrelid = 'duecare.tasks'::regclass and contype = 'c'
          and pg_get_constraintdef(oid) ~ '(overdue|missed)'
    loop execute format('alter table duecare.tasks drop constraint %I', c.conname); end loop;
end $$"""


def upgrade():
    op.execute(DROP_STATUS_CHECKS)
    op.execute("update duecare.tasks set status = 'missed' where status = 'overdue'")
    op.execute(
        "alter table duecare.tasks add constraint tasks_status_check "
        "check (status in ('due','completed','missed'))"
    )


def downgrade():
    op.execute(DROP_STATUS_CHECKS)
    op.execute("update duecare.tasks set status = 'overdue' where status = 'missed' and type = 'assignment'")
    op.execute(
        "alter table duecare.tasks add constraint tasks_status_check "
        "check (status in ('due','completed','overdue','missed'))"
    )
    op.execute(
        "alter table duecare.tasks add constraint tasks_check check (status <> 'overdue' or type = 'assignment')"
    )
    op.execute(
        "alter table duecare.tasks add constraint tasks_check1 check (status <> 'missed' or type = 'test')"
    )
