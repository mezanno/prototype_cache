# Local pilot deployment evidence — 2026-10-01

**Status: local implementation/restart checks passed; tester release is not signed off.**
The owner selected this machine with local or SSH-tunnel access and supplied the
current BnF Image API v3 URL. Isolated project: `asset-store-pilot`. Development
containers/volumes were preserved. Scheduled cleanup remains disabled.

## Runtime and image identity

| Component | Recorded identity |
|---|---|
| App candidate | `sha256:cf5736cb6147c223c13760945c76e593cc71213412ab6f3ce154f280e4fae2d7` |
| App source | `9b5ccb4` plus this implementation checkpoint (ADRs 033–036); runtime application changes are local-image/v3/resource mapping, while worker/budget changes are configuration |
| Garage v1.0.1 | `dxflrs/garage@sha256:a5706cf1f3d7b349ac5133ec59ad8181b709270b75e5f2fa7b3e1a5c07d67137` |
| Postgres 16 | `postgres@sha256:1a6ab3f5345eb6dbe04a1349529caabdb0ab09293a09590fad07b2246bfa4b54` |
| Resolved Python build input | `python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f` |
| Resolved uv build input | `ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424` |

Backend identities came from installed image metadata. No images were published.
The candidate was built with locked Python dependencies. Build input references
are recorded here; the Dockerfile still uses tags and image scanning remains open.
Fresh pilot credentials/configuration are in ignored `deploy/pilot/private/` with
directory mode 700 and runtime files mode 600. They are never included here.
Fresh schema migration reached 0003 before application startup.

## Live content check

Owner-approved source:
`https://openapi.bnf.fr/iiif/image/v3/ark:/12148/bd6t543024772/f18/full/max/0/default.webp`

Cached read:
`http://127.0.0.1:18001/openapi.bnf.fr/iiif/image/v3/ark:/12148/bd6t543024772/f18/full/max/0/default.webp`

- First preload missed and fetched the exact requested WebP response.
- Download size: **655,296 bytes**.
- SHA-256: `c5a299d6b8a05253e4eb072e016b9be2ac6c8cd7711ec2b4ce352c75ebef88bf`.
- Two cached downloads matched the checksum ETag; repeat preload reused the asset.
- Anonymous read returned 401; an unapproved origin returned 403; an absent image
  returned 404. Generic `/v1/ensure-url` was absent from OpenAPI.
- The earlier legacy sample and BnF-documented crop returned origin 403 (surfaced
  as preload 502); no repeated workaround requests or security relaxation.
- A generated 632-byte JPEG fixture was separately uploaded through the guard to
  test storage before the owner supplied the working v3 URL. It is clearly keyed
  as `fixturelocal8x8`, not recorded as a live-origin success.

## Restart and lifecycle checks

Full Postgres/Garage/asset-store/fetcher restart preserved the live asset identity
and checksum; repeat smoke reported an initial cache hit. Restarting only
asset-store while fetcher remained running also passed cached reads, exercising
remint after the old in-process capability store was lost. Before/after fetcher
outbound connection counters were unchanged during each cached smoke.
Lifecycle dry run: 0 candidates, 0 applied, 0 skipped, 0 errors, no exhausted
buckets. Scheduled apply remains disabled until reviewed operational approval.

Validation: **519 tests passed, none skipped**, with separate development
Garage/Postgres; 48 focused API/smoke and 22 Compose/preflight checks pass.
Ruff lint/format, strict mypy (86 files) and whitespace checks pass.

## Access

Asset-store/admin: `http://127.0.0.1:18000/admin`.
Cache API: `http://127.0.0.1:18001/docs`.
Both bind host loopback; Postgres/Garage ports are not published. Use the
`task-api` service credential from the protected fetcher env for cache calls and
the admin credential for administrative access. Do not copy secrets into this
record. The [smoke instructions](../../tools/cache-pilot/README.md) use the new URL.
Remote access should tunnel these loopback ports over SSH; no external ingress
was configured or exposed.

## Gates still open

Admin disconnect fix deployment/recheck (browser acceptance and workspace fix
verified on 2026-10-05; see [evidence](../../docs/acceptance/ADMIN_UI_LOCAL.md));
image/runtime scan findings; configured
host disk quotas/monitoring and audit retention; scheduled cleanup approval;
backup/restore and rollback rehearsal; representative corpus/concurrency/24-hour
soak; named operator/testers and limited release go/no-go. Named volumes are not
filesystem quotas. The host had about 7.3 GiB available RAM and 94 GiB free disk
at preparation time (root filesystem 90% used); those are observations, not a
reservation or an approved lifetime disk budget.

## Legacy/current resource pair and downloaded-file comparison

