"""Profile pictures.

Uploaded avatars are stored in ``auth.users.picture_url`` as a small base64
``data:`` URI, but pages never embed that data: they link to ``/avatar/<usr_id>``
(see ``avatar_url``), which the browser caches. Uploads are shrunk to at most
``AVATAR_SIZE`` pixels so the stored value stays small.
"""
import base64
import binascii
import hashlib
import io
import logging
import re

logger = logging.getLogger(__name__)

AVATAR_SIZE = 256                 # longest side, pixels
MAX_STORED_BYTES = 120 * 1024     # data URIs above this are re-encoded smaller
DEFAULT_AVATAR = '/static/img/default-avatar.svg'

_DATA_URI_RE = re.compile(r'^data:(image/(?:png|jpe?g|gif|webp));base64,(.+)$', re.S)


def decode_data_uri(data_uri: str):
    """Return (mimetype, bytes) for an image data: URI, or None if it is not one."""
    m = _DATA_URI_RE.match(data_uri or '')
    if not m:
        return None
    try:
        return m.group(1), base64.b64decode(m.group(2), validate=False)
    except (binascii.Error, ValueError):
        return None


def shrink_data_uri(data_uri: str, size: int = AVATAR_SIZE) -> str | None:
    """Re-encode an image data: URI to at most ``size`` px (JPEG, or PNG when it
    has transparency). Returns the new data: URI, or None if it is not a valid image."""
    decoded = decode_data_uri(data_uri)
    if not decoded:
        return None
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(decoded[1])) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((size, size))
            has_alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)
            out = io.BytesIO()
            if has_alpha:
                img.convert('RGBA').save(out, 'PNG', optimize=True)
                mime = 'image/png'
            else:
                img.convert('RGB').save(out, 'JPEG', quality=85, optimize=True)
                mime = 'image/jpeg'
    except Exception as exc:   # Pillow raises many types for bad input
        logger.warning('avatar: could not re-encode image: %s', exc)
        return None
    return f'data:{mime};base64,' + base64.b64encode(out.getvalue()).decode('ascii')


def avatar_url(usr_id, picture_url: str | None) -> str:
    """What pages should put in <img src>: the stored https:// URL (e.g. Google),
    a cacheable /avatar/<id> link for uploaded images, or the default avatar."""
    if not picture_url:
        return DEFAULT_AVATAR
    if picture_url.startswith('data:'):
        # Same value as the SQL in app/db/transient.py: substr(md5(picture_url), 1, 10)
        version = hashlib.md5(picture_url.encode('utf-8'), usedforsecurity=False).hexdigest()[:10]
        return f'/avatar/{usr_id}?v={version}'
    return picture_url
