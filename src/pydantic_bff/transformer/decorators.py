from pydantic import BaseModel as PydanticBaseModel

from .inspection import introspect_model_transformers


def bff_model[T: type[PydanticBaseModel]](cls: T) -> T:
    """Optional eager-introspection decorator.

    ``populate_context_with_batch`` (and therefore ``executor.render``) will
    introspect a model on first use, so this decorator is not required. Use it
    when you want introspection cost paid at import time, or to make the
    intent explicit at the model definition::

        owner_field = build_transform_annotated(transform_owner)

        @bff_model
        class TeamDTO(BaseModel):
            id: int
            owner: Annotated[User, owner_field]

    Raises ``TypeError`` if applied to a non-Pydantic class.
    """
    if not (isinstance(cls, type) and issubclass(cls, PydanticBaseModel)):
        raise TypeError(f'@bff_model expects a Pydantic BaseModel subclass, got {cls!r}')
    introspect_model_transformers(cls)
    return cls
