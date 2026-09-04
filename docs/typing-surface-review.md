# Typing surface review and proposed direction

Date: 2026-09-03
Reviewed revision: `a6f74c0` (`async-core-and-resolve-pipeline`)

> Status: accepted and implemented for 0.4.0 on 2026-09-04. See the
> [0.3 → 0.4 migration guide](migration/0.3-to-0.4.md).

## Recommendation

Keep the 0.3 Plan/Fetch/Merge implementation. The pipeline is a good architectural fix
for async composition, batching, caching, and standalone Pydantic validation. The typing
problem is narrower: a render query has **two contracts**, but the API names only one.

```text
handler / database             render boundary             endpoint
TeamRow                        Resolve keys                 TeamDTO
owner: int | None       ->     FetchUsers            ->    owner: User | None
```

`Query[list[TeamDTO]]` correctly types the right side. `list[dict]` leaves the left side
unchecked. An `Annotated[User | None, Resolve(FetchUsers)]` field cannot express both
types to a checker: per the [Python typing specification], tools treat metadata they do
not understand as metadata on the underlying `User | None` type.

Make the raw row a first-class, explicit `TypedDict`:

```python
class TeamRow(TypedDict):
    id: int
    owner: int | None


class TeamDTO(BaseModel):
    id: int
    owner: Annotated[User | None, Resolve(FetchUsers)]


class FetchTeams(Query[list[TeamDTO]]):
    pass


@app.queries(FetchTeams)
def fetch_teams(session: DBSession) -> list[TeamRow]:
    return [
        TeamRow(id=row.id, owner=row.owner_id)
        for row in session.execute(select(TeamTable)).scalars()
    ]
```

This works on the current branch today. A local `ty 0.0.31` probe accepted the valid form
and rejected `owner: str`. [`TypedDict`] is the standard structural type for dictionaries
with independently typed, required/optional keys, and it adds no runtime wrapper.

The repeated `id` declaration is not ideal, but it represents a genuine boundary rather
than accidental duplication: `TeamRow.owner` and `TeamDTO.owner` have different types.
Python typing cannot synthesize a statically visible TypedDict from Pydantic runtime
reflection. Eliminating those few repeated scalar fields requires code generation or a
type-checker plugin, both poor trade-offs at this stage.

## What is wrong in the current surface

1. **The docs advertise erased row types.** The quickstart and SQLAlchemy example return
   `list[dict]`, so a typo such as `{'owenr': 10}` and a wrong value type both reach
   runtime. The output query remains typed, but the code users write is not.

2. **Registration checks only “is mapping-shaped.”** `_is_row_shaped()` accepts the broad
   category and does not compare its keys with the output model or infer the key type of a
   `Resolve(EntityQuery[K, V])` field.

3. **The SQLAlchemy adapter creates a false type boundary.** `execute_all(statement,
   list[TeamDTO]) -> list[TeamDTO]` actually returns dictionaries via `cast`. The cast is
   internal, but the handler annotation is still untrue at the point it returns. Column
   label mistakes are invisible to the checker and are delayed until render.

4. **Raw source names are coupled to output names.** `_render_resolve` reads the raw key
   from `row[field.name]`. SQL must label `owner_id AS owner`, even though the two names
   describe different concepts. This makes projections more magical and weakens database
   tooling.

5. **Container support is narrower than the type surface suggests.** Render classification
   recognizes only bare models and `list[Model]`; `Sequence`, tuples, optional results,
   pagination wrappers, and generic envelopes do not enter the pipeline. This can wait,
   but should be documented as a deliberate constraint.

## Proposed release sequence

### 0.3.1: make the existing good path official

- Document `TypedDict` as the preferred raw-row type; change every `list[dict]` example.
- Detect it explicitly with `typing.is_typeddict`, rather than relying on its runtime
  relationship to `dict`.
- Add typing fixtures that run `ty` over public examples, including expected failures for
  missing, misspelled, and wrongly typed keys. Package-only type checking cannot protect
  user-facing examples.
- Keep `Mapping[str, Any]` working as an escape hatch, but describe it as unchecked.
- Rename internal language from “honest rows” to “raw rows”; `list[dict]` is runtime-honest
  but not a useful static contract.

This is a documentation and hardening release; it need not break `Query[T]`.

### 0.4: validate the raw/output contract at registration

For a `TypedDict` handler return and a renderable output model, build a compatibility
check from annotations already present:

- ordinary output field `x: T` requires a raw `x` compatible with Pydantic input `T`;
- `Annotated[V, Resolve(EntityQuery[K, V])]` requires raw `x: K | None`;
- collection resolve fields require an iterable of `K`;
- resolver functions should expose their key type explicitly, preferably as
  `resolver(keys: frozenset[K], ...) -> Mapping[K, V]`, and registration should verify it;
