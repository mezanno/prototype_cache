# SEC-05 — outbound connection validation

**Implemented and reviewed · ADR-025 · M-001/P1 · 2026-09-29.**

The default HttpFetcher transport validates DNS answers when a TCP connection is
opened, then passes only an approved numeric address to the socket backend. The
original hostname remains the HTTP origin for Host, TLS SNI and certificate
verification. A DNS change after validation cannot select a different hostname
resolution during that dial. Existing preflight checks remain an early rejection
layer; they are no longer the only safeguard.

Every address in a DNS answer must pass before any is dialed. Empty/invalid
answers and non-public/multicast destinations are rejected; IPv6 translation and
tunnel prefixes are conservatively rejected too. Failed approved addresses may
fall back only to another approved address within the remaining connection budget.
Redirects use the same transport; an existing pooled connection stays attached to
its originally validated peer. Environment proxies remain disabled.

The implementation uses HTTPX's public transport and httpcore's public network
backend interfaces. `httpcore` is now an explicit runtime dependency; its locked
version is unchanged. No TLS verification is disabled in production. Tests use a
local generated certificate and an explicit fixture trust root; the OpenSSL CLI
is required to run that TLS regression.

## Evidence and acceptance

`tests/test_fetcher_transport.py` covers changing DNS answers, mixed public/private
answers, metadata and translation addresses, redirect rebinding, preserved HTTP
Host, real HTTPS SNI and certificate-hostname mismatch rejection. Existing local
HTTP, timeout, body-limit and Garage/Postgres integration tests remain applicable.
The implementation baseline passed **366 tests**, none skipped, and the locked
container built successfully. The subsequent test-only delegation added three regressions: all **15 transport
tests passed**, and lead review accepted the additions without rework. Ruff and
strict mypy (71 files at this checkpoint) passed.

Observability: `fetcher_outbound_connections_total{outcome}` reports `connected`,
`failed` and `rejected` connection-stage outcomes; `fetch.ssrf_denied` logs a generic
denial without URL, credentials or IP details. Early preflight denial is logged
but does not count as a TCP connection-stage attempt.

## Limits retained explicitly

- `FETCHER_ALLOW_PRIVATE_HOSTS=1` deliberately bypasses the address policy for local
  fixtures; it must remain disabled in the pilot deployment.
- Injected HTTPX clients are trusted test/integration seams and must provide an
  equivalent secure transport when used for real outbound networking.
- The system DNS resolver may block independently of the socket timeout; elapsed
  time is checked before dialing, but resolver interruption is not implemented.
  Bounded fetch concurrency and operating-system resolver configuration belong
  to the resource/deployment gates in M-001/P2/P4.
- This protects the application destination-selection boundary, not against a
  compromised host, DNS library, network routing infrastructure or trust store.
- Origin-domain/path allowlisting for the Gallica facade is separate from IP-level
  SSRF protection and remains part of P3. The general fetcher still supports tmp.
- R-017 also covers the trusted-dispatcher/destination-policy boundary; closing the
  DNS race does not close all of R-017 or grant production security approval.

## Delegation trial

A single `gpt-6-sol` subagent was assigned only additional transport tests: approved
address fallback, total connection budget and response release/reuse after an
oversized body. The lead retains implementation review and security acceptance.
No parallel coding agents or new agent-directory framework were introduced.
Exact cost savings are not measured; model/task/test results provide an initial
quality record, not a cost claim.
