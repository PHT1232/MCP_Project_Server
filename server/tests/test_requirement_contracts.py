"""T10 requirement contract model — one regression per acceptance item."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer

from pcs.config import get_settings
from pcs.context import service
from pcs.context.types import (
    CONTRACT_STATEMENT_MAX_CHARS,
    REQ_BLOCKED,
    REQ_DONE,
    REQ_IN_PROGRESS,
    REQ_NOT_STARTED,
    ContractNotFoundError,
    ContractRevisionView,
    CriterionView,
    InvariantView,
    ValidationError,
)
from pcs.db.base import session_scope
from pcs.requirements import contracts

PGVECTOR_IMAGE = "pgvector/pgvector:pg16"
PRIOR_HEAD = "0005_index_semantic"
PROJECT = "acme-web"
OTHER = "other-app"


async def _seed_requirement(*, name: str = PROJECT, title: str = "Ship login") -> str:
    async with session_scope() as session:
        with suppress(service.DuplicateProjectError):
            await service.register_project(
                session, name=name, root_path=f"/repos/{name}", overview=f"{name} overview"
            )
        req = await service.add_entry(session, project=name, section="requirements", headline=title)
        return req.id


class TestContractService:
    pytestmark = pytest.mark.usefixtures("clean_db")

    async def test_stable_keys_are_unique_within_parent_and_duplicates_are_actionable(
        self,
    ) -> None:
        req_a = await _seed_requirement(title="Auth")
        req_b = await _seed_requirement(title="Billing")
        async with session_scope() as session:
            first = await contracts.create_invariant(
                session,
                project=PROJECT,
                requirement_id=req_a,
                key="INV-1",
                statement="Login stays passwordless.",
                kind="behavior",
                risk="high",
            )
            await contracts.create_invariant(
                session,
                project=PROJECT,
                requirement_id=req_b,
                key="INV-1",
                statement="Same key is allowed on another requirement.",
                kind="behavior",
                risk="low",
            )
            with pytest.raises(ValidationError, match="already exists"):
                await contracts.create_invariant(
                    session,
                    project=PROJECT,
                    requirement_id=req_a,
                    key="INV-1",
                    statement="Duplicate key on the same requirement.",
                    kind="behavior",
                    risk="low",
                )
            second = await contracts.create_invariant(
                session,
                project=PROJECT,
                requirement_id=req_a,
                key="INV-2",
                statement="Second invariant.",
                kind="architecture",
                risk="medium",
            )
            with pytest.raises(ValidationError, match="already exists"):
                await contracts.update_invariant(
                    session, project=PROJECT, invariant_id=second.id, key="INV-1"
                )
            criterion = await contracts.create_criterion(
                session,
                project=PROJECT,
                invariant_id=first.id,
                key="AC-1",
                statement="pytest covers the login path.",
                evidence_kind="test",
            )
            await contracts.create_criterion(
                session,
                project=PROJECT,
                invariant_id=second.id,
                key="AC-1",
                statement="Same AC key is allowed on another invariant.",
                evidence_kind="manual",
            )
            with pytest.raises(ValidationError, match="already exists"):
                await contracts.create_criterion(
                    session,
                    project=PROJECT,
                    invariant_id=first.id,
                    key="AC-1",
                    statement="Duplicate criterion key.",
                    evidence_kind="test",
                )
            extra = await contracts.create_criterion(
                session,
                project=PROJECT,
                invariant_id=first.id,
                key="AC-2",
                statement="Second criterion.",
                evidence_kind="command",
            )
            with pytest.raises(ValidationError, match="already exists"):
                await contracts.update_criterion(
                    session, project=PROJECT, criterion_id=extra.id, key="AC-1"
                )
        assert first.key == "INV-1"
        assert criterion.key == "AC-1"

    async def test_invariant_and_criterion_crud_is_project_isolated_and_typed(self) -> None:
        req_a = await _seed_requirement(title="Auth")
        async with session_scope() as session:
            await service.register_project(
                session, name=OTHER, root_path="/repos/other", overview="other overview"
            )
            req_b = await service.add_entry(
                session, project=OTHER, section="requirements", headline="Other req"
            )
            req_b_id = req_b.id
        async with session_scope() as session:
            created = await contracts.create_invariant(
                session,
                project=PROJECT,
                requirement_id=req_a,
                key="INV-ISO",
                statement="Tokens never leave the store.",
                kind="data-boundary",
                risk="high",
                author="alice",
            )
            assert isinstance(created, InvariantView)
            merged = await contracts.update_invariant(
                session,
                project=PROJECT,
                invariant_id=created.id,
                statement="Tokens never leave the store or logs.",
            )
            assert merged.key == "INV-ISO"
            assert merged.statement.endswith("or logs.")
            assert merged.kind == "data-boundary"
            criterion = await contracts.create_criterion(
                session,
                project=PROJECT,
                invariant_id=created.id,
                key="AC-ISO",
                statement="Unit test asserts redaction.",
                evidence_kind="test",
                required=True,
                independent_review="required",
            )
            assert isinstance(criterion, CriterionView)
            updated_c = await contracts.update_criterion(
                session,
                project=PROJECT,
                criterion_id=criterion.id,
                required=False,
            )
            assert updated_c.required is False
            assert updated_c.independent_review == "required"
            listed_i = await contracts.list_invariants(
                session, project=PROJECT, requirement_id=req_a
            )
            listed_c = await contracts.list_criteria(session, project=PROJECT, requirement_id=req_a)
            other_i = await contracts.list_invariants(
                session, project=OTHER, requirement_id=req_b_id
            )
            fetched_i = await contracts.get_invariant(
                session, project=PROJECT, invariant_id=created.id
            )
            fetched_c = await contracts.get_criterion(
                session, project=PROJECT, criterion_id=criterion.id
            )
        assert [row.id for row in listed_i] == [created.id]
        assert [row.id for row in listed_c] == [criterion.id]
        assert other_i == []
        assert fetched_i.as_dict()["key"] == "INV-ISO"
        assert fetched_c.as_dict()["key"] == "AC-ISO"
        assert fetched_i.project_id != ""
        async with session_scope() as session:
            with pytest.raises(ValidationError, match="cross-project"):
                await contracts.get_invariant(session, project=OTHER, invariant_id=created.id)
            with pytest.raises(ValidationError, match="cross-project"):
                await contracts.get_criterion(session, project=OTHER, criterion_id=criterion.id)

    async def test_soft_delete_hides_from_active_reads_and_preserves_history(self) -> None:
        req_id = await _seed_requirement()
        async with session_scope() as session:
            invariant = await contracts.create_invariant(
                session,
                project=PROJECT,
                requirement_id=req_id,
                key="INV-DEL",
                statement="Must not bind a public interface.",
                kind="forbidden-path",
                risk="high",
            )
            criterion = await contracts.create_criterion(
                session,
                project=PROJECT,
                invariant_id=invariant.id,
                key="AC-DEL",
                statement="Bind-mode test stays green.",
                evidence_kind="test",
            )
            await contracts.update_invariant(
                session,
                project=PROJECT,
                invariant_id=invariant.id,
                statement="Must not bind a public or LAN interface.",
            )
            deleted = await contracts.delete_invariant(
                session, project=PROJECT, invariant_id=invariant.id, author="reviewer"
            )
            active_i = await contracts.list_invariants(
                session, project=PROJECT, requirement_id=req_id
            )
            active_c = await contracts.list_criteria(
                session, project=PROJECT, invariant_id=invariant.id
            )
            hidden_i = await contracts.list_invariants(
                session, project=PROJECT, requirement_id=req_id, include_deleted=True
            )
            hidden_c = await contracts.list_criteria(
                session, project=PROJECT, invariant_id=invariant.id, include_deleted=True
            )
            history = await contracts.list_contract_revisions(
                session, project=PROJECT, requirement_id=req_id
            )
            with pytest.raises(ContractNotFoundError, match=r"invariant"):
                await contracts.get_invariant(session, project=PROJECT, invariant_id=invariant.id)
            kept = await contracts.get_invariant(
                session, project=PROJECT, invariant_id=invariant.id, include_deleted=True
            )
        assert deleted.status == "deleted"
        assert active_i == []
        assert active_c == []
        assert [row.id for row in hidden_i] == [invariant.id]
        assert [row.id for row in hidden_c] == [criterion.id]
        assert hidden_c[0].status == "deleted"
        assert kept.status == "deleted"
        actions = [(row.entity_kind, row.action) for row in history]
        assert ("invariant", "create") in actions
        assert ("invariant", "update") in actions
        assert ("invariant", "delete") in actions
        assert ("criterion", "create") in actions
        assert ("criterion", "delete") in actions
        assert all(isinstance(row, ContractRevisionView) for row in history)
        assert all(row.snapshot for row in history)

    async def test_invalid_kind_risk_evidence_statement_and_cross_project_links_are_rejected(
        self,
    ) -> None:
        req_a = await _seed_requirement(title="Auth")
        async with session_scope() as session:
            await service.register_project(
                session, name=OTHER, root_path="/repos/other", overview="other overview"
            )
            req_b = await service.add_entry(
                session, project=OTHER, section="requirements", headline="Other req"
            )
            req_b_id = req_b.id
            other_inv = await contracts.create_invariant(
                session,
                project=OTHER,
                requirement_id=req_b_id,
                key="INV-X",
                statement="Other project invariant.",
                kind="behavior",
                risk="low",
            )
            other_inv_id = other_inv.id
        async with session_scope() as session:
            with pytest.raises(ValidationError, match="invalid kind"):
                await contracts.create_invariant(
                    session,
                    project=PROJECT,
                    requirement_id=req_a,
                    statement="bad kind",
                    kind="performance",
                    risk="low",
                )
            with pytest.raises(ValidationError, match="invalid risk"):
                await contracts.create_invariant(
                    session,
                    project=PROJECT,
                    requirement_id=req_a,
                    statement="bad risk",
                    kind="behavior",
                    risk="critical",
                )
            ok = await contracts.create_invariant(
                session,
                project=PROJECT,
                requirement_id=req_a,
                key="INV-OK",
                statement="Valid invariant.",
                kind="integration",
                risk="medium",
            )
            with pytest.raises(ValidationError, match="invalid evidence kind"):
                await contracts.create_criterion(
                    session,
                    project=PROJECT,
                    invariant_id=ok.id,
                    statement="bad evidence",
                    evidence_kind="screenshot",
                )
            with pytest.raises(ValidationError, match="exceeds"):
                await contracts.create_invariant(
                    session,
                    project=PROJECT,
                    requirement_id=req_a,
                    statement="x" * (CONTRACT_STATEMENT_MAX_CHARS + 1),
                    kind="manual",
                    risk="low",
                )
            with pytest.raises(ValidationError, match="exceeds"):
                await contracts.create_criterion(
                    session,
                    project=PROJECT,
                    invariant_id=ok.id,
                    statement="y" * (CONTRACT_STATEMENT_MAX_CHARS + 1),
                    evidence_kind="file",
                )
            with pytest.raises(ValidationError, match="cross-project"):
                await contracts.create_invariant(
                    session,
                    project=PROJECT,
                    requirement_id=req_b_id,
                    statement="linked to the other project",
                    kind="behavior",
                    risk="low",
                )
            with pytest.raises(ValidationError, match="cross-project"):
                await contracts.create_criterion(
                    session,
                    project=PROJECT,
                    invariant_id=other_inv_id,
                    statement="linked to the other project",
                    evidence_kind="review",
                )

    async def test_requirements_without_criteria_keep_legacy_status_updates(self) -> None:
        req_id = await _seed_requirement()
        async with session_scope() as session:
            listed = await contracts.list_criteria(session, project=PROJECT, requirement_id=req_id)
            assert listed == []
            started = await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_IN_PROGRESS
            )
            blocked = await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_BLOCKED
            )
            done = await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_DONE
            )
            reset = await service.set_requirement_status(
                session, project=PROJECT, entry_id=req_id, status=REQ_NOT_STARTED
            )
        assert started.requirement_status == REQ_IN_PROGRESS
        assert blocked.requirement_status == REQ_BLOCKED
        assert done.requirement_status == REQ_DONE
        assert reset.requirement_status == REQ_NOT_STARTED

    async def test_contract_writes_do_not_mutate_requirements_markdown(
        self, tmp_path: Path
    ) -> None:
        req_file = tmp_path / ".project-context" / "requirements.md"
        req_file.parent.mkdir(parents=True)
        original = "# Requirements\n\n### R-001 — Ship login\n\nKeep this prose.\n"
        req_file.write_text(original, encoding="utf-8")
        async with session_scope() as session:
            await service.register_project(
                session, name=PROJECT, root_path=str(tmp_path), overview="file isolation"
            )
            req = await service.add_entry(
                session, project=PROJECT, section="requirements", headline="Ship login"
            )
            await contracts.create_invariant(
                session,
                project=PROJECT,
                requirement_id=req.id,
                key="INV-FILE",
                statement="Must not rewrite the requirements file.",
                kind="architecture",
                risk="medium",
            )
        assert req_file.read_text(encoding="utf-8") == original


@contextmanager
def _temporary_database_url(url: str) -> Iterator[None]:
    previous = os.environ.get("PCS_DATABASE_URL")
    os.environ["PCS_DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("PCS_DATABASE_URL", None)
        else:
            os.environ["PCS_DATABASE_URL"] = previous
        get_settings.cache_clear()


def _requirement_snapshot(url: str) -> list[tuple[object, ...]]:
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, project_id, section, headline, detail, status, "
                "requirement_status, req_key FROM context_entries "
                "WHERE section = 'requirements' ORDER BY id"
            )
        ).fetchall()
    engine.dispose()
    return [tuple(row) for row in rows]


def _public_tables(url: str) -> set[str]:
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).fetchall()
    engine.dispose()
    return {str(row[0]) for row in rows}


def test_migration_upgrades_from_prior_head_and_downgrades_without_changing_requirement_rows() -> (
    None
):
    """Upgrade 0005 → head and downgrade back; context_entries stay byte-identical."""
    with PostgresContainer(PGVECTOR_IMAGE, driver="psycopg") as container:
        url = container.get_connection_url()
        with _temporary_database_url(url):
            config = Config("alembic.ini")
            command.upgrade(config, PRIOR_HEAD)
            engine = create_engine(url)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO projects (id, name, root_path) "
                        "VALUES ('proj-legacy', 'legacy', '/repos/legacy')"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO context_entries "
                        "(id, project_id, section, headline, detail, status, author, "
                        "requirement_status, req_key) "
                        "VALUES ('req-legacy', 'proj-legacy', 'requirements', "
                        "'Ship login', 'Must ship login', 'open', 'tester', "
                        "'in-progress', 'R-001')"
                    )
                )
            engine.dispose()
            before = _requirement_snapshot(url)
            assert before == [
                (
                    "req-legacy",
                    "proj-legacy",
                    "requirements",
                    "Ship login",
                    "Must ship login",
                    "open",
                    "in-progress",
                    "R-001",
                )
            ]
            command.upgrade(config, "head")
            after_upgrade = _requirement_snapshot(url)
            assert after_upgrade == before
            tables = _public_tables(url)
            assert "requirement_invariants" in tables
            assert "acceptance_criteria" in tables
            assert "requirement_contract_revisions" in tables
            engine = create_engine(url)
            with engine.connect() as conn:
                invariant_count = conn.execute(
                    text("SELECT COUNT(*) FROM requirement_invariants")
                ).scalar_one()
                criterion_count = conn.execute(
                    text("SELECT COUNT(*) FROM acceptance_criteria")
                ).scalar_one()
            engine.dispose()
            assert invariant_count == 0
            assert criterion_count == 0
            command.downgrade(config, PRIOR_HEAD)
            after_downgrade = _requirement_snapshot(url)
            assert after_downgrade == before
            tables_after = _public_tables(url)
            assert "requirement_invariants" not in tables_after
            assert "acceptance_criteria" not in tables_after
            assert "requirement_contract_revisions" not in tables_after
