# Deploy and use the local cache pilot

## 1. Deployment

The pilot currently runs on this machine:

- Cache API and interactive docs: http://127.0.0.1:18001/docs
- Asset-store API: http://127.0.0.1:18000/docs
- Admin console: http://127.0.0.1:18000/admin

From the repository root, define:

```bash
pilot() {
  docker compose --env-file deploy/pilot/private/pilot.env -f deploy/pilot/compose.yml "$@"
}
```

For a fresh deployment, build the app image with `deploy/Dockerfile`, record its
immutable image ID, and prepare credentials, pinned backend images and Garage
buckets using [the deployment runbook, sections 1–2](../deploy/pilot/README.md).
The existing `private/` files belong to this host; do not replace them on restart.
Then validate and start:

```bash
.venv/bin/python deploy/pilot/check_config.py deploy/pilot/private/pilot.env
pilot run --rm migrate
pilot up -d asset-store fetcher
pilot ps
```

Stop with `pilot stop`; resume with `pilot up -d asset-store fetcher`.
Volumes persist. Do not use `down -v` to stop the service.
Remote access can use an SSH tunnel:

```bash
ssh -L 18000:127.0.0.1:18000 -L 18001:127.0.0.1:18001 user@pilot-host
```

Credentials are in protected `deploy/pilot/private/asset.env` and `fetcher.env`.
The admin UI takes only the admin secret. API headers use
`Authorization: Service <identity>:<secret>`. Keep files/secrets private.

## 2. When a task arrives

1. **Preload inputs:** call fetcher `POST /v1/cache/preload` with `{"url": "..."}`
   as `task-api`. Save the returned `qualified_alias` and `asset_id`.
2. **Describe inputs:** resolve the alias at asset-store `GET /resolve?space=cache&alias=<relative-alias>`
   as `task-api` to get the stored checksum. Pass alias/checksum to your worker.
3. **Read and process:** the worker mints a read capability for each input alias,
   downloads through `GET /objects/<qualified-alias>` with
   `Authorization: Capability <token>`, verifies SHA-256, then runs your code.
4. **Write results:** mint a worker write capability scoped to
   `results/<user>/<task>/<attempt>/<worker>`. Upload each output with
   `PUT /objects/<qualified-result-alias>`, its MIME type and expected checksum.
5. **Publish completion last:** upload `manifest.json` listing output aliases and
   checksums only after every output succeeds. Treat the manifest as completion.

A cache-only read miss is 404: preload explicitly. Do not refetch during every
worker read. Results are immutable; use a fresh attempt prefix after failure and
inspect any existing manifest before retrying an uncertain final response.

**Available today:** cache, capabilities, result storage and the worker simulator.
Your scheduler and processing/OCR code remain external. The simulator below
copies input bytes; it demonstrates the protocol, not actual OCR.

### Test the legacy/current JPEG pair

Preload either URL, then preload the other; the second call must be a cache hit
with the same `asset_id` and `qualified_alias`:

- Legacy: <https://gallica.bnf.fr/iiif/ark:/12148/bpt6k9907264/f7/full/full/0/native.jpg>
- Current v3: <https://openapi.bnf.fr/iiif/image/v3/ark:/12148/bpt6k9907264/f7/full/max/0/default.jpg>

Authenticated cached reads are available at:

- <http://127.0.0.1:18001/gallica.bnf.fr/iiif/ark:/12148/bpt6k9907264/f7/full/full/0/native.jpg>
- <http://127.0.0.1:18001/openapi.bnf.fr/iiif/image/v3/ark:/12148/bpt6k9907264/f7/full/max/0/default.jpg>

Both return the same stored v3 JPEG. Cold fetches use v3 because the old API is
unstable. The two downloaded origin encodings are not byte-identical; this is
an approved shared resource with a canonical representation.
For the Python example below, you can replace `url` with either JPEG URL.
Browser links still require the service authorization header; use the interactive
cache API docs or an authenticated HTTP client to test.

## 3. Runnable cache → worker → results demonstration

This host has a distinct `worker` identity and a 64 MiB results budget. A fresh
cache-only deployment can add `worker:<distinct random secret>` to the asset
credential list and set `PILOT_RESULTS_CAPACITY_BYTES=67108864` in `pilot.env`,
then validate and recreate asset-store. Never give a worker the admin secret.

Run this from the repository root. It reads local protected credentials without
printing them, preloads the owner-approved v3 image, resolves its checksum and
runs the existing simulator through HTTP:

```python
from pathlib import Path
import sys, uuid
import httpx

sys.path.insert(0, "tools/worker-sim")
from worker_sim import Task, run_task

env = dict(line.split("=", 1) for line in
           Path("deploy/pilot/private/asset.env").read_text().splitlines()
           if line and not line.startswith("#") and "=" in line)
secrets = dict(item.split(":", 1) for item in
               env["ASSET_STORE_SERVICE_CREDENTIALS"].split(","))
url = "https://openapi.bnf.fr/iiif/image/v3/ark:/12148/bd6t543024772/f18/full/max/0/default.webp"
auth = {"Authorization": "Service task-api:" + secrets["task-api"]}
with httpx.Client(timeout=90, trust_env=False) as http:
    response = http.post("http://127.0.0.1:18001/v1/cache/preload",
                         json={"url": url}, headers=auth)
    response.raise_for_status()
    alias = response.json()["qualified_alias"]
    space, relative = alias.split("/", 1)
    response = http.get("http://127.0.0.1:18000/resolve",
                        params={"space": space, "alias": relative}, headers=auth)
    response.raise_for_status()
    checksum = response.json()["checksum"]
prefix = f"results/demo/task-1/{uuid.uuid4().hex}/worker-1"
task = Task(inputs=[{"alias": alias, "checksum": checksum}], result_prefix=prefix)
with httpx.Client(base_url="http://127.0.0.1:18000", timeout=90, trust_env=False) as http:
    report = run_task(http, task, service_secret=secrets["worker"])
if report.status != "ok" or not report.manifest_written:
    raise RuntimeError(report.error or "manifest was not published")
print("Completed:", prefix + "/manifest.json")
```

Save as a local file and run with `PYTHONPATH=src .venv/bin/python <file>`.
Inspect the resulting artifacts/manifest in the admin console. For a real task,
replace the simulator's copy step with your processing implementation, retaining
scoped capabilities, verified inputs and manifest-last result publication.
See [the worker protocol](services/worker-sim.md) for request details.

Default object cap is 50 MiB; budgets count retained results across tasks. Inspect
usage and review budget/retention changes before larger runs. Scheduled cleanup
is currently disabled. Browser login/asset listing was confirmed by the owner;
scans, recovery rehearsal, broader UI checks and soak acceptance remain pending.
