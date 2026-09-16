import pytest

from app.rag import vectorstore


def test_build_wiki_chunk_ids_are_revision_scoped():
    assert vectorstore.build_wiki_chunk_ids(
        page_id=4925,
        revision_id=37451,
        chunk_count=3,
    ) == [
        "wiki:4925:37451:0",
        "wiki:4925:37451:1",
        "wiki:4925:37451:2",
    ]


def test_replace_wiki_revision_writes_before_removing_old(monkeypatch):
    events = []

    def fake_delete(page_id, revision_id):
        events.append(("delete", page_id, revision_id))
        return 4 if revision_id == 9 else 0

    def fake_add(chunks, *, page_id, revision_id):
        events.append(("add", page_id, revision_id, len(chunks)))
        return len(chunks)

    monkeypatch.setattr(vectorstore, "delete_wiki_revision_chunks", fake_delete)
    monkeypatch.setattr(vectorstore, "add_wiki_revision_chunks", fake_add)

    added, removed = vectorstore.replace_wiki_revision_chunks(
        [object(), object()],
        page_id=1,
        revision_id=10,
        previous_revision_id=9,
    )

    assert added == 2
    assert removed == 4
    assert events == [
        ("delete", 1, 10),
        ("add", 1, 10, 2),
        ("delete", 1, 9),
    ]


def test_replace_wiki_revision_cleans_failed_target_and_keeps_old(monkeypatch):
    events = []

    def fake_delete(page_id, revision_id):
        events.append(("delete", page_id, revision_id))
        return 0

    def fail_add(_chunks, *, page_id, revision_id):
        events.append(("add", page_id, revision_id))
        raise RuntimeError("write failed")

    monkeypatch.setattr(vectorstore, "delete_wiki_revision_chunks", fake_delete)
    monkeypatch.setattr(vectorstore, "add_wiki_revision_chunks", fail_add)

    with pytest.raises(RuntimeError, match="write failed"):
        vectorstore.replace_wiki_revision_chunks(
            [object()],
            page_id=1,
            revision_id=10,
            previous_revision_id=9,
        )

    assert events == [
        ("delete", 1, 10),
        ("add", 1, 10),
        ("delete", 1, 10),
    ]


def test_replace_wiki_revision_rolls_back_new_when_old_delete_fails(monkeypatch):
    events = []

    def fake_delete(page_id, revision_id):
        events.append(("delete", page_id, revision_id))
        if revision_id == 9:
            raise RuntimeError("old delete failed")
        return 0

    def fake_add(chunks, *, page_id, revision_id):
        events.append(("add", page_id, revision_id, len(chunks)))
        return len(chunks)

    monkeypatch.setattr(vectorstore, "delete_wiki_revision_chunks", fake_delete)
    monkeypatch.setattr(vectorstore, "add_wiki_revision_chunks", fake_add)

    with pytest.raises(RuntimeError, match="old delete failed"):
        vectorstore.replace_wiki_revision_chunks(
            [object()],
            page_id=1,
            revision_id=10,
            previous_revision_id=9,
        )

    assert events == [
        ("delete", 1, 10),
        ("add", 1, 10, 1),
        ("delete", 1, 9),
        ("delete", 1, 10),
    ]
