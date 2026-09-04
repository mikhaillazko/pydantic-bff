"""SQLAlchemy → fastbff row converter."""

from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import Select
from sqlalchemy.orm import Session


class SqlalchemyConverter:
    """Execute a SQLAlchemy ``Select`` and project rows into shape for the render pipeline.

    Replaces the ``[{'field': row.column, ...} for row in scalars]`` boilerplate
    inside ``@queries`` handlers. Column labels in the ``Select`` must match
    field names on the target Pydantic model — fastbff's render pipeline takes
    the rows from here and validates them through ``Query[T].T`` at the dispatch
    boundary (resolving any ``Resolve`` fields along the way), so the caller of
    ``query_executor.fetch(...)`` receives the declared model type.

    Per-request: bind via FastAPI ``Depends`` against your session factory::

        def make_converter(session: DBSession) -> SqlalchemyConverter:
            return SqlalchemyConverter(session)

        ConverterDep = Annotated[SqlalchemyConverter, Depends(make_converter)]

        @app.queries(FetchTeams)
        def fetch_teams(converter: ConverterDep) -> list[TeamRaw]:
            statement = select(TeamRow.id, TeamRow.owner_id)
            return converter.execute_all(statement, TeamRaw)

    ``TeamRaw`` is normally a :class:`typing.TypedDict`. The adapter validates
    SQLAlchemy's mapping rows against it by default, so a missing/mislabelled
    column fails here rather than later in the render pipeline.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def execute_all[T](self, statement: Select[Any], row_type: type[T], *, validate: bool = True) -> list[T]:
        """Run *statement* and return rows shaped as ``row_type``.

        ``row_type`` is the handler's raw-row contract, normally a TypedDict,
        not the resolved Pydantic DTO returned by ``QueryExecutor.fetch``.
        Disable validation only for a trusted, performance-sensitive path.
        """
        rows = [dict(row) for row in self.session.execute(statement).mappings().all()]
        if not validate:
            return [row_type(**row) for row in rows]
        adapter = TypeAdapter(row_type)
        return [adapter.validate_python(row) for row in rows]

    def execute_one[T](self, statement: Select[Any], row_type: type[T], *, validate: bool = True) -> T | None:
        """Run *statement* and return the first row shaped as ``row_type``.

        Returns ``None`` when the statement has no result.
        """
        row = self.session.execute(statement).mappings().first()
        if row is None:
            return None
        raw = dict(row)
        if not validate:
            return row_type(**raw)
        return TypeAdapter(row_type).validate_python(raw)
