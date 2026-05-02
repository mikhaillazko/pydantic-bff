from typing import Annotated
from typing import Any
from typing import Optional
from typing import Union
from typing import get_args
from typing import get_origin
from typing import get_type_hints

from pydantic import BaseModel as PydanticBaseModel

from fastbff.exceptions import TransformerRegistrationError

from .types import _BATCHES_ATTR
from .types import BatchInfo
from .types import TransformerAnnotation


def introspect_model_transformers(cls: type[PydanticBaseModel]) -> None:
    """Scan *cls*'s annotations for transformer fields with a ``BatchArg`` and
    cache the batching metadata on ``cls.__batches__``.

    Invoked lazily on first use (via :func:`get_model_batches`). No-ops when
    the model has no batchable transformer fields.

    Uses :func:`typing.get_type_hints` with ``include_extras=True`` so models
    declared in modules with ``from __future__ import annotations`` (PEP 563)
    work transparently — string annotations are evaluated against the model's
    own module globals while the ``Annotated[...]`` metadata carrying the
    ``TransformerAnnotation`` is preserved.
    """
    batches = []
    annotations = get_type_hints(cls, include_extras=True)
    for field_name, field_type in annotations.items():
        transformer_annotation = _find_transformer_annotation(field_type)
        if transformer_annotation and transformer_annotation.batch_key:
            batches.append(
                BatchInfo(
                    field_name=field_name,
                    key=transformer_annotation.batch_key,
                    batch_fetch_type=transformer_annotation.batch_fetch_type,
                ),
            )

    setattr(cls, _BATCHES_ATTR, batches)


def _find_transformer_annotation(field_type: type) -> TransformerAnnotation | None:
    metadata = _find_all_nested_annotations(field_type)
    transformer_annotations = [item for item in metadata if isinstance(item, TransformerAnnotation)]
    if not transformer_annotations:
        return None
    if len(transformer_annotations) > 1:
        raise TransformerRegistrationError(
            f'Field declares multiple TransformerAnnotation entries; only one is allowed: {transformer_annotations!r}',
        )
    return transformer_annotations[0]


def _find_all_nested_annotations(_type: type) -> list[Any]:
    annotations: list[Any] = []
    origin = get_origin(_type)

    if origin is Annotated:
        # For Annotated[T, a1, a2, ...], get_args returns (T, a1, a2, ...)
        args = get_args(_type)
        base_type = args[0]
        for meta in args[1:]:
            # When user-supplied metadata is itself an Annotated alias, recurse
            # into it explicitly — Python does not flatten the outer Annotated
            # into the inner one if the base types do not match by identity.
            if get_origin(meta) is Annotated:
                annotations.extend(_find_all_nested_annotations(meta))
            else:
                annotations.append(meta)
        annotations.extend(_find_all_nested_annotations(base_type))
    elif origin in (Union, Optional) or get_args(_type):
        for arg in get_args(_type):
            annotations.extend(_find_all_nested_annotations(arg))

    return annotations
