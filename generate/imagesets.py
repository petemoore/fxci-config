"""Imageset resolution: logical name -> cloud image IDs."""

from .loader import load_yaml

_imagesets = None


def get_imagesets():
    global _imagesets
    if _imagesets is None:
        _imagesets = load_yaml("imagesets.yml")
    return _imagesets


def resolve_gcp_image(imageset_name):
    """Return the full GCP image path for an imageset."""
    imagesets = get_imagesets()
    iset = imagesets[imageset_name]
    return iset["gcp"]["image"]


def resolve_azure_images(imageset_name):
    """Return dict of {location: image_id} for an Azure imageset."""
    imagesets = get_imagesets()
    iset = imagesets[imageset_name]
    return iset["azure"]["images"]
