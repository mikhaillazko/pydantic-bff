"""Carrier for pending query / transformer registrations.

A :class:`QueryRouter` gathers functions with their type metadata. When the
router is merged into a :class:`FastBFF` app via :meth:`FastBFF.include_router`,
its registrations become part of the union of handlers scanned by
:meth:`FastBFF.finalize` to synthesize the ``provide_query_executor`` factory.
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

    """

    def __init__(self) -> None:
        self._query_func_annotations_registry: dict[Callable, QueryAnnotation] = {}
        self._transformer_func_annotation_registry: dict[Callable, TransformerAnnotation] = {}

    def queries[F: Callable](self, func: F) -> F:
        """Register *func* as a ``@query`` handler on this router."""
        annotation = QueryAnnotation(original_func=func)
        self._query_func_annotations_registry[func] = annotation
        return func

    def transformer[F: Callable](self, func: F) -> F:
        """Register *func* as a ``@transformer`` handler on this router."""
        transformer_annotation = TransformerAnnotation(original_func=func)
        setattr(func, _TRANSFORMER_ANNOTATION_ATTR, transformer_annotation)
        self._transformer_func_annotation_registry[func] = transformer_annotation
        return func
