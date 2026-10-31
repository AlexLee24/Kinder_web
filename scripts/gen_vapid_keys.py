"""Make a VAPID key pair for Web Push (Admin › Push, app/services/notifications/webpush.py).

    .venv/bin/python scripts/gen_vapid_keys.py

Prints three lines for kinder.env. Make the pair once and give every server the same one: browsers subscribe to the
public key, so a new pair means every member has to turn push on again.
"""
import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def main():
    v = Vapid01()
    v.generate_keys()
    private = v.private_key.private_numbers().private_value.to_bytes(32, 'big')
    public = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    print(f'VAPID_PUBLIC_KEY={_b64(public)}')
    print(f'VAPID_PRIVATE_KEY={_b64(private)}')
    print('VAPID_SUBJECT=mailto:kinder@astro.ncu.edu.tw')


if __name__ == '__main__':
    main()
