import types as builtin_types
from collections.abc import Callable
from collections.abc import Iterable
from typing import Any
from typing import TypeGuard
from typing import Union
from typing import get_args
from typing import get_origin
from typing import get_type_hints

from fastbff.exceptions import QueryRegistrationError

from .query import Query


def _strip_none(t: Any) -> Any:
    """Remove NoneType from a simple Optional/Union for stable cache key construction."""
    origin = get_origin(t)
    if origin is Union or isinstance(t, builtin_types.UnionType):
        non_none = [a for a in get_args(t) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return t


def _find_ids_param(hints: dict[str, Any], key_type: type) -> str | None:
    """Find the parameter typed as ``Iterable[K]`` matching the dict's key type."""
    for param_name, param_type in hints.items():
        if param_name == 'return':
            continue
        origin = get_origin(param_type)
        if origin is not None:
            try:
                if issubclass(origin, Iterable):
                    args = get_args(param_type)
                    if args and args[0] == key_type:
                        return param_name
            except TypeError:
                continue
    return None


def _is_query_subclass(annotation: Any) -> TypeGuard[type[Query]]:
    """Check whether *annotation* is a concrete subclass of :class:`Query`."""
    try:
        return isinstance(annotation, type) and issubclass(annotation, Query) and annotation is not Query
    except TypeError:
        return False


def extract_query_return_type(query_cls: type) -> Any | None:
    """Extract ``T`` from ``Query[T]`` via ``__query_return_type__`` set at class definition time."""
    return getattr(query_cls, '__query_return_type__', None)


def _is_row_shaped(t: Any) -> bool:
    """Whether *t* is a 'rows' shape: ``list[Mapping]``, ``Mapping``, or close.

    The auto-wrap path lets a handler honestly declare ``-> list[dict[str, Any]]``
    (or single ``Mapping``) and have the framework validate to ``Query[T].T``
    at dispatch time. Anything else has to match ``Query[T].T`` exactly so
    genuine model-mismatch bugs (handler returns ``Entity`` while query says
    ``PlainResult``) still fail at registration.
    """
    import collections.abc as collections_abc

    if t is dict or t is collections_abc.Mapping:
        return True
    origin = get_origin(t)
    if origin is dict or origin is collections_abc.Mapping:
        return True
    if origin is list:
        args = get_args(t)
        if not args:
            return False
        return _is_row_shaped(args[0])
    return isinstance(t, type) and issubclass(t, collections_abc.Mapping)


def _find_ids_field_on_query(query_cls: type, key_type: type) -> str | None:
    """Find a field on the query class typed as ``Iterable[K]`` matching the dict's key type."""
    for field_name, field_info in query_cls.model_fields.items():  # type: ignore[attr-defined]
        field_type = field_info.annotation
        if field_type is None:
            continue
        origin = get_origin(field_type)
        if origin is not None:
            try:
                if issubclass(origin, Iterable):
                    args = get_args(field_type)
                    if args and args[0] == key_type:
                        return field_name
            except TypeError:
                continue
    return None


class QueryAnnotation:
    """Metadata gathered once when a ``@query`` function is registered.

    Stores the injected callable and all derived type metadata so that
    lookups in :class:`QueryExecutor` need no further reflection.
    """

    def __init__(self, original_func: Callable, explicit_query_type: type[Query] | None = None) -> None:
        self.original_func = original_func
        hints = get_type_hints(original_func)
        return_type = hints.get('return')
        if return_type is None:
            raise QueryRegistrationError(
                f'@query {original_func.__name__!r}: handler must declare a return type annotation.',
            )
        self.return_type: type = return_type

        # Detect Query[T] parameter; an explicit_query_type from the decorator
        # (``@queries(SomeQueryType)``) covers parameterless handlers that
        # still need a query-type binding.
        self.query_type: type | None = explicit_query_type
        self.query_param_name: str | None = None
        for param_name, param_type in hints.items():
            if param_name == 'return':
                continue
            if _is_query_subclass(param_type):
                if self.query_param_name is not None:
                    raise QueryRegistrationError(
                        f'@query {original_func.__name__}: multiple Query parameters '
                        f'({self.query_param_name}: {self.query_type.__name__ if self.query_type else "?"}, '
                        f'{param_name}: {param_type.__name__})',
                    )
                if explicit_query_type is not None and explicit_query_type is not param_type:
                    raise QueryRegistrationError(
                        f'@query {original_func.__name__}: explicit query type '
                        f'{explicit_query_type.__name__} does not match signature parameter '
                        f'{param_name}: {param_type.__name__}',
                    )
                self.query_type = param_type
                self.query_param_name = param_name

        if self.query_type is not None:
            expected_return = extract_query_return_type(self.query_type)
            if (
                expected_return is not None
                and self.return_type != expected_return
                and not _is_row_shaped(self.return_type)
            ):
                raise QueryRegistrationError(
                    f'@query {original_func.__name__}: return type {self.return_type} '
                    f'does not match {self.query_type.__name__}[{expected_return}]',
                )

        # Pre-compute dict[K, V] metadata; None if return type is not a dict.
        self.dict_value_type: Any = None
        self.dict_type_key: tuple[type, Any] | None = None
        self.ids_param_name: str | None = None
        origin = get_origin(self.return_type)
        if origin is not None and issubclass(origin, dict):
            key_type, value_type = get_args(self.return_type)
            self.dict_value_type = _strip_none(value_type)
            self.dict_type_key = (key_type, self.dict_value_type)
            # For query-object handlers, look for IDs field on the query class
            if self.query_type is not None:
                self.ids_param_name = _find_ids_field_on_query(self.query_type, key_type)
            else:
                self.ids_param_name = _find_ids_param(hints, key_type)

        # Lazy auto-wrap classification — populated on first access via
        # ``auto_wrap``. Lazy because a model referenced as a return type may
        # not be fully constructed yet when the @queries decorator fires
        # (e.g. forward references resolved later in a module).
        self._auto_wrap_cache: tuple[Any, ...] = ()

    @property
    def auto_wrap(self) -> tuple[str, Any] | None:
        """Whether handler results should be auto-wrapped via ``validate_batch``.

        Source of truth is ``Query[T].T`` — the *output* contract — not the
        handler's own return annotation. Lets handlers honestly declare
        ``-> list[dict[str, Any]]`` for a rows-shaped body while the
        framework validates to ``Model`` at the dispatch boundary.

        Returns ``None`` for ``dict[K, V]``-returning queries and for models
        without transformer fields. Cached on first access.
        """
        if not self._auto_wrap_cache:
            from fastbff.batch import classify_auto_wrap

            target = extract_query_return_type(self.query_type) if self.query_type is not None else None
            if target is None:
                target = self.return_type
            self._auto_wrap_cache = (classify_auto_wrap(target),)
        return self._auto_wrap_cache[0]

    def __repr__(self) -> str:
        func_name = getattr(self.original_func, '__name__', str(self.original_func))
        return f'QueryAnnotation({self.return_type}, {func_name})'
