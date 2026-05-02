"""Inheritance — transformer fields declared on a parent BaseModel must be
discovered when a subclass is the validation target.

Two layers we need to cover:

1. ``introspect_model_transformers`` must walk the MRO so that fields declared
   on the parent end up in the subclass's batches list. ``get_type_hints``
   already merges across the MRO, so this is implicit.
2. ``get_model_batches`` must not return the parent's cached
   ``__batches__`` when asked about the subclass. ``getattr(cls, ...)``
   walks the MRO, so if the parent was introspected first, the subclass
   would silently skip its own introspection.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel

from fastbff import BatchArg
from fastbff import FastBFF
from fastbff import Query
from fastbff import QueryExecutor
from fastbff import build_transform_annotated
from fastbff.transformer.batcher import get_model_batches
from fastbff.transformer.batcher import populate_context_with_batch


@dataclass(frozen=True)
class _User:
    id: int


def test_inherited_transformer_field_is_discovered_on_subclass() -> None:
    app = FastBFF()

    class FetchUsers(Query[dict[int, _User]]):
        ids: frozenset[int]

    @app.queries
    def fetch_users(args: FetchUsers) -> dict[int, _User]:
        return {i: _User(id=i) for i in args.ids}

    @app.transformer
    def transform_owner(
        owner_id: int,
        batch: BatchArg[int],
        query_executor: Annotated[QueryExecutor, Depends(QueryExecutor)],
    ) -> _User | None:
        return query_executor.fetch(FetchUsers(ids=batch.ids)).get(owner_id)

    OwnerTransformerAnnotated = build_transform_annotated(transform_owner)

    class BaseDTO(BaseModel):
        owner: OwnerTransformerAnnotated

    class TeamDTO(BaseDTO):
        id: int

    rows = [{'id': 1, 'owner': 10}, {'id': 2, 'owner': 20}, {'id': 3, 'owner': 10}]

    context = populate_context_with_batch(TeamDTO, rows)

    batches = get_model_batches(TeamDTO)
    assert len(batches) == 1, 'inherited transformer field should be discovered on TeamDTO'
    assert batches[0].field_name == 'owner'
    assert context == {batches[0].key: {10, 20}}


def test_subclass_introspection_not_short_circuited_by_parent_cache() -> None:
    """If the parent is introspected first, the subclass must still introspect itself.

    ``getattr(cls, '__batches__', None)`` would otherwise walk the MRO and
    return the parent's cached list — so the subclass's own batches would
    never be computed and any subclass-only transformer field would silently
    drop out of bulk fetching.
    """
    app = FastBFF()

    class FetchUsers(Query[dict[int, _User]]):
        ids: frozenset[int]

    @app.queries
    def fetch_users(args: FetchUsers) -> dict[int, _User]:
        return {i: _User(id=i) for i in args.ids}

    @app.transformer
    def transform_owner(
        owner_id: int,
        batch: BatchArg[int],
        query_executor: Annotated[QueryExecutor, Depends(QueryExecutor)],
    ) -> _User | None:
        return query_executor.fetch(FetchUsers(ids=batch.ids)).get(owner_id)

    @app.transformer
    def transform_admin(
        admin_id: int,
        batch: BatchArg[int],
        query_executor: Annotated[QueryExecutor, Depends(QueryExecutor)],
    ) -> _User | None:
        return query_executor.fetch(FetchUsers(ids=batch.ids)).get(admin_id)

    OwnerTransformerAnnotated = build_transform_annotated(transform_owner)
    AdminTransformerAnnotated = build_transform_annotated(transform_admin)

    class BaseDTO(BaseModel):
        owner: OwnerTransformerAnnotated

    class TeamDTO(BaseDTO):
        admin: AdminTransformerAnnotated

    # Trigger parent introspection first — Parent.__batches__ now lives on
    # the parent class, so Child's getattr() lookup would walk MRO and find
    # it without ever introspecting Child.
    parent_batches = get_model_batches(BaseDTO)
    assert len(parent_batches) == 1
    assert parent_batches[0].field_name == 'owner'

    child_batches = get_model_batches(TeamDTO)
    field_names = {batch.field_name for batch in child_batches}
    assert field_names == {'owner', 'admin'}, (
        f'subclass should see both inherited and own transformer fields, got {field_names}'
    )


def test_inherited_transformer_field_renders_through_entrypoint() -> None:
    """End-to-end: Plan/Fetch/Merge over a subclass with parent-declared transformer."""
    app = FastBFF()
    db_calls: list[frozenset[int]] = []

    class FetchUsers(Query[dict[int, _User]]):
        ids: frozenset[int]

    @app.queries
    def fetch_users(args: FetchUsers) -> dict[int, _User]:
        db_calls.append(args.ids)
        return {i: _User(id=i) for i in args.ids}

    @app.transformer
    def transform_owner(
        owner_id: int,
        batch: BatchArg[int],
        query_executor: Annotated[QueryExecutor, Depends(QueryExecutor)],
    ) -> _User | None:
        return query_executor.fetch(FetchUsers(ids=batch.ids)).get(owner_id)

    OwnerTransformerAnnotated = build_transform_annotated(transform_owner)

    class BaseDTO(BaseModel):
        owner: OwnerTransformerAnnotated

    class TeamDTO(BaseDTO):
        id: int

    class FetchTeams(Query[list[TeamDTO]]):
        pass

    @app.queries(FetchTeams)
    def fetch_teams() -> list[dict[str, int]]:
        return [{'id': 1, 'owner': 10}, {'id': 2, 'owner': 20}, {'id': 3, 'owner': 10}]

    @app.entrypoint
    def render_page(
        query_executor: Annotated[QueryExecutor, Depends(QueryExecutor)],
    ) -> list[TeamDTO]:
        return query_executor.fetch(FetchTeams())

    results = render_page()

    assert len(db_calls) == 1
    assert db_calls[0] == frozenset({10, 20})
    assert [row.owner for row in results] == [_User(id=10), _User(id=20), _User(id=10)]