- error messages should name the query, handler, field, expected raw type, and received
  type.

This preserves the repository principle of deriving facts from annotations. It also
catches cross-file drift even when a consumer does not run a type checker.

Add an optional source name:

```python
class TeamRow(TypedDict):
    id: int
    owner_id: int | None


class TeamDTO(BaseModel):
    id: int
    owner: Annotated[
        User | None,
        Resolve(FetchUsers, source='owner_id'),
    ]
```

The default remains the output field name, so existing code is unchanged. `source=` is
preferable to Pydantic `validation_alias`: [Pydantic aliases] control model validation and
serialization names, whereas this name belongs to fastbff's pre-validation planning
phase.

Also normalize supported row objects explicitly:

```python
def row_mapping(row: Mapping[str, object] | BaseModel) -> Mapping[str, object]:
    if isinstance(row, BaseModel):
        return row.model_dump(mode='python')
    return row
```

TypedDict should remain the recommended form; a raw Pydantic model is useful when runtime
input validation is worth the allocation cost. Pydantic's [`model_validate`] supports
mapping/model validation, but it cannot make a field statically be both `K` before render
and `V` afterwards.

### SQLAlchemy adapter

Change the adapter to name the *raw* type and optionally validate it:

```python
@app.queries(FetchTeams)
def fetch_teams(converter: ConverterDep) -> list[TeamRow]:
    statement = select(TeamTable.id, TeamTable.owner_id)
    return converter.execute_all(statement, TeamRow)
```

Conceptual signature:

```python
def execute_all[R](
    self,
    statement: Select[object],
    row_type: type[R],
    *,
    validate: bool = True,
) -> list[R]: ...
```

In validated mode, use `TypeAdapter(list[R])` over SQLAlchemy mapping rows; in trusted
mode, keep the cast inside the adapter but return `list[R]`, never the resolved DTO type.
SQLAlchemy exposes mapping results as [`RowMapping`], so this is a natural conversion
boundary. Static typing still cannot prove that SQL labels match TypedDict keys; runtime
validation gives a clear error at the adapter instead of later in render.

## Alternatives considered

| Option | Typing quality | DX / implementation trade-off | Decision |
| --- | --- | --- | --- |
| Keep `list[dict[str, Any]]` | Poor | Minimal code; errors are delayed | Reject as documented default |
| Pretend rows are `list[TeamDTO]` with a cast | Misleading | Clean-looking signatures, false producer contract | Remove from examples/adapter |
| Explicit `TypedDict` raw rows | Strong | Small, honest duplication; zero wrapper cost | **Recommend** |
| Separate Pydantic raw model | Strong + runtime validation | More allocation and another model | Support optionally |
| `Query[Raw, Output]` everywhere | Strong but verbose | Duplicates the handler’s return annotation and complicates generic metadata | Defer |
| `Resolved[K, V]` field wrapper | Both types visible, poor consumption DX | Endpoint sees a wrapper or needs checker magic | Reject |
| Pydantic validator/alias trick | Runtime-only | Cannot change what static tools see; risks returning to validator-driven I/O | Reject |
| Generate row types / checker plugin | Potentially strongest | Toolchain, IDE, packaging, and synchronization burden | Revisit only with scale evidence |

## ADR amendment

ADR 0002 should remain accepted, with a short amendment:

> A render query has distinct raw-row and resolved-output contracts. `Query[T]` denotes
> only the resolved output returned by the executor. Handlers should return an explicitly
> typed raw mapping (`TypedDict` preferred). `Resolve` metadata relates the raw key type to
> the resolved field type, and fastbff validates that relation at registration.

This clarifies the architecture without undoing 0.3. The important boundary stays where
it is; it simply becomes visible to static tools.

## Acceptance criteria

- No primary docs example exposes an unparameterized `dict` or lies that raw rows are DTOs.
- A valid `TypedDict` example passes `ty`; wrong/missing fields fail the typing fixture.
- Registration rejects an incompatible resolve key type before serving requests.
- SQLAlchemy label/key mismatch fails in the adapter when validation is enabled.
- Existing `list[dict]` handlers remain source-compatible through 0.4.
- Executor callers still infer exactly `T` from `fetch(Query[T])`.

[Python typing specification]: https://typing.python.org/en/latest/spec/qualifiers.html#annotated
[`TypedDict`]: https://typing.python.org/en/latest/spec/typeddict.html
[Pydantic aliases]: https://docs.pydantic.dev/latest/concepts/fields/#field-aliases
[`model_validate`]: https://docs.pydantic.dev/latest/concepts/models/#validating-data
[`RowMapping`]: https://docs.sqlalchemy.org/en/20/core/connections.html#sqlalchemy.engine.RowMapping
