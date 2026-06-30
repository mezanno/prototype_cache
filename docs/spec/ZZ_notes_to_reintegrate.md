# Various unstructured notes which we have to reintegrate in the formal specs

## Important notes

### Object lifecycle support
Garage lacks support for object lifecycle management which is available (beta) in RustFS, and in cloud S3 services (OVH, AWS)

### Bucket structure and Garage limitations
Garage has an annoying limitation: it does not shard buckets, so having few buckets of uneven size will imbalance storage usage on the various nodes (if we have more notes that requested number of replicas).
- garage buckets are geo-replicated, not sharded!
This raises the question of which physical structure the storage should have. We assume we should be able to choose the region of the storage to be able to switch easily, but within a region the structure of buckets / partitions could either be:
A. service-like at bucket level (like cache, user private data, temporary inputs, results which all have different permission sets and retention policies) THEN per-user partition / subdir
  * pros: much easier to manage as we do only have to create a few buckets with clear permissions/policies, ownership transfer (chown) does not require moving data from a bucket to another
  * cons: storage space monitoring has to be implemented at the asset management level to check user quotas, and we have storage imbalance with Garage
B. per-user bucket (requires a special bucket for automatic or anonymous users like in the case of public caching, but maybe it is also the case in the other scenario) THEN per-service partition / subdir (cache, private data, temp inputs, results)
  * pros: better quota management, maybe better storage balancing, but if caching relies on a single anonymous or system/service/robot user, this is not even sure — so if we go this way we need to assign cached element to the bucket of the user which requests it
  * cons: complex to manage as we have many buckets and also user quota monitoring is complex as we have more than user-uploaded data (the only data they have control on) in each bucket
C. a bucket for each service × user combination: for each user we create a `cache_u0001`, `userdata_u0001` and so on. We can have special users for special services, like anonymous fetching, but this may make less sense here.
  - pros: quota management is possible, and bucket storage should be better distributed among storage nodes (but there is no strong guarantee)
  - cons: requires the creation of many buckets each time we have a new user

Scenario A seems easier to implement, even if it requires managing user quota at the asset management level (as the feature will not be provided directly by the storage backend) but this is OK if we plan to support multiple storage regions / storage backends simultaneously.
Scenarios B and C seem like premature optimization because of a missing (hidden) feature of the storage backend, though we should be as backend-agnostic as possible.
As a result, Scenario A (which is the one currently planned) seems to be the best option we could think of. Having the ability to aggregate mutltiple storage *regions* seems like a strong feature to be able to migrate things without interruption.


### Experience with OVH S3 storage
- it is cheap
- it is easy to use
- it is fast in our first experiments (with multiple storage classes and regions available)
- it features the base S3 API, with extra features like
  - locking buckets (WORM) to avoid accidental deletion of data
  - expiration date for objects, which is useful for cache management
  - ability to make a bucket public or private
  - legal hold and retention policies for objects, to avoid accidental deletion of data
  - encryption at rest
- it supports creating multiple users with different permissions, which is useful for our use case of having multiple services (workers, cache, etc.) accessing the same storage backend with different permissions
- it supports URL presigning

### Overcoming Garage limitations and boosting OVH performance
It may be possible to implement a form of sharding on top of the S3 storage by creating multiple buckets for the same purpose (e.g., cache) and distributing the assets among them based on some hash of the asset ID, or any dispersion strategy (random shard selection is ok). This would require some extra logic in the asset management layer to keep track of which bucket an asset is stored in, but it could help with performance and storage balancing.
Because Garage and OVH S3 can be accessed through a single endpoint (whichever bucket is used), this is compatible with both proxying and signed URLs.

### Proxy mode vs signed URL mode
- proxy mode: the asset management service acts as a proxy for the storage backend, and the client accesses the storage through the asset management service. This allows for more control over access and permissions, but it may introduce some overhead and latency, especially for large files.
- signed URL mode: the asset management service generates signed URLs for the storage backend, and the client accesses the storage directly through these signed URLs. This can be more efficient for large files, but it requires careful management of the signed URLs and their expiration times, and it may expose the storage backend to more direct access.

