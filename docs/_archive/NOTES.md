# Misc. notes
*This file contain unsorted notes.*

## Accessing resources via the IIIF server
- IIIF URLs should be durable and unique, so users can cite/reference the resources easily.
- These URLs should have a form like `https://{iiif server domain}/ark:/{our ark prefix}/{user or project id}/{resource alias}/{iiif-specific query part}`
- Such resource should be stored under a sub bucket for the user/project/team, and have a alias of the form `{user or team or project id}/???/{UID}`
- once published, a resource should not receive another IIIF unique identifier
- we should avoid to have multiple IIIF identifier pointing to the same resource, to avoid confusion.
- Manifests (for the IIIF Presentation API) should receive clear and persistent URLs
- `info.json` files for the IIIF Image API should not carry any information about how they are organised by the user, as they can be included in multiple manifests.
- manifests should be static (regarding the list of images they point to) once they are published (maybe we can have an option to mark them "unstable", and to choose when they can be used durably, maybe with private/restricted URLs before, and public URLs after)
- metadata may be updated at any time to fix mistakes, but we should version manifests in this case (this can be addressed later)
- basically, we have to type of resources: images (we do not support other forms of IIIF resoures for now) and definitions of collections which include images


## User uploads
- User uploads (images) should changed once they are uploaded. We want to have reliable resources idenfiers to static content.


## Storage and permissions
- user uploads are stored on user-specific space, to facilitate quota management and storage billing
- depending on their permissions, users may add, remove or edit metadata for resources in a particular space
- each resource receives a new unique identifier
- aliases are logical filenames which enable users to access these objects.
- resources should always have one or more aliases, otherwise they probably are unused resources which can be removed
- accessing resources using their unique identifier is a low level API, probably only internal to the storage API, after authentication (like using an inode)
- access permissions are associated to aliases, and the "storage guard" is responsible for checking that the request for a resource comes from a user or a service with adequate permissions, before proxying data access using the low-level API.
- we may create aliases before underlying objects actually exist, to allow a service to perform an upload, for instance
- I'm wondering whether it makes sense to use prefix-based permissions, for instance if we want to grant a user to access a complete subtree (from the alias perspective, i.e., all filename which start with the same prefix, which indicate they are virtually organized under the same directory at some point)


## Aliases (aka filenames) and storage
- Does it make sense to permit a file to have more that one alias pointing to it (except for the cache which can mirror resources which can be fetched from different URLs though they are the same)?
- Maybe users may want a resource to be used in several manifests, and in this case this seems to make sense.
- This sort of feature may be useful if a private manifest is generated for each subdirectory:
    - the URL for the manifest would be based on the internal, virtual organization of files a user has,
    - and they could create "sharing links" (like what can be done with NextCloud) for other users
    - and finally, when they want to publish a collection, it will automatically be given a unique name, each file/image will receive a new unique name, both the manifest and the images via these public aliases, could be read by anyone as public permissions would be set for them. The public collection would appear in a special part on the management interface for user which created it, and it could not be updated.
- maybe this sharing thing can be simplified, with only 2 aliases being used: private ones and public ones, with private aliases supporting the addition of multiple users/groups in the list of who can read them
- also, as mentionned somewhere else, workers, upload services and other software modules should not be able to access all data at any time: they should be granted fine-grained permission, for a limited amount of time or even for a single use.
    - proceeding this way, I believe, may limit privacy issues with upload service and workers which can be granted permissions to read or write only selected files or subdirectories (for the workers producing multiple output artifacts for instance)
    - this looks like a sort of virtual filesystem (probably backed by an S3 storage), but with particularities related to the immutable character of most, if not all, files. 
        - this seems like a useful abstraction, as it is a very standard thing, and we would be able to give each actor an identifier and permissions. We could also have supervision system which enforces the properties we are looking for, like imutability of specific resources after their creation, short-lived actor-specific permissions, quota management, access monitoring, and so on.
    - metadata, and maybe virtual folders (but are they more than common prefixes for different aliases?), seem to be the only items which can be modified after their initial creation
    - so, the question about how and where to store metadata is an important point to address. Metadata stores attributes for files, probably in the form of a (sorted?) set of (key, value) elements describing provenance, content, and any other aspect about the images of historical document we will store.


## Caching of distant IIIF resources
- caching works in a way which is similar to user upload, in the sense that
    - a storage space is reserved for the cache management, which can be populated by manual pre-loaded or on-demand fetchig
    - the "physical" organization of resources should comply with the naming of the distant service which is cached (WARNING: is that compatible with multiple domains pointing to the same resource?)
    - the "logical" organization (aliases defined with metadata) should name these resources as `{mirrored domain}/{remote resource-related url part}`, with multiple aliases being possible (e.g., in the case 2 versions of the IIIF API are available for the distant service, as it is the case with Gallica)
