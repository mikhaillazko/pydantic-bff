from collections.abc import Callable
from collections.abc import Iterator

import pytest

from fastbff import FastBFF
from fastbff.query_executor.query_executor import QueryExecutor
from fastbff.router import QueryRouter


class NoopInjector:
    """Pass functions through unchanged — for tests that don't exercise DI."""

    def inject(self, func: Callable) -> Callable:
        return func


@pytest.fixture()
def noop_injector() -> NoopInjector:
    return NoopInjector()


@pytest.fixture()
def app() -> Iterator[FastBFF]:
    fastbff_app = FastBFF()
    with fastbff_app._injector.dependency_context.init_context():
        yield fastbff_app


@pytest.fixture()
def query_router() -> QueryRouter:
    return QueryRouter()


@pytest.fixture()
def query_executor(app: FastBFF) -> QueryExecutor:
    return QueryExecutor(query_annotations=app._query_annotations)
