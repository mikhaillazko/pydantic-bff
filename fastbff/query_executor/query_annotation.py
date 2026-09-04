import types as builtin_types
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Sequence
from inspect import signature
from typing import Annotated
from typing import Any
from typing import NotRequired
from typing import Required
from typing import TypeGuard
from typing import Union
from typing import get_args
from typing import get_origin
from typing import get_type_hints
from typing import is_typeddict

from pydantic import BaseModel

from fastbff.exceptions import QueryRegistrationError

from .query import EntityQuery
from .query import Query


def _strip_none(t: Any) -> Any:
    """Remove NoneType from a simple Optional/Union for stable cache key construction."""
    origin = get_origin(t)
    if origin is Union or isinstance(t, builtin_types.UnionType):
        non_none = [a for a in get_args(t) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return t


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

    TypedDict is the preferred checked form. Broad ``dict`` / ``Mapping``
    annotations remain an unchecked compatibility path. Anything else has to
    match ``Query[T].T`` exactly so genuine model-mismatch bugs still fail at
    registration.
    """
    import collections.abc as collections_abc

    if is_typeddict(t):
        return True
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


def _is_pydantic_row(t: Any) -> bool:
    row = _raw_row_type(t)
    return isinstance(row, type) and issubclass(row, BaseModel)


def _is_renderable_output(t: Any) -> bool:
    from fastbff.resolve import classify_render

    return classify_render(t) is not None


def _raw_row_type(t: Any) -> Any | None:
    """Return the item type from a single-row or ``list[row]`` annotation."""
    if get_origin(t) is list:
        args = get_args(t)
        return args[0] if args else None
    return t


def _strip_annotated(t: Any) -> Any:
    while get_origin(t) in (Annotated, Required, NotRequired):
        t = get_args(t)[0]
    return t


def _allows_none(t: Any) -> bool:
    t = _strip_annotated(t)
    origin = get_origin(t)
    return (origin is Union or isinstance(t, builtin_types.UnionType)) and type(None) in get_args(t)


def _types_compatible(actual: Any, expected: Any) -> bool:
    """Conservative static compatibility check for raw row annotations."""
    actual = _strip_annotated(actual)
    expected = _strip_annotated(expected)
    if actual is Any or expected is Any or actual == expected:
        return True

    actual_origin = get_origin(actual)
    expected_origin = get_origin(expected)
    actual_union = actual_origin is Union or isinstance(actual, builtin_types.UnionType)
    expected_union = expected_origin is Union or isinstance(expected, builtin_types.UnionType)
    if actual_union:
        return all(_types_compatible(member, expected) for member in get_args(actual))
    if expected_union:
        return any(_types_compatible(actual, member) for member in get_args(expected))
    if actual_origin is not None or expected_origin is not None:
        if actual_origin != expected_origin:
            return False
        actual_args = get_args(actual)
        expected_args = get_args(expected)
        return len(actual_args) == len(expected_args) and all(
            _types_compatible(left, right) for left, right in zip(actual_args, expected_args, strict=True)
        )
    try:
        return isinstance(actual, type) and isinstance(expected, type) and issubclass(actual, expected)
    except TypeError:
        return False


def _resolver_key_type(resolver: Callable) -> Any | None:
    hints = get_type_hints(resolver, include_extras=True)
    parameters = tuple(signature(resolver).parameters)
    if not parameters:
        return None
    annotation = hints.get(parameters[0])
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (set, frozenset, list, tuple) and args:
        return args[0]
    return None


def _resolve_key_type(resolve: Any) -> Any | None:
    if resolve.query_type is not None:
        return_type = extract_query_return_type(resolve.query_type)
        if get_origin(return_type) is dict:
            return get_args(return_type)[0]
        return None
    return _resolver_key_type(resolve.resolver)


def _collection_key_compatible(actual: Any, key_type: Any, *, nullable: bool) -> bool:
    actual = _strip_annotated(actual)
    if _allows_none(actual):
        if not nullable:
            return False
        actual = _strip_none(actual)
    origin = get_origin(actual)
    args = get_args(actual)
    return (
        origin in (list, set, frozenset, tuple, Iterable, Sequence)
        and bool(args)
        and _types_compatible(args[0], key_type)
    )


def validate_raw_contract(annotation: 'QueryAnnotation') -> None:
    """Validate a typed raw row against its resolved output model."""
    raw_model = _raw_row_type(annotation.return_type)
    if not is_typeddict(raw_model) and not (isinstance(raw_model, type) and issubclass(raw_model, BaseModel)):
        return
    render_target = annotation.render_target
    if render_target is None:
        return

    from fastbff.resolve import get_resolve_fields

    render_kind, output_model = render_target
    raw_hints = get_type_hints(raw_model, include_extras=True)
    raw_required_keys = getattr(raw_model, '__required_keys__', frozenset(raw_hints))
    output_hints = get_type_hints(output_model, include_extras=True)
    resolve_by_name = {field.name: field for field in get_resolve_fields(output_model)}
    errors: list[str] = []

    raw_is_list = get_origin(annotation.return_type) is list
    if raw_is_list != (render_kind == 'list'):
        expected_shape = 'list of rows' if render_kind == 'list' else 'single row'
        actual_shape = 'list of rows' if raw_is_list else 'single row'
        errors.append(f'handler returns {actual_shape}; output requires {expected_shape}')

    for name, model_field in output_model.model_fields.items():
        resolve_field = resolve_by_name.get(name)
        source = resolve_field.source if resolve_field is not None else name
        if source not in raw_hints:
            if resolve_field is not None or model_field.is_required():
                errors.append(f'missing raw key {source!r} for output field {name!r}')
            continue

        actual = raw_hints[source]
        source_required = model_field.is_required()
        if resolve_field is None:
            expected = output_hints.get(name, model_field.annotation)
        else:
            key_type = _resolve_key_type(resolve_field.resolve)
            if key_type is None:
                # A resolver without a typed ``frozenset[K]`` first argument is
                # still supported, but its raw key contract cannot be checked.
                continue
            nullable = _allows_none(resolve_field.annotation)
            source_required = not nullable
            expected = list[key_type] if resolve_field.is_collection else key_type
            if nullable:
                expected = expected | None

        if source_required and source not in raw_required_keys:
            errors.append(f'raw key {source!r} for output field {name!r} must be required')

        compatible = (
            _collection_key_compatible(actual, key_type, nullable=nullable)
            if resolve_field is not None and resolve_field.is_collection and key_type is not None
            else _types_compatible(actual, expected)
        )
        if not compatible:
            errors.append(
                f'raw key {source!r} for output field {name!r} has type {actual!r}; expected {expected!r}',
            )

    if errors:
        query_name = annotation.query_type.__name__ if annotation.query_type is not None else '<unbound>'
        handler_name = getattr(annotation.original_func, '__name__', repr(annotation.original_func))
        details = '; '.join(errors)
        raise QueryRegistrationError(
            f'@queries {handler_name!r}: typed raw row is incompatible with '
            f'{query_name} output {output_model.__name__}: {details}.',
        )


def _find_ids_field(query_cls: type, key_type: Any) -> str | None:
    """Find the field holding the requested ids on an :class:`EntityQuery` subclass.

    Prefers a field literally named ``ids`` (the documented convention); falls
    back to the unique field typed as an iterable of the dict's key type.
    """
    fields = query_cls.model_fields  # type: ignore[attr-defined]
    if 'ids' in fields:
        return 'ids'
    for field_name, field_info in fields.items():
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
    """Metadata gathered once when a ``@queries`` function is registered.

    Stores the handler and all derived type metadata so that lookups in
    :class:`QueryExecutor` need no further reflection: whether the query opts
    into entity-level caching (an :class:`EntityQuery` subclass) and, lazily,
    whether its result model needs the render pipeline.
    """

    def __init__(self, original_func: Callable, explicit_query_type: type[Query] | None = None) -> None:
        self.original_func = original_func
        hints = get_type_hints(original_func)
        return_type = hints.get('return')
        if return_type is None:
            raise QueryRegistrationError(
                f'@queries {original_func.__name__!r}: handler must declare a return type annotation.',
            )
        self.return_type: type = return_type

        # Detect a Query[T] parameter; an explicit_query_type from the decorator
        # (``@queries(SomeQueryType)``) covers parameterless handlers.
        self.query_type: type | None = explicit_query_type
        self.query_param_name: str | None = None
        for param_name, param_type in hints.items():
            if param_name == 'return':
                continue
            if _is_query_subclass(param_type):
                if self.query_param_name is not None:
                    raise QueryRegistrationError(
                        f'@queries {original_func.__name__}: multiple Query parameters '
                        f'({self.query_param_name}: {self.query_type.__name__ if self.query_type else "?"}, '
                        f'{param_name}: {param_type.__name__})',
                    )
                if explicit_query_type is not None and explicit_query_type is not param_type:
                    raise QueryRegistrationError(
                        f'@queries {original_func.__name__}: explicit query type '
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
                and not (_is_pydantic_row(self.return_type) and _is_renderable_output(expected_return))
            ):
                raise QueryRegistrationError(
                    f'@queries {original_func.__name__}: return type {self.return_type} '
                    f'does not match {self.query_type.__name__}[{expected_return}]',
                )

        # Entity-level caching is explicit opt-in: only EntityQuery subclasses.
        self.is_entity: bool = False
        self.entity_key_type: Any = None
        self.entity_value_type: Any = None
        self.ids_field: str | None = None
        if (
            self.query_type is not None
            and isinstance(self.query_type, type)
            and issubclass(self.query_type, EntityQuery)
        ):
            dict_return = extract_query_return_type(self.query_type)
            if get_origin(dict_return) is dict:
                key_type, value_type = get_args(dict_return)
                self.entity_key_type = key_type
                self.entity_value_type = _strip_none(value_type)
                self.ids_field = _find_ids_field(self.query_type, key_type)
                if self.ids_field is None:
                    raise QueryRegistrationError(
                        f'EntityQuery {self.query_type.__name__!r} must declare an ids field — a '
                        f'field (conventionally named `ids`) typed as an iterable of {key_type}.',
                    )
                self.is_entity = True

        # Lazy render classification — a model referenced as a return type may
        # not be fully constructed when the decorator fires (forward refs).
        self._render_cache: tuple[Any, ...] = ()

    @property
    def render_target(self) -> tuple[str, Any] | None:
        """Whether handler results should go through :func:`fastbff.resolve.render`.

        Source of truth is ``Query[T].T`` — the resolved output contract. A
        handler may separately declare a TypedDict or Pydantic raw-row type,
        which is checked during finalize. ``None`` for entity queries,
        primitives, and models without ``Resolve`` fields. Cached.
        """
        if not self._render_cache:
            from fastbff.resolve import classify_render

            target = extract_query_return_type(self.query_type) if self.query_type is not None else None
            if target is None:
                target = self.return_type
            self._render_cache = (classify_render(target),)
        return self._render_cache[0]

    def __repr__(self) -> str:
        func_name = getattr(self.original_func, '__name__', str(self.original_func))
        return f'QueryAnnotation({self.return_type}, {func_name})'
