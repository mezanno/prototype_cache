# Software reuse after the pivot

The [old layer-by-layer OSS survey](../history/asset-store/spec/A_OSS_SURVEY.md)
is historical background. Its recommendation to complete a custom asset registry
and capability broker no longer defines the product or a required spike sequence.

## Active choices

- Keep the existing S3/Postgres approach for M-002. Reuse current adapters,
  transport/origin protections and operational patterns where they shorten delivery.
- Use existing IIIF Image software, with **Cantaloupe as a candidate to verify**
  against actual source formats, S3 endpoint, publication gating and Corpusense
  API versions. B-104 records the final choice/compatibility evidence as an ADR.
- Generate basic local Presentation manifests in the collection application.
  No new repository platform or general manifest editor is required.
- Supabase Storage remains a possible later option if it removes a specific
  product blocker. Do not add an adoption/migration study as a pilot prerequisite.
  It does not remove collection provenance, geometry or job integration work.

This is a delivery decision, not a fresh certification of provider versions,
licenses, resource footprint or every advertised feature. Check the selected
software/image and applicable existing findings when integrating it.

References for B-104: [Cantaloupe storage sources](https://cantaloupe-project.github.io/manual/5.0/sources.html),
[Image API endpoints](https://cantaloupe-project.github.io/manual/5.0/endpoints.html),
[IIIF image-service manifest recipe](https://iiif.io/api/cookbook/recipe/0005-image-service/).
