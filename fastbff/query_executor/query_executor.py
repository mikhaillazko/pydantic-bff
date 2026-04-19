from collections.abc import Iterable

from fastbff.exceptions import QueryNotRegisteredError

from .query import Query
from .query_annotation import QueryAnnotation
from .query_cache import QueryCache


class QueryExecutor:
    """Per-request executor.

    :meth:`fetch` dispatches typed query objects with automatic caching:

    - Call-level for plain return types.
    - Entity-level for ``dict[K, V]`` queries with an IDs field:
      overlapping id sets share cached entries, only missing ids are
      fetched from the underlying query.
    """

    def __init__(self, query_annotations: dict[type, QueryAnnotation]) -> None:
        self._query_annotations = query_annotations
        self._cache = QueryCache()

    def fetch[T](self, query_obj: Query[T]) -> T:
        query_type = type(query_obj)
        annotation = self._query_annotations.get(query_type)
        if annotation is None:
            raise QueryNotRegisteredError(f'No @query registered for query object {query_type}')
        query_param_name = annotation.query_param_name
        if query_param_name is None:
            raise QueryNotRegisteredError(
                f'Query handler for {query_type.__name__!r} has no Query[T] parameter.',
            )

        if annotation.dict_type_key is not None:
            ids_field = annotation.ids_param_name
            if ids_field is not None:
                ids_value = getattr(query_obj, ids_field, None)
                if isinstance(ids_value, Iterable) and not isinstance(ids_value, (str, bytes)):
                    ids = frozenset(ids_value)
                    bucket_key = self._cache.build_key(annotation.call, {}, annotation.dict_value_type)
                    result = self._cache.get_or_fetch_entities(
                        bucket_key,
                        ids,
                        lambda missing: annotation.call(
                            **{query_param_name: query_obj.model_copy(update={ids_field: missing})},
                        ),
                    )
                    return result  # type: ignore[return-value]

        cache_key = self._cache.build_key(
            annotation.call,
            dict(query_obj),
            annotation.dict_value_type if annotation.dict_type_key is not None else None,
        )
        return self._cache.get_or_call(cache_key, lambda: annotation.call(**{query_param_name: query_obj}))
