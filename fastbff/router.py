"""Carrier for pending query / transformer registrations.

A :class:`QueryRouter` gathers functions with their type metadata but does
*not* wrap them with any DI injector. Wrapping is deferred until the router
is merged into a :class:`FastBFF` app via :meth:`FastBFF.include_router`
(external routers) or handled inline by ``@app.queries`` / ``@app.transformer``
on an app that owns its own :class:`QueryRouter`.
"""

from collections.abc import Callable

from .query_executor.query_annotation import QueryAnnotation
from .transformer.types import _TRANSFORMER_ANNOTATION_ATTR
from .transformer.types import TransformerAnnotation


class QueryRouter:
    """A bundle of query and transformer registrations not yet attached to an app.

    Use ``@router.queries`` and ``@router.transformer`` exactly like the
    decorators on a :class:`FastBFF` app. Pass the router to
    :meth:`FastBFF.include_router` to merge its registrations into the app::

        router = QueryRouter()

        @router.queries
        def fetch_users(args: FetchUsers) -> dict[int, User]: ...

        @router.transformer
        def transform_owner(
            owner_id: int,
            batch: BatchArg[int],
            query_executor: Annotated[QueryExecutor, Depends(QueryExecutor)],
        ) -> User | None: ...

        app = FastBFF()
        app.include_router(router)

    Stored ``QueryAnnotation.call`` / ``TransformerAnnotation.call`` initially
    point at the raw function. :meth:`FastBFF.include_router` replaces them
    with injector-wrapped calls in-place, so any already-captured references
    (e.g. in ``Annotated[...]`` aliases returned by
    :func:`build_transform_annotated`) automatically pick up the app's DI
    resolution once included.
    """

    def __init__(self) -> None:
        self._query_func_annotations_registry: dict[Callable, QueryAnnotation] = {}
        self._transformer_func_annotation_registry: dict[Callable, TransformerAnnotation] = {}

    def queries[F: Callable](self, func: F) -> F:
        """Register *func* as a ``@query`` handler on this router."""
        annotation = QueryAnnotation(call=func, original_func=func)
        self._query_func_annotations_registry[func] = annotation
        return func

    def transformer[F: Callable](self, func: F) -> F:
        """Register *func* as a ``@transformer`` handler on this router."""
        transformer_annotation = TransformerAnnotation(original_func=func, wrapped_call=func)
        setattr(func, _TRANSFORMER_ANNOTATION_ATTR, transformer_annotation)
        self._transformer_func_annotation_registry[func] = transformer_annotation
        return func
