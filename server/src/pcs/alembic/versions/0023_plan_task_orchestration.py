"""T23: Plan & Task orchestration core tables and composite constraints.

Revision ID: 0023_plan_task_orchestration
Revises: 0019_evidence_quality
Create Date: 2026-09-14

Creates plans, plan_tasks, task_dependencies, plan_task_requirements, and
plan_task_events. Enforces plan and project tenant isolation via composite
foreign keys and strict section validation for requirements (INV-PLAN-1).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_plan_task_orchestration"
down_revision: str | None = "0019_evidence_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. plans table
    op.create_table(
        "plans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("author", sa.String(length=120), nullable=False, server_default="agent"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'completed', 'archived')",
            name="ck_plans_status",
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 160",
            name="ck_plans_title_len",
        ),
        sa.CheckConstraint(
            "char_length(goal) BETWEEN 1 AND 8000",
            name="ck_plans_goal_len",
        ),
        sa.UniqueConstraint("id", "project_id", name="uq_plans_id_project"),
    )
    op.create_index("ix_plans_project_id", "plans", ["project_id"])
    op.create_index("ix_plans_project_status", "plans", ["project_id", "status"])

    # 2. plan_tasks table
    op.create_table(
        "plan_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("local_task_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column(
            "acceptance_criteria",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "linked_files",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("claim_token_hash", sa.String(length=64), nullable=True),
        sa.Column("claimed_by", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "project_id"],
            ["plans.id", "plans.project_id"],
            ondelete="CASCADE",
            name="fk_plan_tasks_plan",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'claimed', 'in_progress', 'blocked', "
            "'in_review', 'completed', 'cancelled')",
            name="ck_plan_tasks_status",
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 160",
            name="ck_plan_tasks_title_len",
        ),
        sa.CheckConstraint(
            "char_length(objective) BETWEEN 1 AND 8000",
            name="ck_plan_tasks_objective_len",
        ),
        sa.CheckConstraint(
            "char_length(local_task_id) BETWEEN 1 AND 32",
            name="ck_plan_tasks_local_task_id_len",
        ),
        sa.UniqueConstraint("id", "plan_id", "project_id", name="uq_plan_tasks_id_plan_project"),
        sa.UniqueConstraint("id", "project_id", name="uq_plan_tasks_id_project"),
        sa.UniqueConstraint("plan_id", "local_task_id", name="uq_plan_tasks_plan_local_id"),
    )
    op.create_index("ix_plan_tasks_project_status", "plan_tasks", ["project_id", "status"])
    op.create_index("ix_plan_tasks_plan_status", "plan_tasks", ["plan_id", "status"])
    op.create_index("ix_plan_tasks_lease_expires_at", "plan_tasks", ["lease_expires_at"])

    # 3. task_dependencies table
    op.create_table(
        "task_dependencies",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("depends_on_task_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("task_id", "depends_on_task_id"),
        sa.CheckConstraint(
            "task_id != depends_on_task_id", name="ck_task_dependencies_no_self_dep"
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "plan_id", "project_id"],
            ["plan_tasks.id", "plan_tasks.plan_id", "plan_tasks.project_id"],
            ondelete="CASCADE",
            name="fk_task_deps_task",
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_task_id", "plan_id", "project_id"],
            ["plan_tasks.id", "plan_tasks.plan_id", "plan_tasks.project_id"],
            ondelete="CASCADE",
            name="fk_task_deps_depends_on",
        ),
    )
    op.create_index("ix_task_dependencies_depends_on", "task_dependencies", ["depends_on_task_id"])
    op.create_index("ix_task_dependencies_plan_id", "task_dependencies", ["plan_id"])

    # 4. plan_task_requirements table
    op.create_table(
        "plan_task_requirements",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("plan_task_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=False),
        sa.Column(
            "requirement_section",
            sa.String(length=32),
            nullable=False,
            server_default="requirements",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("plan_task_id", "requirement_id"),
        sa.CheckConstraint(
            "requirement_section = 'requirements'",
            name="ck_plan_task_requirements_section",
        ),
        sa.ForeignKeyConstraint(
            ["plan_task_id", "project_id"],
            ["plan_tasks.id", "plan_tasks.project_id"],
            ondelete="CASCADE",
            name="fk_plan_task_reqs_task",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id", "project_id"],
            ["context_entries.id", "context_entries.project_id"],
            ondelete="CASCADE",
            name="fk_plan_task_reqs_req_project",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id", "requirement_section"],
            ["context_entries.id", "context_entries.section"],
            ondelete="CASCADE",
            name="fk_plan_task_reqs_req_section",
        ),
    )
    op.create_index(
        "ix_plan_task_requirements_project_req",
        "plan_task_requirements",
        ["project_id", "requirement_id"],
    )
    op.create_index(
        "ix_plan_task_requirements_task_id",
        "plan_task_requirements",
        ["plan_task_id"],
    )

    # 5. plan_task_events table
    op.create_table(
        "plan_task_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("old_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('created', 'updated', 'dependency_added', 'claimed', "
            "'reclaimed', 'heartbeat', 'released', 'status_changed', 'completed', 'cancelled')",
            name="ck_plan_task_events_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "plan_id", "project_id"],
            ["plan_tasks.id", "plan_tasks.plan_id", "plan_tasks.project_id"],
            ondelete="CASCADE",
            name="fk_plan_task_events_task_plan_project",
        ),
    )
    op.create_index(
        "ix_plan_task_events_task_created",
        "plan_task_events",
        ["task_id", "created_at"],
    )
    op.create_index(
        "ix_plan_task_events_plan_created",
        "plan_task_events",
        ["plan_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("plan_task_events")
    op.drop_table("plan_task_requirements")
    op.drop_table("task_dependencies")
    op.drop_table("plan_tasks")
    op.drop_table("plans")
