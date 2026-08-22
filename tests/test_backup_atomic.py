"""Tests for backup/restore and atomic writes."""

from kora.utils.atomic import atomic_write_text
from kora.utils.backup import Backups


class TestAtomicWrite:
    def test_write_creates_parents(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "file.txt"
        atomic_write_text(target, "content")
        assert target.read_text() == "content"

    def test_overwrite_preserves_content(self, tmp_path):
        target = tmp_path / "f.txt"
        atomic_write_text(target, "one")
        atomic_write_text(target, "two")
        assert target.read_text() == "two"

    def test_no_temp_files_remain(self, tmp_path):
        target = tmp_path / "f.txt"
        atomic_write_text(target, "data")
        leftovers = list(tmp_path.glob("*.tmp")) + list(tmp_path.glob(".*tmp*"))
        assert leftovers == []


class TestBackups:
    def test_backup_and_restore_roundtrip(self, tmp_project):
        target = tmp_project / "src" / "main.py"
        original = target.read_text()

        session = Backups.create()
        assert session.backup_file(target) is True

        # simulate a destructive edit
        target.write_text("# broken content")

        restored = session.restore_file(target)
        assert restored is True
        assert target.read_text() == original

    def test_backup_nonexistent_returns_false(self, tmp_path):
        session = Backups.create()
        assert session.backup_file(tmp_path / "ghost.txt") is False

    def test_restore_without_backup_returns_false(self, tmp_path):
        session = Backups.create()
        assert session.restore_file(tmp_path / "never_seen.txt") is False

    def test_session_keeps_first_state(self, tmp_project):
        """Multiple backups in one session keep the earliest state."""
        target = tmp_project / "f.txt"
        target.write_text("v1")
        session = Backups.create()
        session.backup_file(target)
        target.write_text("v2")
        session.backup_file(target)

        target.write_text("v3-broken")
        session.restore_file(target)
        assert target.read_text() == "v1"

    def test_manifest_records_entries(self, tmp_path):
        session = Backups.create()
        session.record("did something")
        manifest = session.manifest_path.read_text(encoding="utf-8")
        assert "did something" in manifest
