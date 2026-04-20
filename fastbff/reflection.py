from collections.abc import Callable
from functools import cache
from inspect import Signature
from inspect import isclass
from inspect import signature
from typing import Annotated
from typing import Any
from typing import get_origin


@cache
def cached_signature(func: Callable) -> Signature:
    return signature(func)


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
