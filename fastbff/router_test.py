"""Tests for ``QueryRouter`` registration semantics and type checking."""

from dataclasses import dataclass

import pytest

from fastbff.exceptions import QueryRegistrationError
from fastbff.query_executor.query import Query


@dataclass(frozen=True)
class PlainResult:
    value: str


@dataclass(frozen=True)
class Entity:
    value: str


class FetchPlainQuery(Query[PlainResult]):
    key: str


def test_query_type_registered_in_app(app) -> None:
    # Arrange
    @app.queries
    def fetch_plain(query_args: FetchPlainQuery) -> PlainResult:
        return PlainResult(value=query_args.key)

    # Act
    annotation = app.get_annotation_by_query_type(FetchPlainQuery)

    # Assert
    assert annotation is not None
    assert annotation.query_type is FetchPlainQuery


def test_return_type_mismatch_raises(query_router) -> None:
    # Arrange & Act & Assert
    with pytest.raises(QueryRegistrationError, match='return type.*does not match'):

        @query_router.queries
        def fetch_plain(query_args: FetchPlainQuery) -> Entity:
            return Entity(value='wrong')
