"""Unit tests for the requirements-file parser + surgical serialiser (FR16a).

No database — pure text round-trips.
"""

from __future__ import annotations

from pcs.requirements.parser import parse_requirements
from pcs.requirements.template import LineEdit, render_heading, render_token, serialise
from pcs.requirements.types import ManagedToken

SAMPLE = """\
# Requirements

Intro prose that must be preserved verbatim.

### R-001 — First requirement
<!-- req status=in-progress files=src/a.py,src/b.py blocker=uuid-1 -->
Body of the first requirement.
Second line of prose.

### R-002 — Second requirement
<!-- req status=done -->
It is finished.
"""


def test_parse_basic_blocks() -> None:
    parsed = parse_requirements(SAMPLE)
    assert not parsed.fatal_errors
    assert [b.req_key for b in parsed.blocks] == ["R-001", "R-002"]
    first = parsed.blocks[0]
    assert first.title == "First requirement"
    assert first.status == "in-progress"
    assert first.token is not None
    assert first.token.files == ("src/a.py", "src/b.py")
    assert first.token.blocker == "uuid-1"
    assert "Second line of prose." in first.prose
    assert parsed.blocks[1].status == "done"


def test_roundtrip_with_no_edits_is_byte_identical() -> None:
    parsed = parse_requirements(SAMPLE)
    assert serialise(parsed, [], []) == SAMPLE


def test_missing_metadata_line_means_not_started() -> None:
    parsed = parse_requirements("### R-009 — No token\nJust some prose.\n")
    assert parsed.blocks[0].token is None
    assert parsed.blocks[0].status == "not-started"


def test_heading_without_id_is_a_new_block() -> None:
    parsed = parse_requirements("### Brand new idea\nProse.\n")
    assert parsed.blocks[0].req_key is None
    assert parsed.blocks[0].title == "Brand new idea"


def test_malformed_token_is_a_block_error_not_fatal() -> None:
    parsed = parse_requirements("### R-001 — X\n<!-- req status=bogus -->\nprose\n")
    assert parsed.fatal_errors == []
    assert parsed.blocks[0].error is not None
    assert "bogus" in parsed.blocks[0].error


def test_duplicate_id_is_a_fatal_error() -> None:
    text = "### R-001 — A\n<!-- req status=done -->\n\n### R-001 — B\n<!-- req status=done -->\n"
    parsed = parse_requirements(text)
    assert parsed.fatal_errors


def test_token_rewrite_does_not_touch_prose() -> None:
    parsed = parse_requirements(SAMPLE)
    block = parsed.blocks[1]
    assert block.token_line is not None
    edit = LineEdit(block.token_line, render_token(ManagedToken(status="blocked")))
    out = serialise(parsed, [edit], [])
    assert "<!-- req status=blocked -->" in out
    assert "Body of the first requirement." in out
    assert out.count("### R-") == 2
    assert "Intro prose that must be preserved verbatim." in out


def test_heading_id_written_back_for_a_new_block() -> None:
    parsed = parse_requirements("### Add rate limiting\nWe need it.\n")
    block = parsed.blocks[0]
    edit = LineEdit(block.heading_line, render_heading("R-042", block.title))
    token = LineEdit(
        block.heading_line + 1, render_token(ManagedToken(status="not-started")), insert=True
    )
    out = serialise(parsed, [edit, token], [])
    assert out.startswith(
        "### R-042 — Add rate limiting\n<!-- req status=not-started -->\nWe need it.\n"
    )


def test_render_token_orders_and_omits_fields() -> None:
    assert render_token(ManagedToken(status="done")) == "<!-- req status=done -->"
    assert (
        render_token(ManagedToken(status="blocked", files=("a", "b"), blocker="x"))
        == "<!-- req status=blocked files=a,b blocker=x -->"
    )
