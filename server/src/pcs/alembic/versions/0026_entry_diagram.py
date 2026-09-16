"""Feature-doc sequence diagram: nullable diagram column.

Revision ID: 0026_entry_diagram
Revises: 0025_token_savings_log

Adds a nullable ``diagram`` text column to ``context_entries`` and its
``context_entry_revisions`` audit mirror, alongside ``linked_files``/
``related_entry_id``. Agent-authored Mermaid ``sequenceDiagram`` syntax for
a ``features``-section entry; validated (section gate + size cap) at the
service layer, not the database.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_entry_diagram"
down_revision: str | None = "0025_token_savings_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("context_entries", sa.Column("diagram", sa.Text(), nullable=True))
    op.add_column("context_entry_revisions", sa.Column("diagram", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("context_entry_revisions", "diagram")
    op.drop_column("context_entries", "diagram")
