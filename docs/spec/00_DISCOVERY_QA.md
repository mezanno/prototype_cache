# 00 - Discovery Q/A Intake

Use this file as the single narrative input.  
Write short prose answers under each question.  
If unknown, write `TBD`.

After this is filled, I will convert it into:

- `01_SCOPE.md`
- `02_REQUIREMENTS.md`
- `03_ARCHITECTURE_AND_DECISIONS.md`
- `04_OPERATIONS_AND_READINESS.md`
- `05_BACKLOG_AND_OPEN_QUESTIONS.md`

---

## A. Product And Scope Context

### Q1. What exact business problem does this storage/cache module solve?
**Current knowledge:** Provide durable image storage and retrieval for asynchronous processing workers in a larger app.


**Your answer:**
So, from a general point of view, I guess what I want is a generic SaaS framework which enables users to launch processings on data which is either fetched remotely or uploaded by themselves.
I though implementing the storage layer first makes sense, though it is maybe better to design the system globally to ensure every part fits. I tried hard to think about how to organize things step by step, but constructive criticism and help are really welcome here.

More specifically, this storage/cache is the pivot for all data coming into the platform, and maybe it can also be used to store intermediate and final results. For now it is more about processing images, but we may very well process textual content in a near future. We will have several public APIs.

The underlying storage system must be distributed to be fault tolerant and enable the agregation of storage from several servers.

### Q2. Who are the consumers of this module (systems/teams/services)?
**Current knowledge:** Main application backend, async worker services, ops/SRE, security/compliance stakeholders.

**Your answer:**
I have different services than need to communicate and store data reliably. Here is a quick overview of these services:

Services which mostly send data to the storage/cache:
- an **IIIF proxy** which will fetch images from remote heritage institutions (probably using specific IP addresses, auth tokens or others to avoid rate limiting), and store them in the current cache system.
- we also plan to **pre-load images** in the cache thanks to agreement with heritage institutions which sent us large batchs of images for which we know the public URL, so we do not have to download them (and saturate their servers)
- we also need to accept images sent directly by end-users who either use the web app or cli tools. In addition to submitting tasks with images referenced as URLs, they can also submit images as a base64 payload directly in the task submission, or use a dedicated upload service to store content in their personnal (or team) space. Hence there are two more modules which can submit data: **task API** and **upload API**

Services which read from this storage/cache:
- **worker** which assume data they have to process is available in this module, and cannot access Internet directly (maybe some security feature which prevent them from being able to read all storage content at any time could be nice to implement once first layers are ready)
- an eventual **web cache** which serves as a public replacement for unreliable heritage servers
- an **IIIF server** which can be used to publish user-uploaded images (which may also have a cache for rendered tiles)
- and finally **end-user tools** (web app or CLI) when they need to fetch results. In this case, the **workers may write results** to this global storage, eventually through some proxy.


### Q3. What is explicitly out of scope for this prototype?
**Current knowledge:** Image transformation/processing logic itself is out of scope.

**Your answer:**
I though the storage/cache should be a write-once storage, with very basic features.
Data processing is out of scope.
Task management in general is out of scope.
User APIs are out of score.
Remote URL fetching.
User authentication is out of scope for now, maybe it can be integrated later.


Admin API/UI is to be included here though.



### Q4. What does "prototype close to production grade" mean for you?
**Current knowledge:** Deployable, testable, monitored, and includes necessary operational features.

**Your answer:**
I want to validate as much as possible the feasability, then actually implement a production tool with all QA, security, etc.

---

## B. Ingestion Inputs

### Q5. Which ingestion modes must be supported in the prototype?
**Current knowledge:**  
- Direct file submission  
- Upload/import from private space  
- Remote URL submission

**Your answer:**
Actually, the URL fetching can be left out, as a dedicated service will handle this.
I just need 3 tools to be able to use this storage/cache:
1. a bulk data submission tool which will also act as a demo of the upload
2. a sample fetcher which will simulate a worker
3. a web management interface which enables to list, review, upload, update and remove resources

All authentication logic can be address in a later step.



### Q6. What file constraints should apply?
**Prompt:** max file size, allowed MIME types/extensions, image dimensions, virus/malware scanning expectations.

**Your answer:**
images can be large, but not extreme. I expect images less than 50 MB, with a common file size of 1-2 MB. They can have large dimensions, but this should not be considered here.
I also anticipate that we will have some PDF files which can be quite large (several GB).
Results, if we store them in this system, can have various sizes but are generally much smaller. They can be related to a particular group sometimes, like when a task generates several artifacts.
I want the caching/storage to be agnosting regarding content type, and virus/malware scanning should be performed at injestion time, which is out of scope of the current module.



