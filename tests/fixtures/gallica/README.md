# Local Gallica-shaped origin fixture

`image.jpg` is an 8×8 solid RGB JPEG generated locally with Pillow. It is not
a Gallica download and has no third-party content. Tests serve it over local
HTTPS using the approved Gallica hostname and image-path shape. No runtime
Pillow dependency is needed. This fixture verifies API/storage/transport
behavior; representative live-origin corpus acceptance remains P6 work.
