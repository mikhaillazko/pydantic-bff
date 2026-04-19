from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .dependant import Dependant
from .reflection import get_dependency_callable

DependencyConfiguration = dict[Callable[..., Any], Callable[..., Any]]


class DependencyProvider:
    dependency_overrides: DependencyConfiguration

    def __init__(self) -> None:
        self.dependency_overrides = {}

    def get_dependant_impl(self, original: Callable[..., Any]) -> Dependant:
        call = get_dependency_callable(original)
        if call in self.dependency_overrides:
            call = self.dependency_overrides[call]
        return Dependant(call=call)

    @contextmanager
    def override(
        self,
        original: Callable[..., Any],
        override: Callable[..., Any],
    ) -> Iterator[None]:
        original_call = get_dependency_callable(original)
        source = self.dependency_overrides.get(original_call)
        self.dependency_overrides[original_call] = override
        yield
        if source is not None:
            self.dependency_overrides[original_call] = source
        else:
            self.dependency_overrides.pop(original_call, None)