### Q7. For remote URL ingestion, what controls are required?
**Prompt:** URL allow/deny policy, timeout, max download size, redirect policy, retries.

**Your answer:**
this feature will be implemented in another module

### Q8. What should happen on duplicate uploads?
**Prompt:** detect via checksum? reuse existing object? always create new asset?

**Your answer:**
this should be detected by the uploader based on how resources are organized.
I suggest we leave this for now, even if having the right metadata will certainly be useful in the future.


---

## C. Core Functional Behavior

### Q9. What are the minimal API capabilities for v1?
**Prompt:** create asset, get metadata, get worker access/read token, delete/expire asset, etc.

**Your answer:**
- create resource (asset): input are: payload (required), sub-bucket (?), keys or list of urls/abstract names/aliases (opt.), time-to-live (?), MIME type (?)
- read resource based on (sub-bucket)/UID or abstract name
- delete/expire resource
- get/set metadata (including access statistics?) – update time-to-live maybe part of this
- add alias / name / uri/url

As you can see, this is biased toward a particular implementation and can be helpfully criticized: I though about having a URL → binary blob logic with a `*-1` cardinality (a blob can have 0 or more URLs/aliases). This would have enabled an easy lookup of cached elements (my intial motivation until I realized this cache system could meybe be extended to a global storage system).

I also thought that internally, blobs can be organized under sub-buckets (like user_{userid}/uploads/… or project_{projectid}/results/task_{taskid}/…) but maybe this is bad separation.

Also, maybe upload can be progressive for large files.



### Q10. What lifecycle states are required for an asset?
**Prompt:** e.g. received, validating, stored, available, failed, expired, deleted.

**Your answer:**
I did not think deeply about this. I'd like to keep this as simple as possible.
What I thought about was that assets can be expired or not, but having the ability to deal with non-atomic transfer is interesting. I do not know whether it will be necessary though.


### Q11. What idempotency behavior is required?
**Prompt:** idempotency key scope, replay semantics, conflict behavior.

**Your answer:**
assets UID should be generated automatically, but we should not be able to assign an alias/url to a blob unless it is not already assigned.



### Q12. What metadata is mandatory?
**Prompt:** tenant/user id, source type, checksum, mime type, size, retention, timestamps.

**Your answer:**
maybe ownership / rights can be managed differently based on aliases/url, in a layer of higher abstraction which may be able to check who has the right to read what depending on the alias of the resource which is requested.

Again, this is very opinionated from me, as I have in mind something with 3 layers:
1. low-level storage using an S3-compatible system (local & distributed like minio or distant)
2. an asset-management level with a metadata db which tracks accesses and provides the asset api
3. (probably to be considered later) an access right management layer which checks who can read what and when



---

## D. Non-Functional Requirements

### Q13. Availability and durability targets?
**Prompt:** SLO target(s), acceptable data loss objective, backup/restore expectations.

**Your answer:**
I should be able to backup regularly to another similar storage, maybe with a storage class betted suited for less frequent access or achival. Being able to do it incrementally would be great. I did not think about this before and may be implemented fully after the core principles are validated. 



### Q14. Performance targets?
**Prompt:** ingestion ack latency, read latency for workers, throughput expectations.

**Your answer:**
I'd like things to run smoothly with 1 TB of assets and about 10 users and 30 workers accessing the system concurrently. High scalability is not required for now, but may be useful in the future.


### Q15. Scale expectations (12-18 months)?
**Prompt:** requests/day, peak RPS, data growth per month, object count projections.

**Your answer:**
Approx. 1000 requests per day. Low object growth at the beginning, but probably 10 GB/month the first year. 


### Q16. Cost constraints?
**Prompt:** hard budget caps, cost per GB or per request guardrails, optimization priorities.

**Your answer:**
No clear plan here for now. S3 storage cost are sustainable based on our first estimates.

---

## E. Security And Compliance

### Q17. Authentication/authorization model?
**Prompt:** service-to-service auth, user-scoped auth, worker permissions model.

**Your answer:**
Let us deal with this in a second stage, but I thought about this:
- upload services have general write permissions (maybe not general read, only existence check) and some ACL-enforcement layer checks the permission of the original request before actually creating the resource
- workers could be given temporary tokens or pre-signed/transient aliases (urls) for resources so they cannot access everything (and could not list resources anyway)
- worker can commit a structured set of assets for a given task run
- I'd like to support anonymous (public), user and project level rights, and admin rights at the asset level
- at low level, if we use buckets, general write/read permissions at service level

