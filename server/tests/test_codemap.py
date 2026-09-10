"""T05 tests: code-map API — LOD aggregation, dependency edges, context overlay.

Covers AC11 (top-level nodes match module structure + edges), AC12 (a node whose
file has an open blocker/bug is flagged), AC20 (default depth = top tier +
aggregated edges; expanding a scope fetches only that subtree), plus a "scales"
test (a wide/deep synthetic repo → the default response stays small).

Runs on the real Postgres (pgvector) testcontainer via the shared fixtures.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import cast

import pytest

from pcs.codemap import service as codemap_service
from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.index import service as index_service
from pcs.mcp import build_http_app, mcp

pytestmark = pytest.mark.usefixtures("clean_db")

PROJECT = "acme-codemap"
OVERVIEW = "Sample repo for the code-map API tests."


def _sample_repo(root: Path) -> None:
    (root / "services" / "billing").mkdir(parents=True)
    (root / "services" / "pricing").mkdir(parents=True)
    (root / "services" / "api").mkdir(parents=True)
    (root / "lib").mkdir()

    (root / "services" / "pricing" / "__init__.py").write_text("", encoding="utf-8")
    (root / "services" / "pricing" / "rates.py").write_text(
        "def price(sku):\n    return 10\n", encoding="utf-8"
    )
    (root / "services" / "billing" / "invoice.py").write_text(
        "from services.pricing import rates\n"
        "from lib.money import Money\n\n"
        "def make_invoice(order):\n    return Money(rates.price(order))\n",
        encoding="utf-8",
    )
    (root / "services" / "billing" / "tax.py").write_text(
        "from services.pricing import rates\n\n"
        "def tax(order):\n    return rates.price(order) * 0.1\n",
        encoding="utf-8",
    )
    (root / "services" / "api" / "routes.py").write_text(
        "from services.billing.invoice import make_invoice\n"
        "from services.pricing.rates import price\n\n"
        "def handler(req):\n    return make_invoice(req)\n",
        encoding="utf-8",
    )
    (root / "lib" / "money.py").write_text(
        "class Money:\n    def __init__(self, amount):\n        self.amount = amount\n",
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "from services.api.routes import handler\n\ndef run():\n    return handler(None)\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Acme\nA sample.\n", encoding="utf-8")


async def _register_and_index(root: Path) -> None:
    _sample_repo(root)
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(root), overview=OVERVIEW
        )
    async with session_scope() as session:
        await index_service.reindex(session, project=PROJECT, incremental=False)


def _paths(nodes: Iterable[dict[str, object]], *, inside_only: bool = False) -> set[str]:
    return {str(n["path"]) for n in nodes if not (inside_only and n.get("outside_scope"))}


def _edge_pairs(edges: Iterable[dict[str, object]]) -> set[tuple[str, str]]:
    return {(str(e["source"]), str(e["target"])) for e in edges}


# --------------------------------------------------------------------------- #
# AC11 — top-level nodes match the real module structure, with dependency edges
# --------------------------------------------------------------------------- #


async def test_ac11_top_level_nodes_and_edges_match_module_structure(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        code_map = await codemap_service.get_code_map(session, project=PROJECT)

    assert code_map["scope"] is None
    assert code_map["depth"] == 1
    nodes = cast(list[dict[str, object]], code_map["nodes"])
    paths = _paths(nodes)
    assert paths == {"services", "lib", "main.py", "README.md"}

    services = next(n for n in nodes if n["path"] == "services")
    assert services["kind"] == "directory"
    assert services["has_children"] is True
    assert cast(int, services["file_count"]) >= 5
    assert services["language"] == "python"

    pairs = _edge_pairs(cast(list[dict[str, object]], code_map["edges"]))
    # main.py imports services.api.routes; services (invoice) imports lib.money.
    assert ("file:main.py", "dir:services") in pairs
    assert ("dir:services", "dir:lib") in pairs
    # intra-`services` edges (billing -> pricing) collapse at the top tier.
    assert ("dir:services", "dir:services") not in pairs


async def test_ac11_expanding_scope_returns_only_that_subtree(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        full = await codemap_service.get_code_map(session, project=PROJECT)
        sub = await codemap_service.get_code_map(session, project=PROJECT, scope="services")

    assert sub["scope"] == "services"
    inside = _paths(cast(list[dict[str, object]], sub["nodes"]), inside_only=True)
    assert inside == {"services/billing", "services/pricing", "services/api"}

    pairs = _edge_pairs(cast(list[dict[str, object]], sub["edges"]))
    assert ("dir:services/billing", "dir:services/pricing") in pairs
    assert ("dir:services/api", "dir:services/billing") in pairs

    # billing -> pricing aggregates invoice.py + tax.py into weight 2.
    weight = next(
        int(cast(int, e["weight"]))
        for e in cast(list[dict[str, object]], sub["edges"])
        if e["source"] == "dir:services/billing" and e["target"] == "dir:services/pricing"
    )
    assert weight == 2

    # Expanding never re-sends the whole graph: no top-level siblings of `services`.
    assert "lib" not in _paths(cast(list[dict[str, object]], sub["nodes"]))
    # And the full map had strictly fewer nodes than the repo has files.
    assert cast(int, cast(dict[str, object], full["stats"])["total_files"]) > len(
        cast(list[dict[str, object]], full["nodes"])
    )


async def test_symbol_scope_returns_file_symbols_and_deps(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        code_map = await codemap_service.get_code_map(
            session, project=PROJECT, scope="services/billing/invoice.py"
        )
    assert code_map["scope_kind"] == "file"
    labels = {str(n["label"]) for n in cast(list[dict[str, object]], code_map["nodes"])}
    assert "make_invoice" in labels
    assert all(n["kind"] == "symbol" for n in cast(list[dict[str, object]], code_map["nodes"]))
    deps = cast(list[str], code_map["dependencies"])
    assert "services/pricing/__init__.py" in deps or "services/pricing/rates.py" in deps
    assert "lib/money.py" in deps
    # routes.py imports invoice.make_invoice → invoice.py has a dependent.
    assert "services/api/routes.py" in cast(list[str], code_map["dependents"])


# --------------------------------------------------------------------------- #
# AC12 — a node whose file has an open blocker/bug is flagged in the overlay
# --------------------------------------------------------------------------- #


async def test_ac12_blocker_and_bug_flag_the_owning_nodes(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await context_service.add_entry(
            session,
            project=PROJECT,
            section="blockers",
            headline="Invoice rounding is wrong",
            linked_files=["services/billing/invoice.py"],
        )
        await context_service.add_entry(
            session,
            project=PROJECT,
            section="bugs",
            headline="Money loses precision",
            linked_files=["lib/money.py"],
        )
        top = await codemap_service.get_code_map(session, project=PROJECT)
        billing = await codemap_service.get_code_map(
            session, project=PROJECT, scope="services/billing"
        )

    assert top["overlay_legend"] == ["focus", "blockers", "bugs", "requirements"]
    nodes = {str(n["path"]): n for n in cast(list[dict[str, object]], top["nodes"])}

    services_overlay = cast(dict[str, object], nodes["services"]["overlay"])
    assert services_overlay["blockers"] == 1
    assert services_overlay["hot"] is True

    lib_overlay = cast(dict[str, object], nodes["lib"]["overlay"])
    assert lib_overlay["bugs"] == 1
    assert lib_overlay["hot"] is True

    # README.md carries nothing.
    assert cast(dict[str, object], nodes["README.md"]["overlay"])["hot"] is False

    # Drilling in: the file node itself is flagged.
    invoice = next(
        n
        for n in cast(list[dict[str, object]], billing["nodes"])
        if n["path"] == "services/billing/invoice.py"
    )
    invoice_overlay = cast(dict[str, object], invoice["overlay"])
    assert invoice_overlay["blockers"] == 1
    assert invoice_overlay["hot"] is True


async def test_overlay_picks_up_current_focus_paths(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        await context_service.set_current_focus(
            session, project=PROJECT, text="Refactor `services/api/routes.py` for async handlers"
        )
        top = await codemap_service.get_code_map(session, project=PROJECT)
    services = next(
        n for n in cast(list[dict[str, object]], top["nodes"]) if n["path"] == "services"
    )
    assert cast(dict[str, object], services["overlay"])["focus"] == 1


# --------------------------------------------------------------------------- #
# AC20 + scales — default depth is the top tier only; expansion stays cheap
# --------------------------------------------------------------------------- #


def _wide_deep_repo(root: Path, *, packages: int, subpackages: int, files: int) -> int:
    total = 0
    for p in range(packages):
        for s in range(subpackages):
            pkg = root / f"pkg{p:02d}" / f"sub{s}"
            pkg.mkdir(parents=True)
            for f in range(files):
                # every file imports pkg00.sub0.mod0 → cross-package edges at the top tier
                body = (
                    f"from pkg00.sub0.mod0 import base\n\ndef fn_{p}_{s}_{f}():\n    return base\n"
                )
                (pkg / f"mod{f}.py").write_text(body, encoding="utf-8")
                total += 1
    (root / "pkg00" / "sub0" / "mod0.py").write_text("base = 1\n", encoding="utf-8")
    return total


async def test_ac20_default_is_top_tier_only_and_expansion_is_scoped(tmp_path: Path) -> None:
    file_count = _wide_deep_repo(tmp_path, packages=12, subpackages=4, files=5)
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(tmp_path), overview=OVERVIEW
        )
    async with session_scope() as session:
        await index_service.reindex(session, project=PROJECT, incremental=False)

    async with session_scope() as session:
        default = await codemap_service.get_code_map(session, project=PROJECT)
        expanded = await codemap_service.get_code_map(session, project=PROJECT, scope="pkg03")

    default_nodes = cast(list[dict[str, object]], default["nodes"])
    stats = cast(dict[str, object], default["stats"])
    # The repo has hundreds of files but the default response is ~12 nodes.
    assert cast(int, stats["total_files"]) == file_count
    assert len(default_nodes) <= 15
    # Top tier only: no node path descends below the first segment.
    assert all("/" not in str(n["path"]) for n in default_nodes)
    # Aggregated cross-package edges are present (pkg03 -> pkg00, etc.).
    pairs = _edge_pairs(cast(list[dict[str, object]], default["edges"]))
    assert ("dir:pkg03", "dir:pkg00") in pairs
    # The default payload is small regardless of repo size (D9 / AC20).
    assert len(json.dumps(default)) < 20_000

    expanded_nodes = cast(list[dict[str, object]], expanded["nodes"])
    inside = _paths(expanded_nodes, inside_only=True)
    assert inside == {"pkg03/sub0", "pkg03/sub1", "pkg03/sub2", "pkg03/sub3"}
    # Expanding pkg03 does not carry pkg01/pkg02/... nodes.
    assert not any(str(n["path"]).startswith("pkg01") for n in expanded_nodes)
    assert len(json.dumps(expanded)) < 20_000


async def test_depth_is_clamped(tmp_path: Path) -> None:
    _wide_deep_repo(tmp_path, packages=3, subpackages=2, files=2)
    async with session_scope() as session:
        await context_service.register_project(
            session, name=PROJECT, root_path=str(tmp_path), overview=OVERVIEW
        )
    async with session_scope() as session:
        await index_service.reindex(session, project=PROJECT, incremental=False)
    async with session_scope() as session:
        deep = await codemap_service.get_code_map(session, project=PROJECT, depth=99)
    assert deep["depth"] == codemap_service.MAX_DEPTH


async def test_bad_scope_is_rejected(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)
    async with session_scope() as session:
        with pytest.raises(ValueError):
            await codemap_service.get_code_map(session, project=PROJECT, scope="../etc")
        with pytest.raises(ValueError):
            await codemap_service.get_code_map(session, project=PROJECT, scope="no/such/dir")


# --------------------------------------------------------------------------- #
# Surface — MCP tool, resource, HTTP route
# --------------------------------------------------------------------------- #


def _tool_payload(result: object) -> dict[str, object]:
    if isinstance(result, tuple):
        _, structured = result
        if isinstance(structured, dict):
            return {str(k): v for k, v in cast(dict[object, object], structured).items()}
    text_val = result
    if isinstance(result, list) and result:
        text_val = getattr(result[0], "text", result[0])
    data: object = json.loads(str(text_val))
    assert isinstance(data, dict)
    return {str(k): v for k, v in cast(dict[object, object], data).items()}


async def test_get_code_map_tool_and_resource(tmp_path: Path) -> None:
    await _register_and_index(tmp_path)

    payload = _tool_payload(await mcp.call_tool("get_code_map", {"project": PROJECT}))
    nodes = cast(list[dict[str, object]], payload["nodes"])
    assert {str(n["path"]) for n in nodes} >= {"services", "lib"}

    contents = list(await mcp.read_resource(f"context://{PROJECT}/code-map"))
    body = json.loads(str(contents[0].content))
    assert body["project_name"] == PROJECT
    assert body["scope"] is None


def test_code_map_http_route_is_registered() -> None:
    app = build_http_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/projects/{project}/code-map" in paths
