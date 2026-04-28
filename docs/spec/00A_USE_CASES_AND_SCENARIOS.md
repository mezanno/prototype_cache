# 00A - Use Cases And Scenarios

Goal: define concrete behaviors before finalizing requirements.

How to use:
- Keep each scenario short and testable.
- Mark unknowns as `TBD`.
- Prefer observable outcomes (status, state change, logs, metrics).

---

## 1) Actor Catalog

- **Bulk loader**: preloads known assets in volume.
- **Upload API**: sends user-provided files into storage.
- **Task API**: registers references and retrieves assets for processing workflows.
- **Worker**: reads processing input and may write artifacts/results.
- **Admin UI/API**: lists and manages resources.
- **IIIF proxy**: fetches remotely and writes into storage module (or through dedicated fetch service).
- **IIIF server**: reads images in user- or team/projec-storage and generates tiles views and manifests, caching tiles and manifests in a dedicated storage area if needed

when core layers are ready, we may add new actors:
- **authentication service**: stores permissions about who can access which resource
- **storage guard**: (if separated from core storage management) checks that each resource is only accessed, modifier or created in a particular storage space by an authorized user. Also populates audit logs.


---

## 2) Scenario Template

Copy/paste this block for new scenarios:

```md
### SCN-XXX - <short title>

- **Priority:** P0 / P1 / P2
- **Actors:** ...
- **Preconditions:** ...
- **Trigger:** ...
- **Main flow:**
  1. ...
  2. ...
  3. ...
- **Expected result:** ...
- **Error/failure paths:** ...
- **Observability checks:** metrics/logs/traces to verify
- **Open questions:** ...
```

---

## 3) Initial Scenarios (Prefilled From Current Knowledge)

### SCN-001 - Bulk preload image set

- **Priority:** P0
- **Actors:** Bulk loader, storage API
- **Preconditions:** Source manifest prepared; storage service available
- **Trigger:** Operator runs bulk submit tool
- **Main flow:**
  1. Bulk loader submits N assets with payload and metadata.
  2. Service stores blobs and records metadata.
  3. Service returns created asset identifiers.
- **Expected result:** Assets are readable by worker fetch path.
- **Error/failure paths:** Partial ingest failure, oversized file, invalid payload
- **Observability checks:** ingest success rate, per-asset failure count, write latency
- **Open questions:** batch transactional semantics? max batch size?

### SCN-002 - Worker reads asset for processing (simple task with existing resource)

- **Priority:** P0
- **Actors:** Worker, storage read API
- **Preconditions:** Asset exists and is not expired/deleted
- **Trigger:** Worker requests an asset by id/alias
- **Main flow:**
  1. Task management requests a single-use (or short-lived) authorization either in the form of an authorization token, or of a new alias with specific permissions, given the original user- or team/project id the request comes from
  2. Service validates request (auth model TBD).
  3. Service returns token or signed URL to task manager, for read only access.
  4. Task management requests a result storage for a particular task/attempt
  5. Service declare appropriate rights and generates an authorization for the result space with write permissions
  6. Task management finalizes task definition for workers using input and output aliases and authorizations
  4. A worker is eventuelly spawned and receives task definition with a list of input assets and an output prefix
  5. The worker fetches resources, using authentication information provided (protocole TBD)
  6. Once processing is complete, the worker commits result artifacts to the appropriate space (results/taskid/attemptid/workerid/...)
- **Expected result:** Worker retrieves content reliably, Worker can write results reliably
- **Error/failure paths:** missing asset, expired asset, transient storage read failure, failed task and multiple attempts
- **Observability checks:** read latency, read error rate by cause
- **Open questions:** direct stream vs signed URL default? Differences between inputs and outputs?


