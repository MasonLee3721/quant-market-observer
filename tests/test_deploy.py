"""Tests for Deployment Scripts and Alerting Mechanism."""

import json
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
