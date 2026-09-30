"""Tests for Deployment Scripts and Alerting Mechanism."""

import hashlib
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread


class MockWebhookHandler(BaseHTTPRequestHandler):
    received_payloads = []

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        parsed = json.loads(post_data.decode("utf-8"))
        MockWebhookHandler.received_payloads.append(parsed)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, format: str, *args: object) -> None:
        pass


def test_notify_alert_script_mock_webhook(tmp_path: Path) -> None:
    """Verify notify_alert.sh formats JSON correctly with special characters and calls webhook."""
    MockWebhookHandler.received_payloads.clear()
    server = HTTPServer(("127.0.0.1", 0), MockWebhookHandler)
    port = server.server_port
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        log_file = tmp_path / "test.log"
        log_file.write_text(
            'Error line 1: "quoted"\nError line 2: backslash \\ test\ttab\nError line 3: failure!'
        )

        env_file = tmp_path / ".env"
        env_file.write_text(f'DISCORD_WEBHOOK_URL="http://127.0.0.1:{port}/webhook"\n')

        script_path = Path("deploy/notify_alert.sh").resolve()
        res = subprocess.run(
            [str(script_path), "Test Task", str(log_file), str(env_file)],
            capture_output=True,
            text=True,
        )

        assert res.returncode == 0, res.stderr
        assert len(MockWebhookHandler.received_payloads) == 1
        payload = MockWebhookHandler.received_payloads[0]
        assert payload["username"] == "QMO Alert Bot"
        content = payload["content"]
        assert "Test Task" in content
        assert '"quoted"' in content
        assert "backslash \\ test" in content
    finally:
        server.shutdown()


def test_notify_alert_script_missing_webhook_fails(tmp_path: Path) -> None:
    """Verify notify_alert.sh returns exit code 1 when no webhook URL is configured."""
    log_file = tmp_path / "test.log"
    log_file.write_text("Error log")
    env_file = tmp_path / ".env"
    env_file.write_text("SOME_VAR=123\n")

    script_path = Path("deploy/notify_alert.sh").resolve()
    res = subprocess.run(
        [str(script_path), "Test Task", str(log_file), str(env_file)],
        capture_output=True,
        text=True,
    )

    assert res.returncode != 0
    assert "No webhook URL configured" in res.stderr


