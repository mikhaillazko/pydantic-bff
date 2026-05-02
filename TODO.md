# TODO — release-readiness review

Goal: ship `fastbff` in a state where a developer who has never seen it can
adopt it without footguns. North star is **simple to use, hard to misuse**.

Items are ordered by user-impact, not implementation cost. Each one calls out
the file/symbol to touch so the next contributor can start without a re-review.

Completed items have been removed; check `git log` for the fix details.

---

## P0 — credibility blockers (a new user gives up in 30 seconds)

### 1. README documents APIs and exceptions that do not exist

`README.md` references symbols absent from the codebase:

- `InjectorRegistry` (DI section, `README.md:212`) — class does not exist.
  The code uses FastAPI's `dependency_overrides` directly via `FastBFF.bind`.
- `DependencyResolutionError`, `DependencyOverrideError`,
  `InvalidAnnotationError`, `ScopeNotActiveError` (`README.md:390-394`) —
  none defined in `fastbff/exceptions.py`.
- `README.md:415` says the integration test lives at `integration_test.py`
  in the project root — actual path is `integration_tests/`.

**Fix**: rewrite the affected sections to match the real public surface
(`fastbff/__init__.py`, `fastbff/exceptions.py`). Treat the public
exception list as the source of truth — either add the missing exception
types or delete the doc lines.

While you're in the README, also add a "Module organisation" note: under
PEP 563, models/transformers/queries that reference local-scope names
won't resolve through `typing.get_type_hints` — declare them at module
level. This matches Pydantic's own constraint.

### 2. Async handlers and transformers are accepted but broken

`QueryExecutor.fetch` (`fastbff/query_executor/query_executor.py:61`) and
`TransformerAnnotation._validate` (`fastbff/transformer/types.py:116`)
call handlers synchronously. An `async def fetch_users(...)` handler will
have its coroutine object cached and returned — silent corruption.

**Fix (minimum)**: detect async callables at registration in
`QueryAnnotation.__init__` (`fastbff/query_executor/query_annotation.py:81`)
and `TransformerAnnotation.__init__` (`fastbff/transformer/types.py:77`),
raise a typed `RegistrationError` explaining sync-only.

**Fix (proper)**: an `async fetch` path with parallel coroutine dispatch.
Larger scope — track separately once the rejection is in.

---

## P1 — silent footguns

### 3. `bind()` after `mount()` does not propagate

`FastBFF.mount` (`fastbff/app.py:189`) does
`fastapi_app.dependency_overrides.update(self._overrides)` — a one-shot
copy. Subsequent `app.bind(...)` calls write to `self._overrides` only.
Users (especially in tests) expect post-mount binds to take effect.

**Fix options**:
- Have `mount` make `fastapi_app.dependency_overrides` and `self._overrides`
  the same dict (assignment-in-place via `clear() + update()` is risky;
  prefer rewriting `bind` to write to both if mounted).
- Or document loudly + raise on `bind` after `mount`.

### 4. `_to_hashable` blows up on common Pydantic shapes

`fastbff/query_executor/query_cache.py:50` does not handle Pydantic
`BaseModel`, `datetime`, `UUID`, dataclasses, etc. The first time a user
nests a model inside a `Query` field, the cache key construction raises
`TypeError: unhashable type` from deep inside cache code.

**Fix**: extend `_to_hashable` to dispatch on `BaseModel`
(`v.model_dump(mode='python')` then recurse) and dataclasses, and raise
`FastBFFError` with a guidance message for anything else still unhashable.

### 5. `include_router` dedup is inconsistent

`FastBFF.include_router` (`fastbff/app.py:125`) raises
`QueryRegistrationError` on duplicate queries but silently overwrites
duplicate transformers. Pick one rule and apply it both ways. (Probably
"raise on duplicate transformer" — silent overwrite is the worse failure
mode.)

### 6. `transformer_callable(...)` is sold as a clean test path but isn't

The README quickstart says:

```python
call = transformer_callable(transform_owner)
assert call(owner_id=1, query_executor=fake) == ...
```

In reality the caller still has to construct every `Annotated[..., Depends(...)]`
parameter by hand. Either:

- Add `app.call_transformer(fn, *args, **kwargs)` that resolves deps through
  the app's bindings; or
- Rewrite the test-helpers section to show realistic usage (passing all
  deps explicitly).

---

## P2 — packaging and release process

### 7. `pyproject.toml` status is `Alpha` and version is `0.1.0`

`pyproject.toml:13`. For "wide developer use" this signals "do not depend
on this." Decide what stability bar we are committing to and bump.

### 8. `publish.yml` has no tag/version guard

`.github/workflows/publish.yml` runs `uv publish` on any release event
without checking the git tag matches `pyproject.toml` `version`, and
without a TestPyPI dry-run.

**Fix**:
- Add a step that fails if `pyproject.toml` `version` != `${GITHUB_REF_NAME#v}`.
- Optionally add a manual-dispatch TestPyPI workflow before promoting.

### 9. No `__version__` constant

`fastbff/__init__.py` should expose `__version__` (read from package
metadata via `importlib.metadata.version("fastbff")` so it stays in sync
with `pyproject.toml`).

### 10. No `CHANGELOG.md`, no `CONTRIBUTING.md`, no docs site

For wide adoption:
- `CHANGELOG.md` (Keep-a-Changelog format) so users can scan before
  upgrading.
- `CONTRIBUTING.md` covering the uv / ruff / ty toolchain that's documented
  in `CLAUDE.md` but invisible to outside contributors.
- Optional but recommended: a docs site (mkdocs-material) for the
  cookbook + reference, separate from the README.

### 11. Internal FastAPI APIs in `_run_entrypoint`

`fastbff/app.py:223-243` constructs scope keys (`fastapi_inner_astack`,
`fastapi_function_astack`) that are FastAPI-internal and post-0.112.
The `pyproject.toml` floor of `fastapi>=0.100` is wrong — the entrypoint
path will fail on 0.100-0.111.

**Fix**:
- Bump the lower bound to `fastapi>=0.112` (or whatever the lowest version
  that has both keys is — verify, don't guess).
- Add an integration test pinned to that floor in CI.

### 12. `requires-python = ">=3.12"` excludes the bulk of production fleets

PEP 695 generics (`class Query[T]`) lock out Python 3.10/3.11. If wide
adoption is the goal, support 3.11 by rewriting the generics with
`TypeVar` / `Generic[T]`. If we keep 3.12+, document the rationale in
the README.

---

## P3 — ergonomics / nits

- `QueryExecutor.__signature__ = Signature([])` (`query_executor.py:105`)
  is load-bearing magic — add a one-line pointer in the README's FastAPI
  integration section so users tinkering with custom executors don't trip
  on it.
- `@app.queries(FetchAllUsers)` (decorator-factory form) vs
  `@app.queries` is a subtle API split. Document the decision tree, or
  detect parameterless handlers and emit a clear error pointing at the
  explicit form when the user forgets.
- `FastBFF` itself is usable as a `dependency_overrides_provider`
  (used by `_run_entrypoint`). Document this — it makes custom test
  harnesses easier.

---

## Test coverage gaps

Cases that bite first-time users; we should have at least one regression
test per row:

- Async handler / async transformer (rejected at registration with a
  clear error).
- `Query` with a nested Pydantic model field (cache key path).
- `validate_batch` over a large page (sanity / performance smoke).
- `bind()` called after `mount()` (whatever the chosen semantics).
