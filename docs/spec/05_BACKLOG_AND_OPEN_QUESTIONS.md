# 05 — Active backlog, open choices and risks

**M-002; 2026-11-07.** This table is the new execution queue. Old B-001..025,
Q-001..036 and R-001..020 remain in the [historical backlog](../history/asset-store/spec/05_BACKLOG_AND_OPEN_QUESTIONS.md).
Old “resolved” questions do not constrain the pivot; old security findings are not
closed by renumbering. Requirements: [FR/NFR](02_REQUIREMENTS.md).

## Delivery queue

| ID | Release / priority | Work | Dependencies | Acceptance / state |
|---|---|---|---|---|
| B-100 | Now | Record pivot, superseding scope/ADRs/workplan and preserve historical evidence. | Owner decisions | Done: documentation only, 2026-11-08; no new product implementation. |
| B-101 | R1 / next | Confirm first import sample, explicit document/page ordering/schema, formats/size budget and deployment base URLs. Obtain current Corpusense/job example for R2 without redesigning it. | Q-101/103/106; Q-102 for integration | Document concrete API/import contract and selected limits; UI details need not block independent catalog/import preparation. FR-100..103, NFR-102. |
| B-102 | R1 | Collection catalog + immutable raw storage + partial import/retry/status, checksum/dimensions/provenance. | B-101 import slice | FR-101..103/106 acceptance, restart persistence, failure tests and NFR-103 signals. Not implemented. |
| B-103 | R1 | Minimal restricted admin API/tools; inspect, publish and unpublish; operator runbook and usable one-host package. | B-102 | SCN-101; unauthorized writes and unpublished reads denied; approved representative import. Not implemented. |
| B-104 | R2; prepare during R1 | Verify an existing IIIF Image server against actual files and S3; select software/versions and record ADR. | Q-102/106, representative files | info.json/full/region requests, resource bounds and publication gate proven. Cantaloupe is a candidate, not a locked dependency. FR-104. |
| B-105 | R2 | Generate local manifests/index; stable public IDs and source metadata; Corpusense browser/CORS integration. | B-103/104, Q-102 | Actual UI imports/displays pages; publication gates apply through image routes. FR-105, NFR-101/104. |
| B-106 | R2 | Existing real job reads local input; retain exact representation/provenance and prove coordinate export; restore representative collection. | B-105, actual job contract | SCN-102/103 and NFR-100/104; no scheduler/results rewrite. Not implemented. |
| B-107 | R3; contract/fixtures can start earlier | Gallica info/image proxy and bounded cache; origin/redirect validation; shared key/rate budget, miss fetching and freshness contract. | Q-104/105; reuse transport | FR-120/122..124 with isolated origin/storage failure and recovery evidence. Not implemented; old cache-only facade is partial reuse. |
| B-108 | R3 | Corpusense direct manifest fetch + transparent proxy routing for info/image requests; deploy/runbook/limited real smoke. | B-107, Q-102/104 | SCN-104/105; no backend Presentation proxy or manifest rewriting. Not implemented. |

R1/R2 form the first user-facing increment; R3 is urgent next. Avoid admin polish,
storage replatforming or general framework work between these milestones.

## Follow-ups — explicitly outside first delivery

| ID | Topic | Trigger / requirement retained |
|---|---|---|
| B-110 | User/project membership, private collection access, service-and-user delegation; proxy authentication/metering | Before private material or stronger user isolation; no claim that a user-scoped path independently proves authority. |
| B-111 | Worker egress isolation, internal-only inputs and controlled model download | Actual worker deployment/security work; preserve current submission interface. |
| B-112 | Multiple simultaneous S3 backends, project placement and progressive verified migration | Future necessary extension; retain stable logical IDs/location separation now. |
| B-113 | Processing representation selector: minimum size/scale, local ranking, exact-rendition option | Real OCR requirements and geometry; FR-108/109 provenance applies already. |
| B-114 | Temporary uploads/staging and result-retention changes | Actual task-system needs; not driven by whether users log in. No new tmp/results service now. |
| B-115 | Agentic discovery/processing/export interfaces | After real collection/proxy usage; reuse resource IDs and canonical provenance. |
| B-116 | Broader hardening and operations | Applicable unresolved legacy security findings, secret rotation, off-host backups, expanded failure/load tests, HA/replicas and metrics as usage requires. No production sign-off inferred. |

## Open implementation inputs

Each input has a decision deadline relative to the release; calendar dates are not
invented. Unknowns block only the dependent slice, not the entire pilot.

| ID | Question | Owner | Due | Status |
|---|---|---|---|---|
| Q-101 | First collection sample and import arrangement: file transport, document/page IDs/order, metadata supplied by BnF/operator? | Product owner + implementer | Before B-102 import contract | Awaiting representative sample/schema. Image files + CSV/JSON index is a candidate, not accepted format. |
| Q-102 | Where are Corpusense/current job code or sanitized requests? Which IIIF versions/routes and input/result fields do they already support? | Corpusense/job owner | Before B-104/105/106 or B-108 integration | Awaiting link/example; do not substitute worker-sim. |
| Q-103 | First host, public base URL, approved material, operator and restart/backup destination? | Operator + product owner | Before R1 exposure / R2 shared use | Public reads and restricted writes are accepted; concrete host/corpus not established by this pivot. |
| Q-104 | Actual BnF key delivery mechanism, permitted hosts/routes and quota documentation? | BnF contact + operator | Before credentialed R3 smoke | Higher-limit key expected, not assumed received; never store it in docs. |
| Q-105 | Proxy freshness/refresh policy, effective request key, info.json routing behavior and global rate/concurrency/wait/retry/cache budgets? | Implementer + Corpusense owner | Before B-107/108 acceptance | Choose finite settings from host and BnF contract; explicit response-varying context. |
| Q-106 | First file formats/sizes/page counts, supported geometry and software/license choice for IIIF? | Implementer + product owner | Before B-102/104 acceptance | Use representative samples; no promise of every TIFF/JPEG2000 variant. |

## Risks and boundaries

| ID | Risk | Required treatment |
|---|---|---|
| R-101 | Public access exposes unapproved/draft material or an image-server bypass | Restrict mutations; review test corpus; enforce publication on all reads; document unpublish/cache behavior. User login intentionally deferred, not an isolation claim. |
| R-102 | Cache/lifecycle cleanup deletes retained collection bytes | Separate retention/ownership; no legacy cache TTL/sweep over raw collections; test restart/restore and cleanup boundaries. |
| R-103 | Incorrect canonical match/coordinate export | Keep actual representation/dimensions and explicit mapping; expose unknown alignment. Same page/size does not establish equal pixels or bytes. |
| R-104 | Shared BnF key exhausted/leaked or proxy bypassed | Server-only secret, allowlist/redirect validation, bounded shared origin demand and cache; actual UI request evidence including info.json-derived URLs. |
| R-105 | Replatforming/generalization delays pilot again | One backend; selective reuse; no mandatory Supabase/alias/capability/HA redesign. Release by real UI/job acceptance. |
| R-106 | Prior evidence or unresolved vulnerabilities misrepresented | Preserve old reports/findings; review applicable deployed code/images/routes before exposure; do not relabel old tests as new acceptance. |
