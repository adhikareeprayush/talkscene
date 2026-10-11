# @talkscene/sdk

The only way the web app is allowed to reach the API.

`src/schema.d.ts` is **generated** from `docs/openapi.yaml` — never edit it by
hand. After changing a Pydantic schema in `apps/api`:

```bash
make openapi   # re-export the contract
make sdk       # regenerate this package
```

Everything else in `src/` is hand-written: a typed `openapi-fetch` client, token
storage, and the two things OpenAPI cannot describe — the SSE turn stream and
audio uploads.

If something the UI needs is missing from this package, the API is incomplete.
That is the rule, not a slogan: it is what keeps the mobile app and third-party
clients able to do everything the web app can (plan §5.4).
