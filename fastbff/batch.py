from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import get_args
from typing import get_origin

from pydantic import BaseModel

from .query_executor.query_executor import QueryExecutor
from .transformer.batcher import model_has_transformer_fields
from .transformer.batcher import populate_context_with_batch


def validate_batch[ModelT: BaseModel](
    model: type[ModelT],
    rows: Sequence[Mapping[str, Any]],
    *,
    query_executor: QueryExecutor,
) -> list[ModelT]:
    """Validate a page of rows against *model*, sharing a batch-aware context.

    Walks *rows* once to collect the id set referenced by each
    :class:`BatchArg`-aware transformer, then validates every row against
    that shared context. The first row's ``executor.fetch(...)`` inside a
    transformer issues the bulk query; subsequent rows hit the query
    executor's entity-level cache.

    *query_executor* is threaded into the Pydantic validation context as
    ``context["query_executor"]``; transformer dispatch reads the
    per-transformer resolved-dep map from it.

    End user code does not normally call this — :class:`QueryExecutor`
    invokes it automatically for handlers whose declared return type is a
    :class:`pydantic.BaseModel` (or ``list`` thereof) with transformer
    fields.
    """
    context = populate_context_with_batch(model, rows)
    context['query_executor'] = query_executor
    return [model.model_validate(row, context=context) for row in rows]


def classify_auto_wrap(return_type: Any) -> tuple[str, type[BaseModel]] | None:
    """Decide whether *return_type* should be auto-wrapped through ``validate_batch``.

    * ``('list', Model)`` for ``list[Model]`` where Model carries transformer fields.
    * ``('single', Model)`` for a bare ``Model`` with transformer fields.
    * ``None`` for anything else (``dict[K, V]``, primitives, models without
      transformers, unions, etc).

    Unions and non-``list`` collections are intentionally excluded — the auto-
    wrap is for the dominant page / single-row patterns; anything more
    elaborate stays explicit via :func:`validate_batch`.
    """
    if get_origin(return_type) is list:
        args = get_args(return_type)
        if args and model_has_transformer_fields(args[0]):
            return ('list', args[0])
        return None
    if model_has_transformer_fields(return_type):
        return ('single', return_type)
    return None


def apply_auto_wrap(
    result: Any,
    wrap_info: tuple[str, type[BaseModel]],
    query_executor: QueryExecutor,
) -> Any:
    """Run :func:`validate_batch` for the given ``classify_auto_wrap`` outcome.

    Fast-path: if *result* already holds instances of the target model, the
    handler built DTOs directly and there is nothing to do —
    ``populate_context_with_batch`` would otherwise reach into rows via
    ``row[field]`` and choke on a model instance.
    """
    kind, model_cls = wrap_info
    if kind == 'list':
        if isinstance(result, list) and (not result or isinstance(result[0], model_cls)):
            return result
        return validate_batch(model_cls, result, query_executor=query_executor)
    if isinstance(result, model_cls):
        return result
    return validate_batch(model_cls, [result], query_executor=query_executor)[0]