A good overview with illustrations is available here: <https://labelstud.io/guide/storage#Pre-signed-URLs-vs-Storage-proxies>

I am not sure which mode is better for our use case, but we should consider the trade-offs and possibly support both modes depending on the context and requirements.

### Do we need aliases?
**From the cache perspective.**
Aliases provide a way to "tag" and keep track of the remote URLs a local asset mirrors. Cache validity can be implemented using lifecycle features, like expiration date.
Aliases can be useful as a way to store the remotes URLs a cache resource points to, but this could also be stored in a separate, dedicated cache database.


**From short-lived permissions perspective, like read authorization of private user data from workers.**
Aliases can be used to managed presigned URLs with short-lived or limited-use permissions for other services or users.


**Regarding how users will be able to read the results of the processings.**
Aliases can be used to create durable URLs when publishing or sharing some content. ← this seems hard to implement without this


**From the perspective or other services.**
Either we create an alias with specific permissions, or add new permissions to an existing alias.
Having the ability to set a time window or usage limit for the validity of the alias / permissions is quite appealing to enable complex accesses.

**From a more theoretical perspective:** do we need a distinction between physical and logical structuration of storage?
- physical:
    * region: which cluster/provider
    * bucket: data semantics which imply lifecycle policy, high-level permissions for services (e.g., workers cannot write cache) if this makes sense  
              💡 the bucket is the only required level as it must match with specific access rights (for services) and retention policies
    * ?? shard?: if we want to implement sharding on top of the storage backend, we could have a shard level here, but this may be overkill and add complexity
    * partitions: (like `user_0001/sub-aspect/`) enable accounting (quota management, billing and finer-grained permissions)  
      (maybe sub-aspect is not needed if we use logical paths/aliases to actually access resources, this risks cluttering/duplicating the logic or file access and permissions). System users would have a special partition for temporary storage of intermediate results, and for caching remote resources. However, maybe this is not needed if we use logical paths/aliases to actually access resources, this risks cluttering/duplicating the logic for file storage structure and permissions. Maybe using a random/hash-based file hierarchy is enough to avoid having too many files in a single "directory" (a bucket).
    * WORM (write once read many) policy for assets, no apparent need for versioning as this can be implemented on top of the asset management
- logical:
    * basically alias → asset, with multiple assets potentially pointing to the same asset
    * N-1 cardinality
    * aliases can be rewired

**DECISIONS**
- It may be OK to use signed URLs for direct access to the storage backend from workers (or other intra-cluster services), but for external users the proxy mode seems safer. Also, the proxy mode allows to implement more complex access control and auditing features, which may be useful for our use case. As a result, we may want to support both modes, and we need to specify which mode is used in which context, and how to switch between them if needed.
- use physical storage with the following structure: region, then bucket (or bucket name + shard id) for high-level storage semantics with default retention and per-service permissions (cache, user data, task results, temporary inputs), [then partition (associated to the entity who owns/pays for data storage) ← not sure we need partitions], then **UID** eventually organized into a prefix tree (*inode* metaphor)
- use logical storage to enable any access to real objects: all accesses are made by requesting the content for a particular alias. User permissions are validated at this level. Auditing and logging of accesses can be implemented at this level, and even if signed URLs are used, we will still have audit traces when the asset management service generates the signed URLs.

Access using the physical path is a low-level, debug- or admin-only API, except for signed URLs.

See next section for details about how permissions are associated to each "facet".


### Permissions
To which level are permissions associated? physical, logical, both?

**Durability**
- Some permissions are temporary (time validity, maybe also limited number of possible reads) to ensure workers and shares cannot have access to data after it was consumed. Signed URLs seem to be a good solution for this, but we need to ensure the storage backend supports this feature (OVH S3 does, Garage does). Source: <https://garagehq.deuxfleurs.fr/documentation/reference-manual/s3-compatibility/>
- Some others are durable like user/group permissions

**Scope**
- can give rights to an alias prefix (like `user_0001/` or `user_0001/task_0001/`) to a user/group/service to retrieve their files, or to upload a set of results
- or to an atomic resource
⇒ we need a prefix-based indexing of aliases permissions?

