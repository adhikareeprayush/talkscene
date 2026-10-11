"""Contract tests.

ADR 0001 makes the committed `docs/openapi.yaml` the review surface for API
changes.  That is only true if it cannot drift, so the first test here is the
same check CI runs: re-export the spec and compare.  The rest assert the
conventions the plan sets out in §10 — one error shape, one version prefix,
auth everywhere it matters.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from talkscene.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED_SPEC = REPO_ROOT / "docs" / "openapi.yaml"

PUBLIC_PATHS = {
    "/v1/auth/guest",
    "/v1/auth/signup",
    "/v1/auth/login",
    "/v1/auth/refresh",
    "/v1/auth/guest/sessions",
    "/v1/languages",
    "/v1/scenarios",
    "/v1/scenarios/{scenario_id}",
    "/v1/status",
    "/healthz",
    "/readyz",
    "/metrics",
}
ADMIN_PREFIX = "/v1/admin"


@pytest.fixture(scope="module")
def spec() -> dict:
    return create_app().openapi()


def test_the_committed_contract_matches_the_app(spec: dict) -> None:
    """The guarantee from ADR 0001: every API change shows up as a diff on the
    contract in the pull request. Run `make openapi` after changing a schema."""
    assert COMMITTED_SPEC.is_file(), "docs/openapi.yaml is missing - run `make openapi`"
    committed = yaml.safe_load(COMMITTED_SPEC.read_text(encoding="utf-8"))
    # Compare the whole document, normalised through the same YAML round-trip
    # the exporter uses: a changed field type must fail this, not just a new path.
    live = yaml.safe_load(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=100))
    stale = sorted(
        {*committed["paths"], *live["paths"]} - {
            p for p in live["paths"] if committed["paths"].get(p) == live["paths"][p]
        }
    )
    stale_schemas = sorted(
        name
        for name in {*committed["components"]["schemas"], *live["components"]["schemas"]}
        if committed["components"]["schemas"].get(name) != live["components"]["schemas"].get(name)
    )
    assert not stale and not stale_schemas, (
        "docs/openapi.yaml is out of date - run `make openapi` and commit the result. "
        f"Changed paths: {stale[:5]}; changed schemas: {stale_schemas[:8]}"
    )


def test_the_spec_is_structurally_valid_openapi(spec: dict) -> None:
    import schemathesis

    schema = schemathesis.openapi.from_dict(spec)
    assert spec["openapi"].startswith("3.")

    # Every operation must resolve: an unresolvable $ref breaks SDK generation
    # silently, producing `unknown` types in the TypeScript client.
    operations = list(schema.get_all_operations())
    assert len(operations) > 30, f"only {len(operations)} operations resolved"
    broken = [result for result in operations if result.ok() is None]
    assert broken == [], f"{len(broken)} operation(s) failed to resolve"


def test_every_versioned_path_lives_under_v1(spec: dict) -> None:
    unversioned = [
        path
        for path in spec["paths"]
        if not path.startswith("/v1/") and path not in {"/healthz", "/readyz", "/metrics"}
    ]
    assert unversioned == [], f"these paths are outside /v1: {unversioned}"


def test_errors_are_problem_json_everywhere(spec: dict) -> None:
    """Plan §10: one error shape across the API, so a client writes one handler."""
    offenders: list[str] = []
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            for status, response in operation.get("responses", {}).items():
                if not str(status).startswith(("4", "5")):
                    continue
                content = response.get("content", {})
                if "application/problem+json" not in content and status != "422":
                    offenders.append(f"{method.upper()} {path} -> {status}")
    assert offenders == [], f"non-problem+json error responses: {offenders}"


def test_the_problem_schema_carries_a_stable_code(spec: dict) -> None:
    problem = spec["components"]["schemas"]["Problem"]
    for field in ("type", "title", "status", "detail", "code"):
        assert field in problem["properties"], f"Problem is missing `{field}`"
    assert "code" in problem["required"], "clients branch on `code`, so it cannot be optional"


def test_protected_operations_declare_the_auth_header(spec: dict) -> None:
    missing: list[str] = []
    for path, operations in spec["paths"].items():
        if path in PUBLIC_PATHS:
            continue
        for method, operation in operations.items():
            if method not in ("get", "post", "patch", "delete"):
                continue
            params = {p.get("name") for p in operation.get("parameters", [])}
            has_auth = "authorization" in {str(p).lower() for p in params}
            has_admin = path.startswith(ADMIN_PREFIX) and "x-admin-token" in {
                str(p).lower() for p in params
            }
            if not (has_auth or has_admin):
                missing.append(f"{method.upper()} {path}")
    assert missing == [], f"these operations take no credentials: {missing}"


def test_the_turn_endpoint_documents_its_event_stream(spec: dict) -> None:
    operation = spec["paths"]["/v1/sessions/{session_id}/turns"]["post"]
    assert "text/event-stream" in operation["responses"]["200"]["content"]
    description = operation["description"]
    # The event names are the contract for the client's SSE handler.
    for event in ("transcript", "no_speech", "ai_delta", "ai_audio", "meta", "turn_state", "done"):
        assert f"`{event}`" in description, f"the `{event}` event is undocumented"


def test_the_report_endpoint_documents_both_success_shapes(spec: dict) -> None:
    responses = spec["paths"]["/v1/sessions/{session_id}/report"]["get"]["responses"]
    assert "200" in responses and "202" in responses
    assert "Report" in str(responses["200"])
    assert "ReportPending" in str(responses["202"])


def test_audio_endpoints_declare_an_audio_content_type(spec: dict) -> None:
    audio_paths = [p for p in spec["paths"] if "audio" in p]
    assert audio_paths
    for path in audio_paths:
        for method, operation in spec["paths"][path].items():
            if method != "get":
                continue
            content = operation["responses"]["200"].get("content", {})
            assert any(key.startswith("audio/") for key in content), path


def test_pronunciation_results_are_marked_as_estimates_in_the_schema(spec: dict) -> None:
    """ADR 0003: a client must be able to tell an estimate from a measurement
    without reading our source."""
    pron = spec["components"]["schemas"]["Pronunciation"]["properties"]
    assert "estimated" in str(pron["confidence"])
    attempt = spec["components"]["schemas"]["DrillAttempt"]["properties"]
    assert "authoritative" in attempt
    assert "estimate" in attempt["authoritative"]["description"].lower()
