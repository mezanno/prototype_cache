# Project Architecture

## Platform overview

```mermaid
flowchart TB
  subgraph platform [Platform services]
    Fetcher[fetcher_service]
    UploadAPI[upload_api]
    TaskAPI[task_api]
    Worker[worker]
  end
  subgraph assetstore [asset_store repo]
    Guard[storage_guard]
    Registry[asset_registry]
  end
  subgraph minio [MinIO]
    cache[cache]
    tmp[tmp]
    users[users]
    results[results]
  end
  Fetcher --> Guard
  UploadAPI --> Guard
  TaskAPI --> Fetcher
  TaskAPI --> Guard
  Worker --> Guard
  Guard --> Registry
  Guard --> minio
```

| Concern | Module |
|---------|--------|
| Bytes, aliases, lifecycle | **asset-store** (this repo) |
| Remote URL → cache/tmp | **fetcher-service** ([`spec/07_FETCHER_SERVICE.md`](spec/07_FETCHER_SERVICE.md)) |
| User files | upload-api → `users` |
| Task outputs | worker → `results` |

## Scope Of This Module

The `asset-store` module (repo: `prototype_cache`, to be renamed at code time) provides durable, multi-tenant asset ingestion and retrieval. It does **not** run image processing, **does not fetch remote URLs** ([`ADR-008`](spec/03_ARCHITECTURE_AND_DECISIONS.md)), does **not** serve IIIF, and does **not** manage end-user authentication.

Storage layout: [`spec/03_ARCHITECTURE_AND_DECISIONS.md`](spec/03_ARCHITECTURE_AND_DECISIONS.md) (buckets `cache`, `tmp`, `users`, `results`). Terms and acronyms: [`spec/00B_GLOSSARY_AND_ACRONYMS.md`](spec/00B_GLOSSARY_AND_ACRONYMS.md).

## Internal Layers

1. **`object-store`** (layer 1) — MinIO; four buckets; keys `{partition_id}/assets/{asset_id}`.
2. **`asset-registry`** (layer 2) — `asset_id`, aliases, `space`, `partition_id`, lifecycle.
3. **`storage-guard`** (layer 3) — capabilities, service auth, bucket allowlists ([`FR-015`](spec/02_REQUIREMENTS.md)), audit.

## Tooling Shipped With The Module

- **`admin-ui`**, **`bulk-loader`**, **`worker-sim`** — see [`spec/00A_SCENARIOS.md`](spec/00A_SCENARIOS.md).

## Suggested Repository Layout

```text
prototype_cache/
  docs/
    PROJECT_ARCHITECTURE.md
    spec/
      README.md
      00B_GLOSSARY_AND_ACRONYMS.md
      01_SCOPE.md
      07_FETCHER_SERVICE.md
      00A_SCENARIOS.md
      ...
  services/
    asset-registry/
    storage-guard/
  tools/
    bulk-loader/
    worker-sim/
```

Fetcher may live in a separate repo later; contract is in `spec/07_FETCHER_SERVICE.md`.

## Core Data Flow (write)

```mermaid
flowchart LR
    Client["Client upload_api bulk_loader fetcher"]
    Guard["storage_guard"]
    Registry["asset_registry"]
    Object["object_store bucket plus key"]

    Client -->|"1 write capability"| Guard
    Guard -->|"2 reserve pending"| Registry
    Guard -->|"3 presigned PUT"| Client
    Client -->|"4 PUT bytes"| Object
    Client -->|"5 commit"| Guard
    Guard -->|"6 available"| Registry
```

## Core Data Flow (read)

```mermaid
flowchart LR
    Worker["Worker"]
    Guard["storage_guard"]
    Registry["asset_registry"]
    Object["object_store"]

    Worker -->|"1 resolve alias"| Guard
    Guard -->|"2 asset_id plus bucket key"| Registry
    Guard -->|"3 presigned GET"| Worker
    Worker -->|"4 GET bytes"| Object
```

## Remote URL flow (fetcher, not asset-store)

See sequence diagram in [`spec/07_FETCHER_SERVICE.md`](spec/07_FETCHER_SERVICE.md).

## Non-Functional Targets (Baseline)

See [`spec/02_REQUIREMENTS.md`](spec/02_REQUIREMENTS.md): capacity, read latency, durability, deployability.
