from dataclasses import replace

import pytest

from behalf.config import Config
from behalf.ledger import load_entries
from behalf.store import ContextStore

ENTRY = """---
id: {id}
title: {title}
kind: note
owner: tester
status: active
tags: []
confidence: 0.8
valid_from: '2026-01-01'
updated_at: '2026-01-01T00:00:00+00:00'
source: manual
---

{body}
"""


@pytest.fixture
def cfg(tmp_path):
    ledger = tmp_path / "ledger"
    (ledger / "notes").mkdir(parents=True)
    (ledger / "notes" / "a.md").write_text(
        ENTRY.format(id="launch", title="Launch is 17 March",
                     body="GA slipped from 3 March because tenant isolation was late.")
    )
    (ledger / "notes" / "b.md").write_text(
        ENTRY.format(id="renewal", title="Northwind renews in April",
                     body="Northwind is worth 840k and renews on 30 April.")
    )
    return replace(Config(), ledger_dir=ledger, state_dir=tmp_path / "state",
                   out_dir=tmp_path / "out", embedder="hashing")


def test_index_covers_every_entry(cfg):
    store = ContextStore(cfg)
    assert store.stats()["entries"] == 2
    store.close()


def test_search_finds_the_right_entry(cfg):
    store = ContextStore(cfg)
    assert store.search("when does Northwind renew")[0].entry.id == "renewal"
    assert store.search("why did the launch slip")[0].entry.id == "launch"
    store.close()


def test_update_supersedes_instead_of_overwriting(cfg):
    store = ContextStore(cfg)
    store.write(entry_id="launch", title="Launch is 24 March",
                body="Slipped again after batch three.", owner="tester")

    live = {e.id for e in store.live}
    assert "launch" in live and "launch@1" not in live

    chain = store.history("launch")
    assert [e.id for e in chain] == ["launch", "launch@1"]
    assert chain[1].status == "superseded"
    assert "17 March" in chain[1].title

    assert any(e["type"] == "update" for e in store.events())
    store.close()


def test_superseded_entries_are_excluded_from_search(cfg):
    store = ContextStore(cfg)
    store.write(entry_id="launch", title="Launch is 24 March",
                body="Slipped again after batch three.", owner="tester")

    live_ids = {r.entry.id for r in store.search("launch date", k=5)}
    assert "launch@1" not in live_ids
    all_ids = {r.entry.id for r in store.search("launch date", k=5, include_superseded=True)}
    assert "launch@1" in all_ids
    store.close()


def test_reindex_is_incremental(cfg):
    store = ContextStore(cfg)
    assert store.reload()["reembedded"] == 0
    (cfg.ledger_dir / "notes" / "b.md").write_text(
        ENTRY.format(id="renewal", title="Northwind renews in April",
                     body="Northwind is worth 900k and renews on 30 April.")
    )
    assert store.reload()["reembedded"] == 1
    store.close()


def test_duplicate_ids_are_rejected(cfg):
    (cfg.ledger_dir / "notes" / "c.md").write_text(
        ENTRY.format(id="launch", title="Duplicate", body="clash")
    )
    with pytest.raises(ValueError, match="duplicate entry ids"):
        load_entries(cfg.ledger_dir)
