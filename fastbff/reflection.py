from collections.abc import Callable
from functools import cache
from inspect import Signature
from inspect import isclass
from inspect import signature
from typing import Annotated
from typing import Any
from typing import get_origin
from typing import get_type_hints


@cache
def cached_signature(func: Callable) -> Signature:
    return signature(func)


@cache
def cached_type_hints(func: Callable) -> dict[str, Any]:
    """Return ``typing.get_type_hints(func, include_extras=True)`` or ``{}`` on failure.

    PEP 563 (``from __future__ import annotations``) leaves ``param.annotation``
    as a string; ``get_type_hints`` evaluates those strings against the
    function's module globals. We swallow resolution errors (e.g. closures
    referencing locals) so the caller can fall back to the raw annotation —
    which is already a real type when PEP 563 is not in effect.
    """
    try:
        return get_type_hints(func, include_extras=True)
    except Exception:
        return {}


def find_arg_info(func: Callable, target_type: type) -> tuple[str | None, type | None]:
    """Locate the first parameter whose declared type is *target_type* (or a subscripted form of it).

    Returns ``(param_name, raw_annotation)`` so callers can recover both the
    binding name and the original ``T``-bearing annotation
    (e.g. ``BatchArg[int]``).
    """
    func_signature = cached_signature(func)
    hints = cached_type_hints(func)
    for param_key, param_val in func_signature.parameters.items():
        param_annotation = hints.get(param_key, param_val.annotation)
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
