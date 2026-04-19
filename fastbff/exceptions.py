"""Public exception hierarchy for ``fastbff``.

All errors raised by the library subclass :class:`FastBFFError` so callers
can catch them with a single ``except`` clause. Sub-exceptions are typed by
concern (registration, batching, dependency resolution) so that targeted
handling is also possible.
"""


class FastBFFError(Exception):
    """Base class for all errors raised by ``fastbff``."""


class RegistrationError(FastBFFError):
    """Raised when a ``@query`` or ``@transformer`` cannot be registered."""


class QueryRegistrationError(RegistrationError):
    """Raised when a ``@query`` handler is mis-declared.

    Examples: missing return type, return type does not match ``Query[T]``,
    multiple ``Query[T]`` parameters on a single handler.
    """


class TransformerRegistrationError(RegistrationError):
    """Raised when a ``@transformer`` callable is mis-declared.

    Example: missing return type annotation, multiple transformer annotations
    on a single model field.
    """


class QueryNotRegisteredError(FastBFFError, KeyError):
    """Raised when ``QueryExecutor.fetch`` receives a query class with no registered handler.

    Subclasses :class:`KeyError` for backwards compatibility with the previous
    behaviour of :meth:`QueryRouter.get_annotation_by_query_type`.
    """


class BatchContextMissingError(FastBFFError, RuntimeError):
    """Raised when a transformer with a ``BatchArg`` is invoked without a batching context.

    Almost always means a row was validated via plain ``Model.model_validate``
    instead of :func:`validate_batch`, which builds the batch context and
    threads it through ``context=``.
    """


class InvalidAnnotationError(FastBFFError, TypeError):
    """Raised when a parameter annotation does not have the expected ``Annotated[...]`` shape.

    Used by the DI machinery when reflecting over dependency declarations.
    """


class ScopeNotActiveError(FastBFFError, RuntimeError):
    """Raised when DI resolution is attempted outside an active ``init_context()`` scope."""


class DependencyResolutionError(FastBFFError):
    """Raised when one or more ``Depends(...)`` parameters fail to resolve."""

    def __init__(self, errors: list[object]) -> None:
        super().__init__(f'Failed to resolve dependencies: {errors!r}')
        self.errors = errors


class DependencyOverrideError(FastBFFError, KeyError):
    """Raised when an override targets an interface that was not registered."""
