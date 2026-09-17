from app.commands.sample_chunks import build_parser, sample_chunks


class FakeCollection:
    def __init__(self, name, rows):
        self.name = name
        self.rows = rows
        self.calls = []

    def get(self, *, ids=None, include=None, where=None):
        self.calls.append({"ids": ids, "include": include, "where": where})
        rows = self.rows
        if ids is not None:
            rows = [row for row in rows if row["id"] in ids]
        if where is not None:
            rows = [
                row
                for row in rows
                if all(row["metadata"].get(key) == value for key, value in where.items())
            ]
        return {
            "ids": [row["id"] for row in rows],
            "documents": (
                [row["document"] for row in rows]
                if "documents" in (include or [])
                else None
            ),
            "metadatas": (
                [row["metadata"] for row in rows]
                if "metadatas" in (include or [])
                else None
            ),
        }


class FakeClient:
    def __init__(self, collections):
        self.collections = collections

    def list_collections(self):
        return self.collections


def make_collection():
    return FakeCollection(
        "langchain",
        [
            {
                "id": "wiki:1:10:0",
                "document": "电解器切块一",
                "metadata": {"title": "电解器", "chunk_index": 0},
            },
            {
                "id": "wiki:1:10:1",
                "document": "电解器切块二",
                "metadata": {"title": "电解器", "chunk_index": 1},
            },
            {
                "id": "wiki:2:20:0",
                "document": "哈奇切块",
                "metadata": {"title": "好吃哈奇", "chunk_index": 0},
            },
        ],
    )


def test_sample_chunks_is_reproducible_and_loads_only_selected_documents():
    first_collection = make_collection()
    second_collection = make_collection()

    first = sample_chunks(
        count=2,
        seed=2026,
        client=FakeClient([first_collection]),
    )
    second = sample_chunks(
        count=2,
        seed=2026,
        client=FakeClient([second_collection]),
    )

    assert [sample.chunk_id for sample in first.samples] == [
        sample.chunk_id for sample in second.samples
    ]
    assert first.eligible_count == 3
    assert first_collection.calls[0]["include"] == []
    assert first_collection.calls[1]["include"] == ["documents", "metadatas"]
    assert len(first_collection.calls[1]["ids"]) == 2


def test_sample_chunks_can_filter_by_title():
    result = sample_chunks(
        count=10,
        seed=1,
        title="电解器",
        client=FakeClient([make_collection()]),
    )

    assert result.eligible_count == 2
    assert len(result.samples) == 2
    assert {sample.metadata["title"] for sample in result.samples} == {"电解器"}


def test_sample_chunks_can_select_collection():
    wiki = make_collection()
    other = FakeCollection(
        "other",
        [
            {
                "id": "other:0",
                "document": "其他切块",
                "metadata": {"title": "其他"},
            }
        ],
    )

    result = sample_chunks(
        count=5,
        seed=1,
        collection_name="other",
        client=FakeClient([wiki, other]),
    )

    assert result.eligible_count == 1
    assert result.samples[0].collection == "other"


def test_sample_chunks_parser_accepts_quality_inspection_options():
    args = build_parser().parse_args(
        [
            "--count",
            "8",
            "--seed",
            "42",
            "--collection",
            "langchain",
            "--title",
            "电解器",
        ]
    )

    assert args.count == 8
    assert args.seed == 42
    assert args.collection == "langchain"
    assert args.title == "电解器"