### Q18. Encryption and key management requirements?
**Prompt:** at rest/in transit, customer-managed keys, key rotation policies.

**Your answer:**
- no need for encryption at rest for now, this can be left of a future improvement (to be noted)
- in-transit data should be encrypted using HTTPS if using this endpoint, but if using another more efficient protocol this would be better indeed
- once we are within the cluster, inter container communication is already secured, so this should not be a big issue

### Q19. Compliance constraints?
**Prompt:** GDPR, SOC2, data residency, retention/deletion legal requirements.

**Your answer:**
no requirements for now, but setting specific expiration delays seems a good starting point — actually managing a very simplified form of asset lifeycle


### Q20. Auditability requirements?
**Prompt:** which actions must be auditable and retention duration of audit logs.

**Your answer:**
- creation and modification of metadata (except access) should be logged
- access should be logged separately, and probably agregated over time, to determine least-frequently accessed assets, in the case we need to free some space and identify cached/expired items
- when adding the ACL-enforcement, then all accesses should be logged for a short period of time (a month at most) especially to debug worker auth issues


---

## F. Operations, Testing, And Delivery

### Q21. Target deployment model?
**Prompt:** k8s/serverless/VM, environments needed, rollout strategy.

**Your answer:**
- docker swarm for now (we need to move to k8s but it is not ready yet)
- no particular environment requirement, though the team is used to Python, but maybe other solutions can be better
- unsure about how to handle rollout properly here if we have only 1 main process



### Q22. Observability baseline for day 1?
**Prompt:** key metrics, logs, traces, dashboards, alerting expectations.

**Your answer:**
- requests per second/minutes/hour/etc.
- most frequently accessed assets
- creation logs
- everything I need to check data injestion works and sample workers can do their work, and identify who fails


### Q23. Testing expectations?
**Prompt:** required unit/integration/e2e/load tests before considering prototype ready.

**Your answer:**
- unit testing is important
- need to define scenarios and mock services for testing integration
- load measurement are a plus



### Q24. Failure handling expectations?
**Prompt:** retries, DLQ behavior, timeout policy, partial failure compensation.

**Your answer:**
- I want to log failures had have an alterting system (probably using standard tools that I expect you to suggest)
- but I expect the storage to fail only on very very rare occasions (hardware/network failure, full disks…) this should stop current operations


### Q25. What are hard go-live gates for this prototype?
**Prompt:** mandatory checks before pilot/adoption.

**Your answer:**
- data model works for our use-cases
- deployment is ready using docker swarm (tested using docker compose)
- integration tests for target scenarios pass
- basic monitoring is running and working


---

## G. Technology And Decision Boundaries

### Q26. Any technology constraints or preferences?
**Prompt:** cloud provider, storage tech, language/runtime, database constraints.

**Your answer:**
no hard constraint, but I was thinking about S3 hosting (local & distributed or cloud), local database(s) for metadata (unsure about how to track accesses), not sure for logging/auditing, maybe Python because of team experience but other stacks may be much more efficient.
Important: if existing, mature and open-source tools already implement these features, I'd prefer to use them.



### Q27. What decisions are already fixed vs still open?
**Prompt:** list `Fixed` and `Open`.

**Your answer:**
fixed: I need a common layer of storage for my application stack
fixed: I need a caching system for images that are fetched and processed several times
fixed: I need to be able to store user uploads and results

the rest is open



### Q28. Any external systems this module must integrate with?
**Prompt:** auth services, event bus, metadata systems, tenant management.

**Your answer:**
None of them yet, we start the stack redesign with the storage level, unless you think this is a bad idea.


---

## H. Prioritization

### Q29. What is P0 (must-have) for first deliverable?
**Your answer:**
ability to store and cache 500+ GB of image


### Q30. What is P1 (important but can follow)?
**Your answer:**
ability to deal with user uploads and processing results


### Q31. What is explicitly deferred (P2+)?
**Your answer:**
authentication / access control

---

## I. Immediate Open Questions (From Current Knowledge)

These are currently unresolved and should be answered early:

1. Which ingestion mode(s) are strictly required for first prototype cut?
2. What are concrete size/type/security limits for incoming images?
3. What are target scale and latency numbers?
4. What are the required auth and compliance constraints?
5. Which deployment environment and operational toolchain should be assumed?
