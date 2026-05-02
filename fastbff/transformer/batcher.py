from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel as PydanticBaseModel

from .inspection import introspect_model_transformers
from .types import _BATCHES_ATTR
from .types import _HAS_TRANSFORMERS_ATTR
from .types import BatchInfo


def populate_context_with_batch(
    return_model: type[PydanticBaseModel],
    dict_objects: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Phase 1 — scan *dict_objects* for every batchable field on *return_model*
    and return a Pydantic validation context populated with the collected IDs.

    If *return_model* has not been introspected yet, introspection runs lazily
    here, so models work out of the box.

    Pass the result as ``context=...`` when calling ``Model.model_validate`` so
    that transformers using ``BatchArg`` can read the full ID set from the
    validation context.
    """
    batches_info = get_model_batches(return_model)
    context_cache: dict[str, Any] = {}
    for batch_info in batches_info:
        batch_values: set[Any] = set()
        for dict_object in dict_objects:
            field_value = dict_object[batch_info.field_name]
            if isinstance(field_value, Iterable):
                for value in field_value:
                    if value is None:
                        continue
                    batch_values.add(value)
            elif field_value is not None:
                batch_values.add(field_value)
        context_cache.setdefault(batch_info.key, set()).update(batch_values)
    return context_cache


def get_model_batches(return_model: type[PydanticBaseModel]) -> list[BatchInfo]:
    """Return the cached :class:`BatchInfo` list for *return_model*, introspecting on demand.

    Reads ``return_model.__dict__`` directly rather than ``getattr`` so the
    lookup does not walk the MRO. Otherwise, once a parent class is
    introspected, every subclass would silently inherit the parent's batches
    and skip its own introspection — losing any subclass-only transformer
    fields and ignoring overrides.
    """
    cached = return_model.__dict__.get(_BATCHES_ATTR)
    if cached is not None:
        return cached
    introspect_model_transformers(return_model)
    return return_model.__dict__.get(_BATCHES_ATTR, [])


def model_has_transformer_fields(model: type) -> bool:
    """Return ``True`` if *model* has any field carrying a ``TransformerAnnotation``.

    Includes non-batched transformers (plain ``@transformer`` fields without
    ``BatchArg``) — those still need the ``query_executor`` in validation
    context to resolve their ``Depends(...)`` params, so they share the same
    auto-wrap path as batched transformers.

    Reads ``model.__dict__`` directly so subclass introspection is not
    short-circuited by a parent's cache (same rationale as
    :func:`get_model_batches`).
    """
    if not isinstance(model, type) or not issubclass(model, PydanticBaseModel):
        return False
    cached = model.__dict__.get(_HAS_TRANSFORMERS_ATTR)
    if cached is not None:
        return cached
    introspect_model_transformers(model)
    return model.__dict__.get(_HAS_TRANSFORMERS_ATTR, False)
