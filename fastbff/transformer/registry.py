from collections.abc import Callable
from typing import Annotated
from typing import Any
from typing import get_args
from typing import get_origin

from fastbff.exceptions import TransformerRegistrationError

from .types import _TRANSFORMER_ANNOTATION_ATTR
from .types import TransformerAnnotation


def build_transform_annotated(func: Callable) -> Any:
    """Return an ``Annotated[ReturnType, TransformerAnnotation]`` alias for *func*."""
    transformer_annotation = getattr(func, _TRANSFORMER_ANNOTATION_ATTR, None)
    if not isinstance(transformer_annotation, TransformerAnnotation):
        func_name = getattr(func, '__name__', repr(func))
        raise TransformerRegistrationError(
            f'{func_name!r} is not a registered @transformer — '
            'decorate it with @transformer before calling build_transform_annotated().',
        )
    return Annotated[transformer_annotation.return_type, transformer_annotation]


def transformer_metadata(func_or_field: Any) -> TransformerAnnotation | None:
    """Return the :class:`TransformerAnnotation` for a transformer or field annotation."""
    direct = getattr(func_or_field, _TRANSFORMER_ANNOTATION_ATTR, None)
    if isinstance(direct, TransformerAnnotation):
        return direct
    if isinstance(func_or_field, TransformerAnnotation):
        return func_or_field
    if get_origin(func_or_field) is Annotated:
        for meta in get_args(func_or_field)[1:]:
            if isinstance(meta, TransformerAnnotation):
                return meta
    return None
