# M-001 private pilot package (ADR-032)

Start with the short [deployment/task quickstart](../../docs/PILOT_QUICKSTART.md).
The [local v3/WebP deployment record](LOCAL_DEPLOYMENT.md) captures the running
candidate, live smoke/restart results and remaining release gates.

Separate from the development Compose project. One process each for asset-store,
fetcher and scheduled lifecycle, with Postgres and Garage persistent volumes.
B-003/B-019 / FR-050/064/068; this delivers packaging, not deployment sign-off.
No stack is started by configuration validation. Preflight/configuration tests
require a Docker Compose plugin supporting `config --format json` and
`--no-env-resolution` (locally verified with v5.2.0); they need no daemon access.

## Required operator selections

Before deployment, record the host/operator, private tunnel or VPN access,
reviewed image digests, approved Gallica corpus, RAM/disk allocation and backup
location. Existing implementation baseline is Garage v1.0.1 and Postgres 16;
use reviewed digests for those versions before attempting any backend upgrade.
The app image must contain this repository checkpoint and migration 0003.
For this local host, build it with `deploy/Dockerfile` and set `PILOT_APP_IMAGE`
to its immutable image ID (`docker image inspect <build-tag> --format '{{.Id}}'`).
No registry publication is required (ADR-033). Record the source commit, image ID
and resolved build input digests. For a registry image, record its digest after publishing
through the operator's authorized release process. Do not deploy a mutable tag. Application services use `pull_policy: never`;
explicitly pull a selected registry app image before startup.
The Dockerfile pins dependencies via `uv.lock`; base/build image digest locking
and image scan review remain release gates. No images are downloaded or published
by the preflight checker.

Proposed default envelope: 1 GiB cache, 64 MiB tmp, 1 MiB each users/results,
50 MiB objects, two concurrent fetch/read jobs and uploads, bounded pools,
1,000 local capabilities and 120 mint attempts/minute with burst 20. Each service
has memory/CPU/PID limits; application scratch space is 64 MiB. Main services
budget about 2.3 GiB RAM, plus the host and maintenance/migration overhead: select
a host with at least 4 GiB available RAM before acceptance. These are initial
settings, not measured capacity certification. Use the same byte budgets for
API and lifecycle; review changes before raising the envelope.

Named volumes do **not** limit disk usage. Before deployment, provision host
filesystem/disk quotas and reserve headroom for Garage metadata, Postgres audit
history, backups and bounded Docker logs (10 MiB × 3 files per service). Lifecycle
capacity estimates bound admitted payloads, not the entire host disk. Audit
retention, disk monitoring and backup/restore remain P5 work.

## 1. Prepare protected runtime files

From the repository root:

```bash
umask 077
mkdir -p deploy/pilot/private
cp deploy/pilot/pilot.env.example deploy/pilot/private/pilot.env
cp deploy/pilot/garage.toml.example deploy/pilot/private/garage.toml
cp deploy/pilot/postgres.env.example deploy/pilot/private/postgres.env
cp deploy/pilot/asset.env.example deploy/pilot/private/asset.env
cp deploy/pilot/fetcher.env.example deploy/pilot/private/fetcher.env
chmod 600 deploy/pilot/private/*
```

Edit every placeholder. `pilot.env` contains digest image references and absolute
paths to the four protected files. Generate distinct random database, RPC,
Garage-admin and service secrets (for example, 32 random bytes encoded as hex).
Keep database passwords URL-safe or percent-encode them in the DSN. Env files use
literal `NAME=value` lines; do not use shell substitutions or `$` expansions.
The asset env holds the provisioned S3 key and the `fetcher`, `task-api`, `admin`
credentials. The fetcher env contains only dispatcher credentials and its own
asset-store fetcher secret. Matching identities use the same secret in both
files; different identities must have different secrets. Never use dev defaults.

`private/` is ignored by Git and excluded from the Docker build context. Protect
its parent directory with mode 700. Docker administrators remain trusted and can
inspect container environment credentials; these files are not a vault. Protect
backups of runtime files. Do not print `docker compose config`, `docker inspect`
or key-create output into shared logs: they may contain credentials.

Garage's single-node RPC address is loopback inside its container, following the
existing tested development topology; it is not a host-exposed RPC service.
Only the Garage CLI inside the container manages layout/keys. Its S3 and admin
ports and all Postgres ports remain unpublished.

## 2. Provision backends and migrate

Use this helper for all commands, from the repository root:

```bash
pilot() {
  docker compose --env-file deploy/pilot/private/pilot.env -f deploy/pilot/compose.yml "$@"
}
pilot config --quiet
pilot up -d garage postgres
pilot exec -T garage /garage status
```

For a fresh Garage node only, obtain its node id with
`pilot exec -T garage /garage node id -q`. Assign that id to the one-node layout
using `pilot exec -T garage /garage layout assign -z pilot -c 1G <node-id>` and
`pilot exec -T garage /garage layout apply --version 1`. Review the layout first;
do not apply these initialization commands to existing storage blindly.
Create `cache`, `tmp`, `users`, `results` buckets with `/garage bucket create`.
Create the pilot key once and capture its output to a protected local file:

```bash
pilot exec -T garage /garage key create asset-store-pilot > deploy/pilot/private/garage-key.txt
```

