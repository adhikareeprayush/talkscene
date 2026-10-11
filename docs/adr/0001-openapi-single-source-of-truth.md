# ADR 0001 — The OpenAPI contract is generated from typed models, not hand-written

* Status: accepted
* Date: 2026-10-10
* Context: system plan §5.4 ("API-first workflow")

## Context

The plan says: *write `openapi.yaml` first, then generate server stubs / Pydantic
models and the TS SDK in CI.* Hand-authoring the document gives the contract a
review surface, which is the valuable part. But generating Pydantic models from
OpenAPI produces unidiomatic code that nobody edits by hand, so the generated
models drift from the hand-written service layer and you end up with two
sources of truth.

## Decision

Invert the generation direction, keep the review property:

1. Pydantic v2 schemas in `apps/api/talkscene/schemas/` are the authoritative
   definition of every request and response body.
2. `make openapi` exports `docs/openapi.yaml` from the running app.
3. The exported file **is committed**. CI re-exports it and fails if the working
   copy differs (`.github/workflows/ci.yml::contract`). So every API change shows
   up as a diff on `docs/openapi.yaml` in the pull request — design review still
   happens on the contract.
4. The TypeScript SDK (`packages/sdk`) is generated *only* from
   `docs/openapi.yaml`, never from the Python source. The web app may not import
   anything else.
5. Schemathesis runs property-based contract tests against the live app.

## Consequences

* One source of truth; the YAML can never silently drift.
* A breaking change is visible as a contract diff before it merges.
* Cost: the contract is reviewed slightly *after* it is written rather than
  strictly before. Mitigated by requiring the schema change and the route change
  in the same PR.
* `/v1` is pinned in the route prefix; a breaking change opens `/v2` and both
  are exported to the same document.
