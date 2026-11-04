"""Inputs are verified before use, revisions fail loudly, and busy servers are retried."""

import io
import time
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from drought_loss import downloads


def test_a_file_with_the_wrong_checksum_is_kept_aside_not_used(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text('{"revised": true}', encoding="utf-8")
    dest = tmp_path / "raw" / "table.json"
    with pytest.raises(ValueError, match="revised its data"):
        downloads.fetch_verified(source.as_uri(), dest, "0" * 64)
    assert not dest.exists()
    assert not dest.with_name("table.json.part").exists()
    unverified = dest.with_name("table.json.unverified")
    assert unverified.read_text(encoding="utf-8") == '{"revised": true}'


def test_a_verified_copy_is_not_fetched_again(tmp_path: Path) -> None:
    dest = tmp_path / "table.json"
    dest.write_text("already here", encoding="utf-8")
    url = (tmp_path / "does-not-exist").as_uri()
    assert downloads.fetch_verified(url, dest, downloads.sha256(dest)) == dest


def test_a_matching_download_lands_in_place(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    dest = tmp_path / "raw" / "table.json"
    downloads.fetch_verified(source.as_uri(), dest, downloads.sha256(source))
    assert dest.read_text(encoding="utf-8") == "{}"


def busy(retry_after: str | None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        "https://example.invalid", 429, "Too Many Requests", headers, None
    )


def test_a_busy_server_is_retried_after_the_wait_it_asks_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replies: list[Any] = [busy("7"), busy(None), io.BytesIO(b"payload")]
    waits: list[float] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> Any:
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(time, "sleep", waits.append)
    downloads.fetch("https://example.invalid/table", tmp_path / "out")
    assert (tmp_path / "out").read_bytes() == b"payload"
    assert waits == [7.0, downloads.RETRY_WAIT_S]


def test_other_errors_are_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def urlopen(request: urllib.request.Request, timeout: float) -> Any:
        raise urllib.error.HTTPError("https://example.invalid", 404, "Not Found", Message(), None)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError, match="Not Found"):
        downloads.fetch("https://example.invalid/table", tmp_path / "out")
