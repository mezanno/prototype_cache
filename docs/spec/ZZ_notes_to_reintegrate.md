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
  * pros: better quota management, maybe better storage balancing, but if caching relies on a single anonymous or system/service/robot user, this is not even sure — so if we go this way we need to assign cached element to the bucket of the user which requests it)
  * cons: complex to manage as we have many buckets and also user quota monitoring is complex as we have more than user-uploaded data (the only data they have control on) in each bucket
C. a bucket for each service × user combination: for each user we create a `cache_u0001`, `userdata_u0001` and so on. We can have special users for special services, like anonymous fetching, but this may make less sense here.
  - pros: quota management is possible, and bucket storage should be better distributed among storage nodes (but there is no strong guarentee)
  - cons: requires the creation of many buckets each time we have a new user

Scenario A seels easier to implement, even if it requires to manage user quota at the asset management level (as the feature will not be provided directly by the storage backend) but this is OK if we plan to support multiple storage regions / storage backends simultaneously.
Scenarios B and C seem like premature optimization because of a missing (hidden) feature of the storage backend, though we should be as backend-agnostic as possible.
As a result, Scenario A (which is the one currently planned) seems to be the best option we could thing of. Having the ability to aggregate mutliple storage *regions* seems like a strong feature to be a able to migrate things without interruption.


### Do we need aliases?
**From the cache perspective.**
Aliases provide a way to "tag" and keep track of the remote URLs a local asset mirrors. Cache validity can be implemented using lifecycle features, like expiration date.
Aliases can be useful as a way to store the remotes URLs a cache resource points to, but this could also be stored in a separate, dedicated cache database.


**From short-lived permissions perspective, like read authorization of private user data from workers.**
Aliases can be used to managed presigned URLs with short-lived or limited-use permissions for other services or users.


**Regarding how users will be able to read the results of the processsings.**
Aliases can be used to create durable URLs when publishing or sharing some content. ← this seems hard to implement without this


**From the perspective or other services.**
Either we create an alias with specific permissions, or add new permissions to an existing alias.
Having the ability to set a time window or usage limit for the validity of the alias / permissions is quite appealing to enable complex accesses.

**From a more theoretical perspective:** do we need a distinction between physical and logical structuration of storage?
- physical:
    * region: which cluster/provider
    * bucket: data semantics which imply lifecycle policy, high-level permissions for services (e.g., workers cannot write cache) if this makes sense
    * partitions: (like `user_0001/sub-aspect/`) enable accounting (quota management, billing and finer-grained permissions)  
      (maybe subaspect is not needed if we use logical pathes/aliases to actually access resources, this risks cluttering/duplicating the logic or file access and permissions) 
    * WORM (write once read many) policy for assets, no apparent need for versionning as this can be implemented on top of the asset management
- logical:
    * basically alias → asset, with multiple assets potentially pointing to the same asset
    * N-1 cardinality
    * aliases can be rewired

**DECISIONS**
- use physical storage with the following structure: region, then bucket for high-level storage semantics with default retention and per-service permissions (cache, user data, task results, temporary inputs), then partition (associated to the entity who owns/payes for data storage), then **UID** eventually organized into a prefix tree (*inode* metaphor)
- use logical storage to enable any access to real objects: all accesses are made by requesting the content for a particular alias. User permissions are validated at this level.

Access using the physical path is a low-level, debug- or admin-only API.

See next section for details about how permissions are associated to each "facet".


### Permissions
To which level are permissions associated? physical, logical, both?

**Durability**
- Some permissions are temporary (time validity, maybe also limited number of possible reads) to ensure workers and shares cannot have access to data after it was consumed.
- Some others are durable like user/group permissions

**Scope**
- can give rights to a prefix
- or to an atomic resource
⇒ we need a prefix-based indexing of aliases permissions?

**Facet*
- low-level permissions / physical (like "database users") at bucket level for services: which service can read/write to which bucket (backend perspective) ← extra safety, necessary to manipulate the storage backend with external services through its API
- also low-level / physical storage: permission for end user to access a storage bucket (for selecting this storage unit)
- logical level : end user perspective or temporary permission to access a particular alias: can the current user read/write file, list/add file/delete file from "directory", create directory, etc.

**Diversity** (some examples, need to have a full list at some point)
- folder listing
- add file to folder (case for result upload by workers for instance)
- file read
- file write (only when not uploaded yet)


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
   b. if previous task was successful, request the creation of a result directory for the next attempt at the Processing task: in the default region, under the `results`bucket, ensure intermediate hierarchy is available (`user_00001`/`task_xxxx`/`attempt_yyyyy`/) with appropriate rights so the user can read them (but not change them), and the workers can add new files under this directory. Whether we have special rights (like "add new write-once-read-many times files to this directory) and/or a dual-permission model (per service and per user/team/project/group) to implement this is a question which needs to be answered quickly.



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
