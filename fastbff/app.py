"""Top-level :class:`FastBFF` app — owns the DI injector, a :class:`QueryRouter`
carrier, and the query-type lookup table consulted by :class:`QueryExecutor`.

Mirrors FastAPI's ``app = FastAPI(); app.include_router(router)`` ergonomics so
multi-module projects can register handlers locally and merge them into a
single composition root.
"""

from collections.abc import Callable
from typing import Any

from .exceptions import QueryNotRegisteredError
from .exceptions import QueryRegistrationError
from .injections.registry import InjectorRegistry
from .query_executor.query_annotation import QueryAnnotation
from .query_executor.query_executor import QueryExecutor
from .router import QueryRouter


class FastBFF:
    """Composition root for a fastbff application.

    Owns an :class:`InjectorRegistry` and a :class:`QueryRouter` carrier.
    ``@app.queries`` / ``@app.transformer`` register on the router and then
    upgrade the stored ``call`` to an injector-wrapped callable so ``Depends``
    parameters resolve through the app's DI graph::

        app = FastBFF()

        @app.queries
        def fetch_users(args: FetchUsers) -> dict[int, User]: ...

        @app.transformer
        def transform_owner(...): ...

        # ...or stage in a router and merge later:
        app.include_router(router)

        results = validate_batch(TeamDTO, rows)
    """

    def __init__(self) -> None:
        self._injector = InjectorRegistry()
        self._router = QueryRouter()
        self._query_annotations: dict[type, QueryAnnotation] = {}
        self._injector.bind(QueryExecutor, lambda: QueryExecutor(query_annotations=self._query_annotations))

    def queries[F: Callable](self, func: F) -> F:
        """Register *func* as a ``@query`` handler, wrapping it with the app's injector."""
        self._router.queries(func)
        annotation = self._router._query_func_annotations_registry[func]
        annotation.call = self._injector.inject(func)
        if annotation.query_type is not None:
            if annotation.query_type in self._query_annotations:
                raise QueryRegistrationError(
                    f'Duplicate @queries registration for query type {annotation.query_type.__name__!r}.',
                )
            self._query_annotations[annotation.query_type] = annotation
        return func

    def transformer[F: Callable](self, func: F) -> F:
        """Register *func* as a ``@transformer``, wrapping it with the app's injector."""
        self._router.transformer(func)
        self._router._transformer_func_annotation_registry[func].call = self._injector.inject(func)
        return func

    @property
    def router(self) -> QueryRouter:
        """The app's underlying :class:`QueryRouter` (query + transformer storage)."""
        return self._router

    def bind(self, target: Any, factory: Callable[..., Any]) -> None:
        """Shortcut for :meth:`InjectorRegistry.bind` against the app's injector."""
        self._injector.bind(target, factory)

    def entrypoint[F: Callable](self, func: F) -> F:
        """Shortcut for :meth:`InjectorRegistry.entrypoint` against the app's injector."""
        return self._injector.entrypoint(func)  # type: ignore[return-value]

    def get_annotation_by_query_type(self, query_type: type) -> QueryAnnotation:
        annotation = self._query_annotations.get(query_type)
        if annotation is not None:
            return annotation
        raise QueryNotRegisteredError(f'No @query registered for query object {query_type}')

    def include_router(self, router: QueryRouter) -> None:
        """Merge *router*'s registrations into this app.

        Upgrades each stored ``QueryAnnotation.call`` / ``TransformerAnnotation.call``
        to an injector-wrapped callable in-place, so any references captured
        before include (e.g. via :func:`build_transform_annotated`) pick up
        the app's DI resolution automatically.

        Raises :class:`QueryRegistrationError` on duplicate registration of the
        same :class:`Query` subclass or function.
        """
        for func, annotation in router._query_func_annotations_registry.items():
            if func in self._router._query_func_annotations_registry:
                raise QueryRegistrationError(
                    f'Duplicate @queries registration for function {func.__name__!r} '
                    f'when including router into FastBFF app.',
                )
            if annotation.query_type is not None:
                if annotation.query_type in self._query_annotations:
                    raise QueryRegistrationError(
                        f'Duplicate @queries registration for query type {annotation.query_type.__name__!r} '
                        f'when including router into FastBFF app.',
                    )
                self._query_annotations[annotation.query_type] = annotation
            annotation.call = self._injector.inject(func)
            self._router._query_func_annotations_registry[func] = annotation

        for func, transformer_annotation in router._transformer_func_annotation_registry.items():
            transformer_annotation.call = self._injector.inject(func)
            self._router._transformer_func_annotation_registry[func] = transformer_annotation
