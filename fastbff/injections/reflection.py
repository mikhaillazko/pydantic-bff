from collections.abc import Callable
from inspect import isclass
from typing import Annotated
from typing import Any
from typing import get_args
from typing import get_origin

from fastapi.params import Depends as FastDepends

from fastbff.exceptions import InvalidAnnotationError
from fastbff.injections.dependant import cached_signature


def find_arg_info(func: Callable, target_type: type) -> tuple[str | None, type | None]:
    """Locate the first parameter whose declared type is *target_type* (or a subscripted form of it).

    Returns ``(param_name, raw_annotation)`` so callers can recover both the
    binding name and the original ``T``-bearing annotation
    (e.g. ``BatchArg[int]``).
    """
    func_signature = cached_signature(func)
    for param_key, param_val in func_signature.parameters.items():
        param_annotation = param_val.annotation
        param_cls = _underlying_class(param_annotation)
        if isclass(param_cls) and issubclass(param_cls, target_type):
            return param_key, param_annotation

    return None, None


def _underlying_class(annotation: Any) -> Any:
    """Strip ``Annotated[...]`` and generic subscripts down to the underlying class."""
    if get_origin(annotation) is Annotated:
        annotation = annotation.__origin__
    origin = get_origin(annotation)
    if isclass(origin):
        return origin
    return annotation


def get_dependency_callable(annotation: type | Callable[..., Any]) -> Callable[..., Any]:
    arg_origin_type = get_origin(annotation)
    if arg_origin_type is not Annotated:
        raise InvalidAnnotationError(f'Expected an Annotated[T, Depends(...)] object, got {annotation!r}.')

    arg_types_of_annotated = get_args(annotation)
    fastapi_depends_annotation = next(
        (arg for arg in arg_types_of_annotated[1:] if isinstance(arg, FastDepends)),
        None,
    )
    if fastapi_depends_annotation is None:
        raise InvalidAnnotationError(
            f'No Depends(...) metadata found in Annotated[...] for {annotation!r}.',
        )
    if fastapi_depends_annotation.dependency is None:
        raise InvalidAnnotationError(f'Depends() for {annotation!r} has no dependency callable.')
    return fastapi_depends_annotation.dependency
