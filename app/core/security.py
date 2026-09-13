"""Authorization extension points for retrieval endpoints."""


async def get_allowed_document_ids() -> set[str] | None:
    """Return document IDs the authenticated caller may access.

    Authentication is not implemented yet, so ``None`` currently means no
    server-side restriction. A future auth provider can replace this FastAPI
    dependency without changing the retriever or API contracts.
    """

    return None
