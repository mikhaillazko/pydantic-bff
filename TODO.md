# TODO — release-readiness review

Goal: ship `fastbff` in a state where a developer who has never seen it can
adopt it without footguns. North star is **simple to use, hard to misuse**.

Items are ordered by user-impact, not implementation cost. Each one calls out
the file/symbol to touch so the next contributor can start without a re-review.

Completed items have been removed; check `git log` for the fix details.

---

## P0 — credibility blockers (a new user gives up in 30 seconds)

### 1. Async handlers and transformers are accepted but broken

`QueryExecutor.fetch` (`fastbff/query_executor/query_executor.py:61`) and
`TransformerAnnotation._validate` (`fastbff/transformer/types.py:116`)
call handlers synchronously. An `async def fetch_users(...)` handler will
have its coroutine object cached and returned — silent corruption.

**Fix (proper)**: an `async fetch` path with parallel coroutine dispatch.
Larger scope — track separately once the rejection is in.

### 2. DI integration leans on FastAPI internals and signature-mutation hacks

The current injection plumbing piggybacks on private FastAPI surface and
hand-edits Python's introspection metadata to make `Depends(...)` work
the way we want. Each one is a load-bearing trick that will quietly
break when FastAPI changes its internals — and they pile up. The longer
they stay, the harder the upgrade story gets.

Sites:

- `fastbff/query_executor/query_executor.py:106` —
  `QueryExecutor.__signature__ = Signature(parameters=[])`. Forces
  FastAPI's `get_dependant` to ignore `__init__` params when an
  endpoint declares `Depends(QueryExecutor)`. The override to
  `provide_query_executor` is what actually fires; the empty signature
  is a workaround for FastAPI introspecting the class anyway.
- `fastbff/di.py:149` —
  `provide_query_executor.__signature__ = Signature(parameters=...)`.
  Synthesises a function signature listing the union of every
  registered handler's deps so FastAPI resolves them all at once.
- `fastbff/app.py:29-30` — direct imports from
  `fastapi.dependencies.utils` (`get_dependant`, `solve_dependencies`).
  Both have changed argument lists across recent FastAPI releases.
- `fastbff/app.py:261-262` — synthesises a `Request` with the scope
  keys `fastapi_inner_astack` and `fastapi_function_astack` so
  `solve_dependencies` does not raise. Both are FastAPI-internal,
  introduced post-0.112; the `pyproject.toml` floor of
  `fastapi>=0.100` is wrong — the entrypoint path will fail on
  0.100-0.111.
- `fastbff/app.py:_extract_solved_values` — version-shim for the two
  return shapes of `solve_dependencies` (tuple vs `SolvedDependency`).

**Rework — pick one (or layer them)**:

1. **Lean only on FastAPI's public surface**. Replace the synthetic
   `provide_query_executor` factory with a small Pydantic / FastAPI
   sub-app that exposes the union of deps as a normal callable.
   Resolve `QueryExecutor` itself through the standard
   `dependency_overrides` mapping with no `__signature__` mutation —
   the override key already handles the lookup. For offline use
   (`@app.entrypoint`), call user-side dependency factories directly
   from the resolved-deps map instead of driving FastAPI's
   `solve_dependencies` through a fake `Request`.
2. **Own the DI graph**. Walk the registered handlers ourselves,
   resolve `Depends(...)` via a tiny container that understands
   FastAPI-style `Annotated[..., Depends(factory)]` parameters, and
   stop reaching into `fastapi.dependencies.utils` entirely. The
   resolver is small (we already have `collect_dep_specs`); the
   payoff is no FastAPI version coupling at all.
3. **Minimum-viable cleanup** if the larger rework is out of scope:
   bump the floor to `fastapi>=0.112` (or whatever the lowest version
   is that ships both scope keys — verify), pin it in CI, and add a
   regression test that exercises `@app.entrypoint` against that
   floor so the next FastAPI bump is a known-cost upgrade.

Whichever path is picked, the goal is: zero `__signature__ =` lines,
zero imports from `fastapi.dependencies.utils`, zero hand-rolled
`Request` scopes.

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

---

## P2 — packaging and release process

### 5. `pyproject.toml` status is `Alpha` and version is `0.1.0`

`pyproject.toml:13`. For "wide developer use" this signals "do not depend
on this." Decide what stability bar we are committing to and bump.

### 6. `publish.yml` has no tag/version guard

`.github/workflows/publish.yml` runs `uv publish` on any release event
without checking the git tag matches `pyproject.toml` `version`, and
without a TestPyPI dry-run.

**Fix**:
- Add a step that fails if `pyproject.toml` `version` != `${GITHUB_REF_NAME#v}`.
- Optionally add a manual-dispatch TestPyPI workflow before promoting.

### 7. No `__version__` constant

`fastbff/__init__.py` should expose `__version__` (read from package
metadata via `importlib.metadata.version("fastbff")` so it stays in sync
with `pyproject.toml`).

### 8. No `CHANGELOG.md`, no `CONTRIBUTING.md`, no docs site

For wide adoption:
- `CHANGELOG.md` (Keep-a-Changelog format) so users can scan before
  upgrading.
- `CONTRIBUTING.md` covering the uv / ruff / ty toolchain that's documented
  in `CLAUDE.md` but invisible to outside contributors.
- Optional but recommended: a docs site (mkdocs-material) for the
  cookbook + reference, separate from the README.

### 9. `requires-python = ">=3.12"` excludes the bulk of production fleets

PEP 695 generics (`class Query[T]`) lock out Python 3.10/3.11. If wide
adoption is the goal, support 3.11 by rewriting the generics with
`TypeVar` / `Generic[T]`. If we keep 3.12+, document the rationale in
the README.

---

## P3 — ergonomics / nits

- `@app.queries(FetchAllUsers)` (decorator-factory form) vs
  `@app.queries` is a subtle API split. Document the decision tree, or
  detect parameterless handlers and emit a clear error pointing at the
  explicit form when the user forgets.
- `FastBFF` itself is usable as a `dependency_overrides_provider`
  (used by `_run_entrypoint`). Document this — it makes custom test
  harnesses easier. (Likely subsumed by the P0 #2 rework.)

---

## Test coverage gaps

Cases that bite first-time users; we should have at least one regression
test per row:

- Async handler / async transformer (rejected at registration with a
  clear error).
- `Query` with a nested Pydantic model field (cache key path).
- `validate_batch` over a large page (sanity / performance smoke).
- `bind()` called after `mount()` (whatever the chosen semantics).
