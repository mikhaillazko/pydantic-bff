"""Tests for ``@bff_model`` and lazy model introspection."""

from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from pydantic_bff.transformer.batcher import get_model_batches
from pydantic_bff.transformer.decorators import bff_model
from pydantic_bff.transformer.inspection import introspect_model_transformers
from pydantic_bff.transformer.registry import TransformerRegistry
from pydantic_bff.transformer.registry import build_transform_annotated
from pydantic_bff.transformer.types import _BATCHES_ATTR
from pydantic_bff.transformer.types import BatchArg
from pydantic_bff.transformer.types import BatchInfo


@dataclass(frozen=True)
class User:
    id: int
    name: str


UserId = int


def test_bff_model_attaches_batches_when_transformer_field_present(noop_injector) -> None:
    transformer = TransformerRegistry(injector=noop_injector)

    @transformer
    def transform_user(user_id: UserId, batch: BatchArg[UserId]) -> User:
        return User(id=user_id, name='')

    UserTransformerAnnotated = build_transform_annotated(transform_user)

    @bff_model
    class TeamDTO(BaseModel):
        id: int
        owner: UserTransformerAnnotated

    batches = getattr(TeamDTO, _BATCHES_ATTR, [])
    assert len(batches) == 1
    assert isinstance(batches[0], BatchInfo)
    assert batches[0].field_name == 'owner'
    assert batches[0].batch_fetch_type == dict[UserId, User]


def test_bff_model_caches_empty_batches_for_plain_models() -> None:
    @bff_model
    class PlainDTO(BaseModel):
        id: int
        name: str

    assert getattr(PlainDTO, _BATCHES_ATTR, None) == []


def test_bff_model_rejects_non_basemodel() -> None:
    with pytest.raises(TypeError, match='Pydantic BaseModel'):

        @bff_model
        class NotAModel:
            pass


def test_introspect_model_transformers_is_idempotent(noop_injector) -> None:
    transformer = TransformerRegistry(injector=noop_injector)

    @transformer
    def transform_user(user_id: UserId, batch: BatchArg[UserId]) -> User:
        return User(id=user_id, name='')

    UserTransformerAnnotated = build_transform_annotated(transform_user)

    class DTO(BaseModel):
        owner: UserTransformerAnnotated

    introspect_model_transformers(DTO)
    first = list(DTO.__batches__)  # type: ignore[attr-defined]
    introspect_model_transformers(DTO)
    second = list(DTO.__batches__)  # type: ignore[attr-defined]
    assert [b.field_name for b in first] == [b.field_name for b in second]


def test_get_model_batches_introspects_lazily_without_bff_model(noop_injector) -> None:
    transformer = TransformerRegistry(injector=noop_injector)

    @transformer
    def transform_user(user_id: UserId, batch: BatchArg[UserId]) -> User:
        return User(id=user_id, name='')

    UserTransformerAnnotated = build_transform_annotated(transform_user)

    class DTO(BaseModel):  # no @bff_model
        owner: UserTransformerAnnotated

    assert not hasattr(DTO, _BATCHES_ATTR)
    batches = get_model_batches(DTO)
    assert len(batches) == 1
    assert batches[0].field_name == 'owner'
    # cached after first call
    assert getattr(DTO, _BATCHES_ATTR) is batches