Owner-supplied legacy path:
`https://gallica.bnf.fr/iiif/ark:/12148/bpt6k9907264/f7/full/full/0/native.jpg`

Corresponding current path:
`https://openapi.bnf.fr/iiif/image/v3/ark:/12148/bpt6k9907264/f7/full/max/0/default.jpg`

Direct legacy fetch returned 403. Direct v3 fetch returned 740,739 JPEG bytes,
SHA-256 `a7a1f2ba2b730682e1b9a897f303f278b41a614dd417747d074d55746f864e34`.
Owner-provided `tmp/native.jpg` and `tmp/default.jpg` are both 2210×3218 RGB
JPEGs, respectively 740,739 and 740,812 bytes; their SHA-256 values are
`a7a1f2ba2b730682e1b9a897f303f278b41a614dd417747d074d55746f864e34` and
`f866b26e0b0c7682c3ed6c74bd60c4d00487cc43470a04ddb79f3eec45894616`.
Decoded pixels differ: mean absolute RGB difference 0.6277 on 0–255, RMS 1.0339,
maximum channel difference 12. JPEG quantization tables match and neither file
has EXIF entries. This comparison does not establish why the encodings differ. The owner reports, based on discussions with BnF specialists, that different
IIIF servers may back each API version. Server implementations and their
transcoding libraries/codecs/settings may differ. This owner-supplied context
has not been independently verified as the cause of the observed differences.
The downloaded files remain local user inputs, not committed test fixtures.

ADR-035 treats these URLs as one logical resource, using current v3 bytes as its
canonical representation. Both reads/preloads use the v3 alias, even when the
legacy URL is requested first. Cold fetch and forced refetch use v3 to avoid the
unstable old API. Other sizes/crops/rotations/qualities/formats remain separate.
No generic content-hash dedup or historical alias rebinding was introduced.

Live deployed pair check passed: legacy-first preload fetched via v3; current
preload was a hit with the same asset id and alias. Both cached reads returned
the same 740,739 JPEG bytes and checksum above. The previously cached WebP smoke
also passed unchanged after the image update.

## Owner UI check and task/result demonstration

The owner confirmed admin login worked after correcting credential copy/paste.
This establishes login usability, not every administrative mutation/browser flow.
A distinct worker identity was provisioned using the existing scoped worker role;
local results budget is explicitly 64 MiB, shared with lifecycle configuration.
The exact Python example in `docs/PILOT_QUICKSTART.md` was executed successfully
against the deployed APIs. It preloaded an existing WebP as a cache hit, resolved
the registered checksum, performed a verified worker read, copied an output
artifact and published the manifest last at:
`results/demo/task-1/5f9bb3889c8b4f55802da995e13044a0/worker-1/manifest.json`.
This is a protocol demonstration, not an OCR job or scheduler integration.
Secrets were not printed. Runtime configuration and owner-downloaded comparison
images are not committed.

## CLI image update — 2026-10-05

B-013 / SCN-004 / FR-040–042 / FR-005–007 / FR-051–053.
Source commit `4bf46ba` is now deployed to asset-store and fetcher via immutable
image `sha256:f25279675d7e78c02eba46621452eebd148572a6584e1179e094af81a7468fff`.
The build used the previously recorded Python and uv digests, explicitly pinned
in a temporary Dockerfile; `uv.lock` remained unchanged. An initial build resolved
a newer Python tag and was not deployed. Previous app image
`sha256:cf5736cb6147c223c13760945c76e593cc71213412ab6f3ce154f280e4fae2d7`
remains available for rollback. Protected pilot configuration changed only its
application image reference. Configuration preflight and migration gate passed.
Application containers were recreated; Garage/Postgres containers and volumes
were retained. Scheduled cleanup remains disabled.

CLI acceptance: both APIs returned ready; HTTP-served `/admin/admin.js` matched
committed source byte-for-byte (SHA-256
`113114e25a1dcb98054b460c16b52ae3f512ade57741f968d0cef5faff2521f4`).
All 10 Node client regressions passed using that downloaded script and controlled
responses. This verifies shipped client behavior in a simulated DOM, not browser
interaction. Authenticated cached WebP smoke passed: 655,296 bytes, SHA-256
`c5a299d6b8a05253e4eb072e016b9be2ac6c8cd7711ec2b4ce352c75ebef88bf`,
initial cache hit and repeat preload hit. This also exercises internal capability
renewal after the application restart. Credentials were not printed.

The deployed browser disconnect recheck remains pending because this session is
CLI-only. Task 1 is not fully closed. Backup/restore has not started; pause before
task 2 pending explicit owner resume. Evidence changes are uncommitted; no push.
