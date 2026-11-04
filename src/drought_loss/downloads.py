"""Fetching inputs: polite retries, and a SHA-256 check before anything is used.

Every input is pinned by SHA-256 in config.py. A source that revises its data therefore fails
loudly, with the new file kept aside for inspection, instead of silently changing results.
"""

import hashlib
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

# A plain client name: some servers rate-limit or block the default Python user agent.
USER_AGENT = "moldova-drought-loss/0.1 (research pipeline)"
RETRIES = 4
RETRY_WAIT_S = 15.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_verified(path: Path, expected: str) -> bool:
    return path.exists() and sha256(path) == expected


def fetch(url: str, dest: Path, data: bytes | None = None) -> Path:
    """Download `url` to `dest` (a POST when `data` is given).

    Waits and retries when the server says it is busy (HTTP 429 or 503), honouring its
    Retry-After header, and gives up after a few attempts.
    """
    headers = {"User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as out:
                shutil.copyfileobj(response, out)
            return dest
        except urllib.error.HTTPError as error:
            if error.code not in (429, 503) or attempt == RETRIES:
                raise
            time.sleep(float(error.headers.get("Retry-After") or RETRY_WAIT_S))
    raise AssertionError("unreachable")


def accept(partial: Path, dest: Path, expected_sha256: str, source: str) -> Path:
    """Move a finished file into place, but only if its SHA-256 matches the pin."""
    actual = sha256(partial)
    if actual != expected_sha256:
        unverified = dest.with_name(dest.name + ".unverified")
        partial.replace(unverified)
        raise ValueError(
            f"SHA-256 of {source} is {actual}, not the pinned {expected_sha256}. The source may "
            f"have revised its data: inspect {unverified}, and if the change is accepted, update "
            "the pin in config.py."
        )
    partial.replace(dest)
    return dest


def fetch_verified(url: str, dest: Path, expected_sha256: str, data: bytes | None = None) -> Path:
    """Download unless a verified copy is already there; never leave an unverified file at dest."""
    if is_verified(dest, expected_sha256):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    fetch(url, partial, data)
    return accept(partial, dest, expected_sha256, url)
