"""Allow append-only DELETE only during project teardown.

Revision ID: 0027_project_teardown_triggers
Revises: 0026_entry_diagram

``requirement_evidence``, ``requirement_contract_revisions``, and
``plan_task_events`` reject row UPDATE/DELETE so history stays immutable.
Project unregister still has to remove those rows (RESTRICT FKs plus the
triggers would otherwise block ``DELETE FROM projects``).

``delete_project`` sets the transaction-local GUC ``pcs.project_teardown=on``
before the ordered deletes. Single-row mutation outside that GUC still
raises, so INV-PLAN-4 / T10 / T12 append-only tests stay valid.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_project_teardown_triggers"
down_revision: str | None = "0026_entry_diagram"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALLOW_TEARDOWN = """
  IF TG_OP = 'DELETE' AND current_setting('pcs.project_teardown', true) = 'on' THEN
    RETURN OLD;
  END IF;
"""


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION pcs_reject_contract_revision_update()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
            {_ALLOW_TEARDOWN}
              RAISE EXCEPTION
                'contract revisions are append-only; mutation rejected';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION pcs_reject_evidence_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
            {_ALLOW_TEARDOWN}
              RAISE EXCEPTION
                'requirement evidence is append-only; mutation rejected';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION pcs_reject_plan_task_event_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
            {_ALLOW_TEARDOWN}
              RAISE EXCEPTION
                'plan task events are append-only; mutation rejected';
            END;
            $$
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION pcs_reject_contract_revision_update()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              RAISE EXCEPTION
                'contract revisions are append-only; mutation rejected';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION pcs_reject_evidence_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              RAISE EXCEPTION
                'requirement evidence is append-only; mutation rejected';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION pcs_reject_plan_task_event_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              RAISE EXCEPTION
                'plan task events are append-only; mutation rejected';
            END;
            $$
            """
        )
    )
