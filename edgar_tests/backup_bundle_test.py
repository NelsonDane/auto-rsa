"""Bundle round-trip + tamper resistance + missing-file behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backup import bundle


def _files(tmp_path: Path, names_and_contents: dict[str, bytes]) -> list[Path]:
    out = []
    for name, content in names_and_contents.items():
        p = tmp_path / name
        p.write_bytes(content)
        out.append(p)
    return out


def test_round_trip_recovers_exact_bytes(tmp_path):
    paths = _files(tmp_path, {
        "vault.json": b'{"version":2,"brokers":{}}',
        "ledger.db": b"binary\x00\x01\x02\xffcontent",
        "license.token": b'{"payload":{"tier":"operator"}}',
    })
    blob = bundle.create_bundle("passw0rd!", paths)

    dest = tmp_path / "restored"
    written = bundle.restore_bundle("passw0rd!", blob, dest)
    assert set(written) == {"vault.json", "ledger.db", "license.token"}
    for name, expected in [
        ("vault.json", b'{"version":2,"brokers":{}}'),
        ("ledger.db", b"binary\x00\x01\x02\xffcontent"),
        ("license.token", b'{"payload":{"tier":"operator"}}'),
    ]:
        assert (dest / name).read_bytes() == expected


def test_missing_files_are_silently_skipped_if_at_least_one_exists(tmp_path):
    paths = _files(tmp_path, {"vault.json": b"x"})
    paths.append(tmp_path / "does_not_exist.token")
    blob = bundle.create_bundle("pw", paths)
    dest = tmp_path / "restored"
    written = bundle.restore_bundle("pw", blob, dest)
    assert written == ["vault.json"]


def test_no_existing_files_at_all_fails_loudly(tmp_path):
    nonexistent = [tmp_path / "x", tmp_path / "y"]
    with pytest.raises(bundle.BackupError) as exc:
        bundle.create_bundle("pw", nonexistent)
    assert "nothing to back up" in str(exc.value).lower()


def test_wrong_passphrase_fails_with_clear_message(tmp_path):
    paths = _files(tmp_path, {"vault.json": b"secret"})
    blob = bundle.create_bundle("correct passphrase", paths)
    with pytest.raises(bundle.BackupError) as exc:
        bundle.restore_bundle("wrong passphrase", blob, tmp_path / "out")
    assert "passphrase" in str(exc.value).lower()


def test_empty_passphrase_refuses_to_create(tmp_path):
    paths = _files(tmp_path, {"vault.json": b"x"})
    with pytest.raises(bundle.BackupError) as exc:
        bundle.create_bundle("", paths)
    assert "empty" in str(exc.value).lower()


def test_empty_passphrase_refuses_to_restore(tmp_path):
    paths = _files(tmp_path, {"vault.json": b"x"})
    blob = bundle.create_bundle("pw", paths)
    with pytest.raises(bundle.BackupError) as exc:
        bundle.restore_bundle("", blob, tmp_path / "out")
    assert "empty" in str(exc.value).lower()


def test_corrupt_bundle_fails_gracefully(tmp_path):
    with pytest.raises(bundle.BackupError) as exc:
        bundle.restore_bundle("pw", b"not a real bundle", tmp_path / "out")
    assert isinstance(exc.value, bundle.BackupError)


def test_bundle_format_starts_with_salt_then_header(tmp_path):
    """Locks in the documented format so a future format change is intentional."""
    paths = _files(tmp_path, {"x": b"y"})
    blob = bundle.create_bundle("pw", paths)
    # First 16 bytes are the salt, next is a JSON object with n/r/p
    # followed by a newline.
    assert len(blob) > bundle._SALT_BYTES + 5
    rest = blob[bundle._SALT_BYTES:]
    header, _ = rest.split(b"\n", 1)
    assert header.startswith(b"{")
    assert b'"n"' in header and b'"r"' in header and b'"p"' in header


def _craft_bundle_with_member(member_name: str, payload: bytes = b"malicious") -> bytes:
    """Encrypt a one-member tarball in the bundle format (for restore)."""
    import base64
    import io
    import json
    import secrets
    import tarfile

    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    raw_tar = io.BytesIO()
    with tarfile.open(fileobj=raw_tar, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=member_name)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    salt = secrets.token_bytes(bundle._SALT_BYTES)
    kdf = bundle._KDF_PARAMS
    scrypt = Scrypt(salt=salt, length=bundle._KEY_LEN, **kdf)
    key = base64.urlsafe_b64encode(scrypt.derive(b"pw"))
    token = Fernet(key).encrypt(raw_tar.getvalue())
    return salt + json.dumps(kdf).encode() + b"\n" + token


def test_path_traversal_in_tarball_is_rejected(tmp_path):
    """A ../ entry that escapes the destination must refuse."""
    crafted = _craft_bundle_with_member("../escapee")
    with pytest.raises(bundle.BackupError) as exc:
        bundle.restore_bundle("pw", crafted, tmp_path / "out")
    assert "path-traversing" in str(exc.value).lower()


def test_sibling_prefix_escape_is_rejected(tmp_path):
    """Regression: a sibling dir that merely shares the destination's
    string prefix (``out-evil`` vs ``out``) used to pass the old
    ``str.startswith`` guard and write outside the destination."""
    dest = tmp_path / "out"
    crafted = _craft_bundle_with_member("../out-evil/pwned")
    with pytest.raises(bundle.BackupError) as exc:
        bundle.restore_bundle("pw", crafted, dest)
    assert "path-traversing" in str(exc.value).lower()
    # And nothing was written to the sibling location.
    assert not (tmp_path / "out-evil").exists()
