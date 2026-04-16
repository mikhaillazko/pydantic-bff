"""Tests for ``populate_context_with_batch`` — Phase 1 "Plan" of Plan/Fetch/Merge."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from pydantic_bff.transformer.batcher import populate_context_with_batch
from pydantic_bff.transformer.decorators import bff_model
from pydantic_bff.transformer.registry import TransformerRegistry
from pydantic_bff.transformer.registry import build_transform_annotated
from pydantic_bff.transformer.types import BatchArg


@dataclass(frozen=True)
class User:
    id: int
    name: str


UserId = int


def test_populate_context_collects_scalar_ids(noop_injector) -> None:
    transformer = TransformerRegistry(injector=noop_injector)

    @transformer
    def transform_user(user_id: UserId, batch: BatchArg[UserId]) -> User:
        return User(id=user_id, name='')

    UserTransformerAnnotated = build_transform_annotated(transform_user)

    @bff_model
    class Row(BaseModel):
        owner: UserTransformerAnnotated

    batch_key = Row.__batches__[0].key  # type: ignore[attr-defined]
    rows: list[dict[str, Any]] = [{'owner': 1}, {'owner': 2}, {'owner': 2}]

    context = populate_context_with_batch(Row, rows)

    assert context == {batch_key: {1, 2}}


def test_populate_context_collects_iterable_ids_and_skips_none(noop_injector) -> None:
    transformer = TransformerRegistry(injector=noop_injector)

    @transformer
    def transform_user(user_id: UserId, batch: BatchArg[UserId]) -> list[User]:
        return []

    UsersTransformerAnnotated = build_transform_annotated(transform_user)

    @bff_model
    class Row(BaseModel):
        owners: UsersTransformerAnnotated

    batch_key = Row.__batches__[0].key  # type: ignore[attr-defined]
    rows: list[dict[str, Any]] = [{'owners': [1, 2, None]}, {'owners': [2, 3]}, {'owners': None}]

    context = populate_context_with_batch(Row, rows)

    assert context == {batch_key: {1, 2, 3}}


def test_populate_context_returns_empty_for_model_without_batches() -> None:
    @bff_model
    class Row(BaseModel):
        id: int

    context = populate_context_with_batch(Row, [{'id': 1}, {'id': 2}])
    assert context == {}


def test_populate_context_works_without_bff_model_decorator(noop_injector) -> None:
    """Lazy introspection: omitting @bff_model still works."""
    transformer = TransformerRegistry(injector=noop_injector)

    @transformer
    def transform_user(user_id: UserId, batch: BatchArg[UserId]) -> User:
        return User(id=user_id, name='')

    UserTransformerAnnotated = build_transform_annotated(transform_user)

    class Row(BaseModel):  # no @bff_model
        owner: UserTransformerAnnotated

    rows: list[dict[str, Any]] = [{'owner': 1}, {'owner': 2}]
    context = populate_context_with_batch(Row, rows)
    # one batch was discovered lazily
    assert len(context) == 1
    assert next(iter(context.values())) == {1, 2}