Copy the generated access id and secret into `asset.env`. Grant read/write for
all four buckets using `/garage bucket allow --read --write <bucket> --key <key-id>`;
the runtime key does not need owner permission. Never use the dev init script
or fixed dev key. On an existing node inspect keys/buckets first; reuse the
provisioned key instead of making duplicates. Review the
[Garage operations documentation](https://github.com/deuxfleurs-org/garage/tree/main-v2/doc/book/operations)
for administration; commands here follow the tested v1.0.1 repository baseline.

Once credentials are filled:

```bash
.venv/bin/python deploy/pilot/check_config.py deploy/pilot/private/pilot.env
pilot run --rm migrate
pilot up -d asset-store fetcher
pilot ps
```

The checker parses Compose configuration without exposing its output. It checks
image digests, protected file modes, loopback ports, durable endpoints, byte
budgets, matching credentials and migration/lifecycle policy. It does not test
credential validity against live services or scan images. Both APIs wait for
migration success and backend health; do not stamp an unverified legacy schema.
Existing databases need the [migration runbook](../../docs/services/lifecycle-worker.md#runbook).
The default app factory still verifies/bootstraps tables; the explicit migration
gate prevents relying on that as the pilot upgrade procedure.

## 3. HTTP acceptance and private access

Only host-loopback API ports are published: asset-store/admin/metrics at
`127.0.0.1:18000`, fetcher at `127.0.0.1:18001`. Tunnel these ports over SSH for
remote testers; service authentication is still required. TLS/private ingress
outside the tunnel must be configured and reviewed separately. No public exposure
is authorized by this package. Keep metrics access private.

Run the [HTTP smoke script](../../tools/cache-pilot/README.md) with
`CACHE_PILOT_BASE_URL=http://127.0.0.1:18001` and an approved Gallica image URL.
Record the checksum and repeat-hit result. The script can fetch once on a miss.
Check `/readyz`, `/metrics`, and authenticated `/admin` on asset-store; browser
visual/interaction acceptance remains required. Check that `/v1/ensure-url` is
absent from fetcher OpenAPI and anonymous cache requests return 401.

For restart acceptance, run smoke, record checksum/asset identity, then restart
Postgres/Garage/asset-store/fetcher with `pilot restart postgres garage asset-store fetcher`.
Wait for health before rerunning smoke: it must report an initial cache hit and
identical checksum. Also restart asset-store alone while leaving fetcher running
and verify the next cached read renews its internal capability. Record the actual
container results; local test fixtures are not substitutes for this evidence.
`/readyz` is a startup health signal, not continuous origin/backend certification.

## 4. Review cleanup, then schedule it

After reviewing the lifecycle policy and expiry behavior:

```bash
pilot run --rm --no-deps lifecycle python -m asset_store_core.lifecycle --dry-run
# Starting this profile applies expiry/deletion and evicts cache under pressure.
pilot --profile maintenance up -d lifecycle
pilot logs --tail 30 lifecycle
pilot exec -T lifecycle cat /tmp/lifecycle.prom
```

The worker applies one sweep every 60 seconds. It shares API budgets/credentials,
logs failures/audited transitions and writes existing Prometheus textfile metrics
to bounded scratch storage. Metrics reset after restart and the file is not yet
wired into a collector (P5). Stop scheduling with `pilot stop lifecycle`; review
errors before retrying. Pressure eviction can remove cached images, after which
explicit preload is required again. Do not enable scheduled apply before dry-run
review. The default `up` excludes this maintenance profile.

## Acceptance remaining

This package is validated by real Compose rendering and negative preflight tests.
No fresh-host deployment was performed for this checkpoint. Required P4 evidence:
reviewed/scanned image digests; actual host budgets and credentials; fresh startup;
real-network smoke; container restart; admin browser check; private access review.
P5 adds monitoring, audit retention, backup/restore and rollback rehearsal; P6 adds
live corpus and soak acceptance. Do not run `down -v` on retained pilot data.

## Optional task worker

The local task workflow uses the existing `worker` role, provisioned only in
asset-store credentials. Preflight permits it as an optional fourth identity;
fetcher still authenticates only task-api/admin dispatchers. The local host sets
`PILOT_RESULTS_CAPACITY_BYTES=67108864` (64 MiB); cache-only defaults remain 1 MiB.
API, migration and lifecycle share this budget. See the quickstart for the
verified simulator example and real-worker integration sequence.

## Recovery rehearsal

The 2026-10-05 [coherent cold backup and isolated restore](../../docs/BACKUP_RESTORE_REHEARSAL.md)
passed for the local pilot (ADR-037). Use the recorded ordering, fresh volume and
network isolation checks, pinned backend versions, table fingerprints and payload
checksums for subsequent rehearsals. Daily/off-host backup scheduling and retention
remain open; this evidence is not an online/PITR backup implementation.

## Task 3 local operation

[CLI monitoring and retention](../../docs/TASK3_OPERATIONS.md) documents ADR-038,
the installed minute monitor and enabled 60-second lifecycle worker. Read
`private/monitor.json`; check its timestamp for freshness. Audit/backups retained
without automatic deletion. Docker disk headroom is near 10% free.
