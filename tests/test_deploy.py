"""Tests for Deployment Scripts and Alerting Mechanism."""

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
    conn.execute("CREATE TABLE test_table(id INT)")
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


def test_check_disk_space_script(tmp_path: Path) -> None:
    """Verify check_disk_space.sh executes without error on valid directory."""
    script_path = Path("deploy/check_disk_space.sh").resolve()
    res = subprocess.run(
        [str(script_path), str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "Disk space for" in res.stdout