### SCN-003 - Task registration with a reference to a remote URL
The role of the IIIF proxy is to ensure that required resources are present in storage before workers are actually triggered.
The IIIF proxy contains the logic about what are the differents URLs that can be used to fetch a resource, and therefore what are the aliases that a resource can have.
- **Preconditions:** valid task request with remote URL, valid URL
- **Trigger:** Task manager needs to ensure remote resource is fetched before triggering workers
- **Main flow:**
  1. The IIIF proxy derives from the URL the set of possible URLs to fetch, with an ordering, and checks whether any of these are aliases for a resource is already present in storage. If present, then the flow exits immediatly with success.
  2. If the resource must be fetched, then the IIIF proxy asks the storage guard for an authorization to create a new resource with specific aliases
  3. storage guard grants a time-limited, write-only permission for a set of resources, and mark them as "pending upload" (or other better status)
  4. IIIF proxy triggers a fetching worker to actually download the resource, with details about how to send the resource to the storage (aliases, authorization).
  5. A fetch worker eventually runs the fetch task, complying with download rates, IIIF authorizations (we may download the image on behalf of a end user, forwarding its authorization token) and restrictions.
  6. If the fetch worker manages to retrieve the only resource, it submits the payload to storage using appropriate aliases and authorizations.
  7. Upon failure, pending upload may be discarded (exact behavior TBD, depending on all possible cases)
- **Expected result:** resource cached in storage
- **Error/failure paths:** fetch failure, inconsistent aliases (two aliases for the same resource pointing to different binary blobs), bad authorization for IIIF proxy (read) or fetcher workers (specific writes)
- **Observability checks:** cache hits/failures, data transfer saved, fetch errors, resource hits
- **Open questions:** IIIF proxy needs dedicated workers (some with specific IPs, some with special authorizations) to be able to fetch from remote heritage institutions. Its actual implementation is left for future work.

check whether URL is already cached > if yes, move on to SCN-002, if no, fetch resource.
To fetch resource, the following actions are performed.
1. The Task manager receives a "not found" reply from the storage service regarding the online resource. How
2. 







### SCN-003 - User upload through Upload API

- **Priority:** P1
- **Actors:** Upload API, storage API
- **Preconditions:** Upload API validates user request
- **Trigger:** User uploads an image/binary through upstream API
- **Main flow:**
  1. Upload API sends payload + metadata to storage module.
  2. Storage module persists object and metadata.
  3. Storage module returns canonical asset id.
- **Expected result:** Upload API can reference the stored asset in business workflows.
- **Error/failure paths:** invalid metadata, timeout during transfer
- **Observability checks:** upload throughput, failed upload causes
- **Open questions:** should storage enforce MIME/size constraints or trust caller?

### SCN-004 - Admin lifecycle operation

- **Priority:** P1
- **Actors:** Admin UI/API, storage API
- **Preconditions:** Asset exists
- **Trigger:** Admin lists resources then updates metadata/TTL or deletes one
- **Main flow:**
  1. Admin lists resources with filters.
  2. Admin inspects metadata.
  3. Admin performs lifecycle action (expire/delete/update metadata policy).
- **Expected result:** Resource state changes are durable and auditable.
- **Error/failure paths:** concurrent update, protected asset deletion blocked
- **Observability checks:** admin action audit logs, state transition counters
- **Open questions:** what is mutable if storage is write-once?

### SCN-005 - Worker writes result artifacts

- **Priority:** P1
- **Actors:** Worker, storage API
- **Preconditions:** Processing task completed
- **Trigger:** Worker submits one or many output artifacts
- **Main flow:**
  1. Worker uploads outputs.
  2. Service associates outputs with task/job metadata (or alias namespace).
  3. Service returns ids/locations for downstream consumers.
- **Expected result:** Outputs can be fetched by user tools or downstream services.
- **Error/failure paths:** group upload partial failure
- **Observability checks:** artifact write success rate, grouped write consistency
- **Open questions:** atomicity required for grouped artifacts?

---

## 4) Cross-Scenario Decisions To Lock Early

1. **Identifier model:** immutable `asset_id` + optional aliases?
2. **Mutability model:** strict write-once vs metadata updates allowed?
3. **Read interface:** proxy stream, signed URL, or both?
4. **Retention model:** default TTL, overrides, hard-delete policy
5. **Large object strategy:** multipart upload and resumable transfer
6. **Scope boundary:** does storage module fetch remote URLs or never?

---

## 5) Acceptance Mapping Draft

Use this later to link scenarios to requirements:

| Scenario | Primary FR IDs | Primary NFR IDs | Test Type |
|---|---|---|---|
| SCN-001 | TBD | TBD | Integration |
| SCN-002 | TBD | TBD | Integration |
| SCN-003 | TBD | TBD | Integration |
| SCN-004 | TBD | TBD | Integration |
| SCN-005 | TBD | TBD | Integration |
