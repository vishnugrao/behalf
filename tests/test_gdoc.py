import pytest

from behalf.gdoc import Block, GoogleDocError, GoogleDocPublisher, build_requests, parse_markdown

PAGE = """# Pre-read — Atlas Q3

_Generated 2026-08-15_

## Decisions that already landed
- 17 March is firm against scope [atlas-launch]
- **SEC-2026-11** blocks GA

## Risks
- Batch three is the only thing that moves the date

> Not ratified by: Marco Silvestri.

<sub>Sourced from 9 live entries.</sub>
"""


def test_headings_and_bullets_are_recognised():
    blocks = parse_markdown(PAGE)
    assert blocks[0] == Block("Pre-read — Atlas Q3", "HEADING_1")
    assert Block("Decisions that already landed", "HEADING_2") in blocks
    bullets = [b for b in blocks if b.bullet]
    assert len(bullets) == 3
    assert bullets[0].text == "17 March is firm against scope [atlas-launch]"


def test_emphasis_and_html_are_stripped():
    text = " ".join(b.text for b in parse_markdown(PAGE))
    assert "**" not in text
    assert "<sub>" not in text
    assert "SEC-2026-11 blocks GA" in text


def test_blank_lines_do_not_become_paragraphs():
    assert all(b.text.strip() for b in parse_markdown(PAGE))


def test_existing_content_is_cleared_before_insert():
    requests = build_requests(parse_markdown("# Title"), end_index=500)
    assert requests[0]["deleteContentRange"]["range"] == {"startIndex": 1, "endIndex": 499}
    assert requests[1]["insertText"]["location"]["index"] == 1


def test_an_empty_document_is_not_cleared():
    requests = build_requests(parse_markdown("# Title"), end_index=1)
    assert "deleteContentRange" not in requests[0]


def test_paragraph_ranges_are_contiguous_and_cover_the_text():
    blocks = parse_markdown(PAGE)
    requests = build_requests(blocks, end_index=1)
    inserted = requests[0]["insertText"]["text"]

    styles = [r["updateParagraphStyle"] for r in requests if "updateParagraphStyle" in r]
    assert len(styles) == len(blocks)

    cursor = 1
    for block, request in zip(blocks, styles):
        span = request["range"]
        assert span["startIndex"] == cursor
        assert inserted[span["startIndex"] - 1 : span["endIndex"] - 1] == block.text + "\n"
        cursor = span["endIndex"]
    assert cursor == 1 + len(inserted)


def test_bullets_are_applied_only_to_bullet_lines():
    blocks = parse_markdown(PAGE)
    requests = build_requests(blocks, end_index=1)
    bullet_requests = [r for r in requests if "createParagraphBullets" in r]
    assert len(bullet_requests) == sum(1 for b in blocks if b.bullet)


def test_missing_credentials_is_a_clear_error(tmp_path):
    publisher = GoogleDocPublisher(
        state_dir=tmp_path, title="t", client_id="", client_secret=""
    )
    with pytest.raises(GoogleDocError, match="GOOGLE_OAUTH_CLIENT_ID"):
        publisher.credentials()


def test_document_id_is_remembered_between_runs(tmp_path):
    first = GoogleDocPublisher(state_dir=tmp_path, title="t", client_id="a", client_secret="b")
    first.document_id = "doc-123"
    first.remember()

    second = GoogleDocPublisher(state_dir=tmp_path, title="t", client_id="a", client_secret="b")
    assert second.recall() == "doc-123"
    assert second.url().endswith("/doc-123/edit")