def test_backup_and_restore_scripts_e2e(tmp_path: Path) -> None:
    """Verify backup_qmo.sh and restore_qmo.sh checksums and atomic swap."""
    import duckdb

    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    lock_file = tmp_path / "test.lock"
    data_dir.mkdir()
    catalog_dir = data_dir / "catalog"
    catalog_dir.mkdir()
    conn = duckdb.connect(str(catalog_dir / "qmo_catalog.duckdb"))
    conn.execute("CREATE TABLE batch_manifests(id INT); CREATE TABLE quality_reports(id INT)")
    conn.close()

    (data_dir / "normalized").mkdir()
    (data_dir / "normalized" / "test.parquet").write_text("parquet_mock_bytes")

    backup_script = Path("deploy/backup_qmo.sh").resolve()
    restore_script = Path("deploy/restore_qmo.sh").resolve()
    env = {**dict(os.environ), "LOCK_FILE": str(lock_file)}

    # 1. Run Backup Script
    res_b = subprocess.run(
        [str(backup_script), str(data_dir), str(backup_dir)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res_b.returncode == 0, res_b.stderr
    assert "Backup created successfully" in res_b.stdout

    tar_files = list(backup_dir.glob("qmo-backup-*.tar.gz"))
    sha_files = list(backup_dir.glob("qmo-backup-*.tar.gz.sha256"))
    assert len(tar_files) == 1
    assert len(sha_files) == 1
    tar_file = tar_files[0]

    # 2. Corrupt data_dir to simulate data corruption
    (data_dir / "normalized" / "test.parquet").write_text("corrupted_data")

    # 3. Run Restore Script
    restore_target = tmp_path / "restored_data"
    res_r = subprocess.run(
        [str(restore_script), str(tar_file), str(restore_target)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res_r.returncode == 0, res_r.stderr
    assert "QMO Restore Completed Successfully" in res_r.stdout
    assert (restore_target / "normalized" / "test.parquet").read_text() == "parquet_mock_bytes"


def test_notify_alert_script_http_500_fails(tmp_path: Path) -> None:
    """Verify notify_alert.sh returns exit code 1 when server responds HTTP 500."""

    class ErrorWebhookHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error": "internal error"}')

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), ErrorWebhookHandler)
    port = server.server_port
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        log_file = tmp_path / "test.log"
        log_file.write_text("Critical system failure log")
        env_file = tmp_path / ".env"
        env_file.write_text(f'DISCORD_WEBHOOK_URL="http://127.0.0.1:{port}/webhook"\n')

        script_path = Path("deploy/notify_alert.sh").resolve()
        res = subprocess.run(
            [str(script_path), "Failed Task", str(log_file), str(env_file)],
            capture_output=True,
            text=True,
        )

        assert res.returncode != 0
        assert "Failed to deliver alert payload" in res.stderr
    finally:
        server.shutdown()


def test_restore_missing_checksum_fails(tmp_path: Path) -> None:
    """Verify restore_qmo.sh fails closed when SHA256 checksum file is missing."""
    tar_file = tmp_path / "mock.tar.gz"
    tar_file.write_text("mock_tar_bytes")

    restore_script = Path("deploy/restore_qmo.sh").resolve()
    target_data = tmp_path / "target_data"
    lock_file = tmp_path / "test.lock"
    env = {**dict(os.environ), "LOCK_FILE": str(lock_file)}
    res = subprocess.run(
        [str(restore_script), str(tar_file), str(target_data)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode != 0
    assert "checksum file" in res.stderr and "missing" in res.stderr


def test_restore_corrupted_catalog_fails(tmp_path: Path) -> None:
    """Verify restore_qmo.sh fails closed when restored catalog is corrupted or invalid."""
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    lock_file = tmp_path / "test.lock"
    data_dir.mkdir()
    (data_dir / "catalog").mkdir()
    (data_dir / "catalog" / "qmo_catalog.duckdb").write_text("not_a_valid_duckdb_file")

    backup_script = Path("deploy/backup_qmo.sh").resolve()
    restore_script = Path("deploy/restore_qmo.sh").resolve()
    env = {**dict(os.environ), "LOCK_FILE": str(lock_file)}

    res_b = subprocess.run(
        [str(backup_script), str(data_dir), str(backup_dir)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res_b.returncode == 0

    tar_file = list(backup_dir.glob("qmo-backup-*.tar.gz"))[0]
    target_data = tmp_path / "target_data"
    res_r = subprocess.run(
        [str(restore_script), str(tar_file), str(target_data)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res_r.returncode != 0
    stderr_lower = res_r.stderr.lower()
    assert "catalog integrity check failed" in stderr_lower or "aborted" in stderr_lower


def test_check_disk_space_script(tmp_path: Path) -> None:
    """Verify check_disk_space.sh handles normal, warning, and critical alert branches."""
    script_path = Path("deploy/check_disk_space.sh").resolve()

    # 1. Normal branch (<80%)
    env_normal = {**dict(os.environ), "MOCK_USAGE_PCT": "50"}
    res_normal = subprocess.run(
        [str(script_path), str(tmp_path)],
        capture_output=True,
        text=True,
        env=env_normal,
    )
    assert res_normal.returncode == 0
    assert "OK: Disk space" in res_normal.stdout

    # 2. Warning branch (80% <= pct < 90%)
    env_warn = {**dict(os.environ), "MOCK_USAGE_PCT": "85"}
    res_warn = subprocess.run(
        [str(script_path), str(tmp_path)],
        capture_output=True,
        text=True,
        env=env_warn,
    )
    assert res_warn.returncode == 0
    assert "WARNING: Disk space" in res_warn.stdout

    # 3. Critical alert branch (pct >= 90%)
    env_crit = {**dict(os.environ), "MOCK_USAGE_PCT": "95"}
    res_crit = subprocess.run(
        [str(script_path), str(tmp_path)],
        capture_output=True,
        text=True,
        env=env_crit,
    )
    assert res_crit.returncode == 1
    assert "CRITICAL: Disk space" in res_crit.stderr


def test_restore_unsafe_tar_entries_fails(tmp_path: Path) -> None:
    """Verify restore_qmo.sh rejects archives with path traversal entries."""
    import io
    import tarfile

    rel_tar = tmp_path / "unsafe_traversal.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="../unsafe_traversal.txt")
        data = b"unsafe content"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    rel_tar.write_bytes(buf.getvalue())

    # Generate sha256 checksum file
    sha256 = hashlib.sha256(rel_tar.read_bytes()).hexdigest()
    (tmp_path / f"{rel_tar.name}.sha256").write_text(f"{sha256}  {rel_tar.name}\n")

    restore_script = Path("deploy/restore_qmo.sh").resolve()
    target_data = tmp_path / "target_data"
    lock_file = tmp_path / "test.lock"
    env = {**dict(os.environ), "LOCK_FILE": str(lock_file)}

    res = subprocess.run(
        [str(restore_script), str(rel_tar), str(target_data)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode != 0
    assert "unsafe" in res.stderr.lower() or "path traversal" in res.stderr.lower()


def test_restore_unsafe_symlink_fails(tmp_path: Path) -> None:
    """Verify restore_qmo.sh rejects archives with symlinks pointing to absolute paths."""
    tar_dir = tmp_path / "archive_content"
    tar_dir.mkdir()
    symlink_file = tar_dir / "bad_link"
    os.symlink("/etc/passwd", symlink_file)

    tar_file = tmp_path / "symlink.tar.gz"
    subprocess.run(
        ["tar", "-czf", str(tar_file), "-C", str(tar_dir), "bad_link"],
        check=True,
    )
    sha256 = hashlib.sha256(tar_file.read_bytes()).hexdigest()
    (tmp_path / f"{tar_file.name}.sha256").write_text(f"{sha256}  {tar_file.name}\n")

    restore_script = Path("deploy/restore_qmo.sh").resolve()
    target_data = tmp_path / "target_data"
    lock_file = tmp_path / "test.lock"
    env = {**dict(os.environ), "LOCK_FILE": str(lock_file)}
    res = subprocess.run(
        [str(restore_script), str(tar_file), str(target_data)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode != 0
    assert "unsafe" in res.stderr.lower() or "symlink" in res.stderr.lower()


def test_restore_swap_failure_preserves_original_data(tmp_path: Path) -> None:
    """Verify restore_qmo.sh preserves original data directory if staging check or swap fails."""
    # 1. Setup original live data directory
    live_data = tmp_path / "live_data"
    live_data.mkdir()
    (live_data / "important_data.txt").write_text("ORIGINAL_LIVE_DATA_V1")

    # 2. Setup backup directory with catalog missing required tables
    data_dir = tmp_path / "bad_data"
    data_dir.mkdir()
    (data_dir / "catalog").mkdir()
    (data_dir / "catalog" / "qmo_catalog.duckdb").write_text("invalid_duckdb_bytes")

    backup_dir = tmp_path / "backups"
    backup_script = Path("deploy/backup_qmo.sh").resolve()
    restore_script = Path("deploy/restore_qmo.sh").resolve()
    lock_file = tmp_path / "test.lock"
    env = {**dict(os.environ), "LOCK_FILE": str(lock_file)}

    subprocess.run(
        [str(backup_script), str(data_dir), str(backup_dir)],
        check=True,
        env=env,
    )

    tar_file = list(backup_dir.glob("qmo-backup-*.tar.gz"))[0]

    # 3. Attempt restore targeting live_data
    res = subprocess.run(
        [str(restore_script), str(tar_file), str(live_data)],
        capture_output=True,
        text=True,
        env=env,
    )

    # 4. Assert restore failed AND original live data preserved
    assert res.returncode != 0
    assert live_data.exists()
    assert (live_data / "important_data.txt").read_text() == "ORIGINAL_LIVE_DATA_V1"


def test_restore_staging_swap_failure_triggers_automatic_rollback(tmp_path: Path) -> None:
    """Verify restore_qmo.sh performs automatic rollback if staging swap fails."""
    import duckdb

    # 1. Setup original live data directory
    live_data = tmp_path / "live_data"
    live_data.mkdir()
    (live_data / "important_data.txt").write_text("ORIGINAL_LIVE_DATA_V1")

    # 2. Setup valid backup directory with required tables
    data_dir = tmp_path / "valid_data"
    data_dir.mkdir()
    (data_dir / "catalog").mkdir()
    conn = duckdb.connect(str(data_dir / "catalog" / "qmo_catalog.duckdb"))
    conn.execute("CREATE TABLE batch_manifests(id INT); CREATE TABLE quality_reports(id INT)")
    conn.close()

    backup_dir = tmp_path / "backups"
    backup_script = Path("deploy/backup_qmo.sh").resolve()
    restore_script = Path("deploy/restore_qmo.sh").resolve()
    lock_file = tmp_path / "test.lock"

    subprocess.run(
        [str(backup_script), str(data_dir), str(backup_dir)],
        check=True,
        env={**dict(os.environ), "LOCK_FILE": str(lock_file)},
    )
    tar_file = list(backup_dir.glob("qmo-backup-*.tar.gz"))[0]

    # 3. Trigger restore with MOCK_FAIL_STAGING_SWAP=1
    env_fail = {
        **dict(os.environ),
        "LOCK_FILE": str(lock_file),
        "MOCK_FAIL_STAGING_SWAP": "1",
    }
    res = subprocess.run(
        [str(restore_script), str(tar_file), str(live_data)],
        capture_output=True,
        text=True,
        env=env_fail,
    )

    # 4. Verify script failed AND original live data directory was restored automatically
    assert res.returncode != 0
    assert "Simulating staging swap failure" in res.stderr
    assert live_data.exists()
    assert (live_data / "important_data.txt").read_text() == "ORIGINAL_LIVE_DATA_V1"


def test_qmo_cron_file_entries_and_syntax() -> None:
    """Verify qmo.cron contains required jobs and valid bash syntax."""
    cron_path = Path("deploy/qmo.cron").resolve()
    content = cron_path.read_text()

    assert "run_pipeline.sh" in content
    assert "backup_qmo.sh" in content
    assert "check_disk_space.sh" in content
    assert "notify_alert.sh" in content

    # Check bash syntax for each command line in cron
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Extract command after cron 5-field schedule
        parts = line.split(maxsplit=5)
        assert len(parts) == 6
        cmd = parts[5]
        res = subprocess.run(["sh", "-n", "-c", cmd], capture_output=True, text=True)
        assert res.returncode == 0, f"Cron line syntax error: {cmd}\n{res.stderr}"




