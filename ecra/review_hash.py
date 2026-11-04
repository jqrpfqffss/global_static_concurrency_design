"""The existing review JSON SHA256, without an entire JSON string and bytes."""
import hashlib
import json


def digest(value):
    hashed=hashlib.sha256()
    encoder=json.JSONEncoder(sort_keys=True,ensure_ascii=False)
    for part in encoder.iterencode(value):hashed.update(part.encode('utf-8'))
    return hashed.hexdigest()