**Facet*
- low-level permissions / physical (like "database users") at bucket level for services: which service can read/write to which bucket (backend perspective) ← extra safety, necessary to manipulate the storage backend with external services through its API
  - but, ultimately, which services are going to be allowed to read/write to which bucket DIRECTLY? Signed URLs and proxy mode seem to limit bucket-level permissions to the asset management service, which is the only service which can access the storage backend directly. 
- also low-level / physical storage: permission for end user to access a storage bucket (for selecting this storage unit) ← not really clear, what did we mean here? maybe we meant "which storage region" which makes more sense as some region may be paid by a particular user or team. This seems to require a higher-level permission management, like "which storage region can this user/team/project use". From this perspective, regions enable to switch between storage backends (like local Garage, OVH S3, etc.) but we need to ensure that we do not need an extra "storage backend" physical level.
- logical level : end user perspective or temporary permission to access a particular alias: can the current user read/write file, list/add file/delete file from "directory", create directory, etc.

**Diversity** (some examples, need to have a full list at some point)
- folder listing
- add file to folder (case for result upload by workers for instance)
- file read
- file write (only when not uploaded yet)

### Security and bucket management
For security reasons, we should not require bucket creation to be done during the normal operation of the system. Buckets should be created during system initialization, and only be modified by an administrator. This is to avoid accidental or malicious creation of buckets with incorrect permissions or retention policies.

## Special asset status
Need to track the status of the asset when it is being uploaded, so we can lock the write permissions later.
Minimal tracking should include:
- upload pending
- created
- expired
- deleted


## Retention policies
Expiration data + legal hold seem sufficient to implement the features we need, at first sight.
We can implement this at the asset management level with proper garbage collection.
No need to rely on such features on the storage level, unless alias management and permissions are sufficient in an off-the-shelf product, which does not seem to be the case.


## Stories

### Submission of a list of OCR tasks with remote IIIF image URL, from an authenticated user

1. the user opens the online Corpusense interface, and selects multiple pages for processing. They configure the OCR endpoint URL but do not provide credentials (auth token), and call the "Run OCR" feature with some model selection and other parameters (`language`, `forced_image_size` for example, when such parameters are available: processing API will have to provide a way to publish their configuration details, but this is out of the scope of the asset management stack)  
   (later: when IIIF "forward auth" will be available, the user will obtain either a pre-signed URL or a short-lived download token for each resource)
2. the task API receives the request and: checks user/team/project token, validates the request payload, validates that the user has sufficient permissions for calling this processing API, etc. (later: checks credits / priority)
3. if everything is correct, the task API will prepare the launch of a new tasks workflow:
   a. ensure that distant assets are properly downloaded using a Cache subtask (see "Fetching a remote IIIF image" below): query the cache with distant resource URL and user id, and return either a permission failure, a download/caching failure, another error, or a success with the internal URI to the cached asset which can be forwarded to Processing services
   b. if previous task was successful, request the creation of a result directory for the next attempt at the Processing task: in the default region, under the `results` bucket, ensure intermediate hierarchy is available (`user_00001`/`task_xxxx`/`attempt_yyyyy`/) with appropriate rights so the user can read them (but not change them), and the workers can add new files under this directory. Whether we have special rights (like "add new write-once-read-many times files to this directory) and/or a dual-permission model (per service and per user/team/project/group) to implement this is a question which needs to be answered quickly.




## (sub story) Fetching a remote IIIF image which is allowed to be cached publicly
- the task API checks the authenticated user can request a fetch task
- depending on the remote URL, it may be cached publicly (allowlist for remote domains and url formats) or fetched in the user's temporary storage, here we consider the public caching scenario
- the task API checks of an already-existing ← FIXME delegate to cache service, with dedicated database for public URL to internal object id mapping? Cache returns an error if it is not allowed to cache the resource?
- the task API reserves a new asset for the remote resource, with following characteristics
   * physical storage parameters:
      * region = default or auto (for now)
      * 
   * 


## (sub story, alternative) Fetching a remote IIIF image which is NOT allowed to be cached publicly
