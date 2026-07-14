from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPOSITORY_ROOT / "skills" / "post-queue-cli" / "scripts" / "post_queue.py"


class RecordingHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    response_status = 200
    response_headers: dict[str, str] = {"Content-Type": "application/json"}
    response_body = b"{}"
    response_queue: list[tuple[int, dict[str, str], bytes]] = []

    def record_and_respond(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        self.__class__.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers),
                "body": body,
            }
        )
        if self.__class__.response_queue:
            status, headers, response_body = self.__class__.response_queue.pop(0)
        else:
            status = self.__class__.response_status
            headers = self.__class__.response_headers
            response_body = self.__class__.response_body
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(response_body)

    def do_GET(self) -> None:
        self.record_and_respond()

    def do_POST(self) -> None:
        self.record_and_respond()

    def do_PATCH(self) -> None:
        self.record_and_respond()

    def do_DELETE(self) -> None:
        self.record_and_respond()

    def do_PUT(self) -> None:
        self.record_and_respond()

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextmanager
def api_server(
    response: Any,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> Iterator[tuple[str, type[RecordingHandler]]]:
    handler_class = type("IsolatedRecordingHandler", (RecordingHandler,), {})
    handler_class.requests = []
    handler_class.response_status = status
    handler_class.response_headers = headers or {"Content-Type": "application/json"}
    handler_class.response_queue = []
    handler_class.response_body = (
        response
        if isinstance(response, bytes)
        else json.dumps(response).encode("utf-8")
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}", handler_class
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def run_cli(
    *arguments: str,
    api_key: str | None = "test-api-key",
    base_url: str | None = "http://127.0.0.1:9",
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("POST_QUEUE_API_KEY", None)
    environment.pop("POST_QUEUE_BASE_URL", None)
    if api_key is not None:
        environment["POST_QUEUE_API_KEY"] = api_key
    if base_url is not None:
        environment["POST_QUEUE_BASE_URL"] = base_url
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *arguments],
        input=stdin,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
        timeout=5,
    )


class ConfigurationTests(unittest.TestCase):
    def test_config_file_is_beside_skill_file(self) -> None:
        namespace = runpy.run_path(str(CLI_PATH))

        self.assertEqual(namespace["CONFIG_PATH"], CLI_PATH.parent.parent / ".env")

    def test_reads_saved_key_from_skill_env_file(self) -> None:
        import tempfile

        namespace = runpy.run_path(str(CLI_PATH))
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / ".env"
            config_path.write_text("POST_QUEUE_API_KEY=saved-key\n", encoding="utf-8")
            namespace["read_config_file"].__globals__["CONFIG_PATH"] = config_path
            with mock.patch.dict(
                os.environ,
                {"POST_QUEUE_BASE_URL": "http://127.0.0.1:9"},
                clear=True,
            ):
                config = namespace["load_config"]()

        self.assertEqual(config.api_key, "saved-key")

    def test_missing_api_key_is_json_configuration_error(self) -> None:
        result = run_cli("account", "list", api_key=None)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        payload = json.loads(result.stderr)
        self.assertEqual(payload["error"]["type"], "configuration")
        self.assertNotIn("test-api-key", result.stderr)

    def test_rejects_unsafe_base_urls_before_a_request(self) -> None:
        unsafe_urls = (
            "http://example.com",
            "https://example.com",
            "https://user:pass@example.com",
            "https://example.com/api",
            "https://example.com?target=elsewhere",
            "https://example.com#fragment",
            "ftp://example.com",
        )

        for unsafe_url in unsafe_urls:
            with self.subTest(url=unsafe_url):
                result = run_cli("account", "list", base_url=unsafe_url)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                payload = json.loads(result.stderr)
                self.assertEqual(payload["error"]["type"], "usage")
                self.assertNotIn("test-api-key", result.stderr)

    def test_rejects_malformed_url_and_key_without_traceback_or_secret(self) -> None:
        malformed_url = run_cli("account", "list", base_url="https://[invalid")
        malformed_key = run_cli("account", "list", api_key="secret\nheader")

        for result in (malformed_url, malformed_key):
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            payload = json.loads(result.stderr)
            self.assertIn(payload["error"]["type"], {"configuration", "usage"})
            self.assertNotIn("Traceback", result.stderr)
            self.assertNotIn("secret", result.stderr)


class AccountTests(unittest.TestCase):
    def test_lists_connected_accounts_with_bearer_authentication(self) -> None:
        accounts = [{"id": "account-1", "platform": "threads"}]
        with api_server(accounts) as (base_url, handler):
            result = run_cli("account", "list", base_url=base_url)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), accounts)
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(handler.requests), 1)
        request = handler.requests[0]
        self.assertEqual(request["method"], "GET")
        self.assertEqual(request["path"], "/tenant/connected-accounts")
        self.assertEqual(request["headers"]["Authorization"], "Bearer test-api-key")

    def test_does_not_follow_authenticated_redirects(self) -> None:
        with api_server({"received": False}) as (receiver_url, receiver):
            with api_server(
                b"redirect",
                status=302,
                headers={"Location": f"{receiver_url}/capture"},
            ) as (base_url, source):
                result = run_cli("account", "list", base_url=base_url)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stderr)["error"]["status"], 302)
        self.assertEqual(len(source.requests), 1)
        self.assertEqual(receiver.requests, [])


class MediaTests(unittest.TestCase):
    def test_uploads_media_without_sending_bearer_to_object_store(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            media_path = Path(directory) / "example.png"
            media_bytes = b"test-png-bytes"
            media_path.write_bytes(media_bytes)
            with api_server({}) as (base_url, handler):
                upload_url = f"{base_url}/object-upload?signature=secret"
                presign = {
                    "media_asset_id": "media-1",
                    "upload_url": upload_url,
                    "public_url": "https://cdn.example.com/user/media-1.png",
                    "object_key": "user/media-1.png",
                    "expires_in": 3600,
                }
                registered = {"id": "media-1", "asset_type": "uploaded"}
                handler.response_queue = [
                    (
                        200,
                        {"Content-Type": "application/json"},
                        json.dumps(presign).encode(),
                    ),
                    (200, {}, b""),
                    (
                        200,
                        {"Content-Type": "application/json"},
                        json.dumps(registered).encode(),
                    ),
                ]
                result = run_cli(
                    "media",
                    "upload",
                    str(media_path),
                    base_url=base_url,
                )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), registered)
        self.assertEqual(len(handler.requests), 3)
        presign_request, upload_request, register_request = handler.requests
        self.assertEqual(presign_request["method"], "POST")
        self.assertEqual(presign_request["path"], "/tenant/media-assets/presign")
        self.assertEqual(
            json.loads(presign_request["body"]),
            {
                "filename": "example.png",
                "content_type": "image/png",
                "size_bytes": len(media_bytes),
            },
        )
        self.assertEqual(upload_request["method"], "PUT")
        self.assertEqual(upload_request["path"], "/object-upload?signature=secret")
        self.assertNotIn("Authorization", upload_request["headers"])
        self.assertEqual(upload_request["headers"]["Content-Type"], "image/png")
        self.assertEqual(upload_request["body"], media_bytes)
        self.assertEqual(register_request["method"], "POST")
        self.assertEqual(register_request["path"], "/tenant/media-assets")
        self.assertEqual(
            json.loads(register_request["body"]),
            {
                "media_asset_id": "media-1",
                "asset_type": "uploaded",
                "object_url": "https://cdn.example.com/user/media-1.png",
                "content_type": "image/png",
                "filename": "example.png",
            },
        )
        self.assertEqual(
            register_request["headers"]["Authorization"], "Bearer test-api-key"
        )

    def test_rejects_unsafe_presigned_urls_without_leaking_them(self) -> None:
        unsafe_urls = (
            "http://example.com/upload?signature=secret-signature",
            "https://user:secret-signature@example.com/upload",
            "https://example.com/upload#secret-signature",
            "https://[secret-signature",
        )
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            media_path = Path(directory) / "example.png"
            media_path.write_bytes(b"test-png-bytes")
            for upload_url in unsafe_urls:
                with self.subTest(upload_url=upload_url):
                    presign = {
                        "media_asset_id": "media-1",
                        "upload_url": upload_url,
                        "public_url": "https://cdn.example.com/user/media-1.png",
                    }
                    with api_server(presign) as (base_url, handler):
                        result = run_cli(
                            "media", "upload", str(media_path), base_url=base_url
                        )

                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(
                        json.loads(result.stderr)["error"]["type"], "response"
                    )
                    self.assertNotIn("secret-signature", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(len(handler.requests), 1)

    def test_does_not_follow_presigned_put_redirect(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            media_path = Path(directory) / "example.png"
            media_path.write_bytes(b"test-png-bytes")
            with api_server({"received": False}) as (receiver_url, receiver):
                with api_server(
                    b"redirect",
                    status=302,
                    headers={"Location": f"{receiver_url}/capture"},
                ) as (upload_origin, upload_handler):
                    with api_server({}) as (base_url, api_handler):
                        api_handler.response_queue = [
                            (
                                200,
                                {"Content-Type": "application/json"},
                                json.dumps(
                                    {
                                        "media_asset_id": "media-1",
                                        "upload_url": f"{upload_origin}/upload?signature=safe",
                                        "public_url": "https://cdn.example.com/user/media-1.png",
                                    }
                                ).encode(),
                            )
                        ]
                        result = run_cli(
                            "media", "upload", str(media_path), base_url=base_url
                        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(upload_handler.requests), 1)
        self.assertEqual(receiver.requests, [])


class PostTests(unittest.TestCase):
    def test_lists_publish_jobs_grouped_as_posts(self) -> None:
        jobs = [
            {"job_type": "publish", "payload": {"crosspost_group_id": "group-1"}},
            {"job_type": "publish", "payload": {"crosspost_group_id": "group-1"}},
            {"job_type": "other", "payload": {}},
            {"job_type": "publish", "payload": {"crosspost_group_id": "group-2"}},
        ]
        posts = [
            {"group_id": "group-1", "jobs": jobs[:2]},
            {"group_id": "group-2", "jobs": [jobs[3]]},
        ]
        with api_server(jobs) as (base_url, handler):
            result = run_cli("post", "list", base_url=base_url)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), posts)
        self.assertEqual([request["path"] for request in handler.requests], ["/tenant/jobs"])

    def test_lists_no_posts_without_detail_requests(self) -> None:
        with api_server([]) as (base_url, handler):
            result = run_cli("post", "list", base_url=base_url)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])
        self.assertEqual(len(handler.requests), 1)

    def test_creates_post_from_named_flags(self) -> None:
        request_body = {
            "post_kind": "text",
            "media_asset_ids": [],
            "run_at": "2026-07-15T12:00:00Z",
            "posts": [{
                "connected_account_id": "account-1", "title": "",
                "description": "hello", "tags": [], "options": {},
            }],
        }
        response_body = {"jobs": [{"id": "job-1", "payload": {"crosspost_group_id": "group-1"}}], "schedules": []}
        with api_server(response_body) as (base_url, handler):
            result = run_cli(
                "post", "create", "--account", "account-1", "--kind", "text",
                "--description", "hello", "--run-at", "2026-07-15T12:00:00Z",
                base_url=base_url,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["group_id"], "group-1")
        request = handler.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["path"], "/tenant/crossposts")
        self.assertEqual(json.loads(request["body"]), request_body)
        self.assertEqual(request["headers"]["Content-Type"], "application/json")

    def test_gets_post_group(self) -> None:
        response_body = {"group_id": "group-1"}
        with api_server(response_body) as (base_url, handler):
            result = run_cli("post", "get", "group-1", base_url=base_url)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(handler.requests[0]["method"], "GET")
        self.assertEqual(handler.requests[0]["path"], "/tenant/posts/group-1")

    def test_updates_scheduled_post_by_merging_current_state(self) -> None:
        request_body = {
            "post_kind": "text",
            "media_asset_ids": [],
            "run_at": "2026-07-16T12:00:00Z",
            "posts": [{
                "connected_account_id": "account-1", "title": "",
                "description": "updated", "tags": [], "options": {},
            }],
        }
        current = {**request_body, "group_id": "group-1"}
        response_body = {"group_id": "group-2"}
        with api_server(response_body) as (base_url, handler):
            handler.response_queue = [
                (200, {"Content-Type": "application/json"}, json.dumps(current).encode()),
                (200, {"Content-Type": "application/json"}, json.dumps(response_body).encode()),
            ]
            result = run_cli(
                "post", "update", "group-1", "--description", "updated",
                "--account", "account-2", base_url=base_url,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(handler.requests[0]["method"], "GET")
        self.assertEqual(handler.requests[1]["method"], "PATCH")
        updated_body = json.loads(handler.requests[1]["body"])
        self.assertEqual(updated_body["posts"][0], request_body["posts"][0])
        self.assertEqual(updated_body["posts"][1]["connected_account_id"], "account-2")
        self.assertEqual(json.loads(result.stdout)["group_id"], "group-2")

    def test_delete_requires_yes_without_network_request(self) -> None:
        result = run_cli("post", "delete", "group-1")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr)["error"]["type"], "usage")

    def test_deletes_post_with_confirmation(self) -> None:
        with api_server(b"", status=204) as (base_url, handler):
            result = run_cli("post", "delete", "group-1", "--yes", base_url=base_url)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"deleted": True, "resource": "post", "id": "group-1"},
        )
        self.assertEqual(handler.requests[0]["method"], "DELETE")
        self.assertEqual(handler.requests[0]["path"], "/tenant/posts/group-1")


class QueueTests(unittest.TestCase):
    queue_body = {
        "name": "Daily",
        "connected_account_ids": ["account-1"],
        "schedule": {"kind": "interval", "interval_minutes": 1440},
        "next_run_at": "2026-07-15T12:00:00Z",
    }

    def test_creates_queue(self) -> None:
        with api_server({"id": "queue-1"}) as (base_url, handler):
            result = run_cli(
                "queue", "create", "--name", "Daily", "--account", "account-1",
                "--interval-minutes", "1440", "--next-run-at", "2026-07-15T12:00:00Z",
                base_url=base_url,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(handler.requests[0]["method"], "POST")
        self.assertEqual(handler.requests[0]["path"], "/tenant/post-queues")
        body = json.loads(handler.requests[0]["body"])
        self.assertEqual(body["name"], "Daily")
        self.assertEqual(body["schedule"], {"kind": "interval", "interval_minutes": 1440})

    def test_lists_queues(self) -> None:
        with api_server([]) as (base_url, handler):
            result = run_cli("queue", "list", base_url=base_url)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(handler.requests[0]["method"], "GET")
        self.assertEqual(handler.requests[0]["path"], "/tenant/post-queues")

    def test_gets_queue(self) -> None:
        with api_server({"queue": {"id": "queue-1"}, "items": []}) as (
            base_url,
            handler,
        ):
            result = run_cli("queue", "get", "queue-1", base_url=base_url)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(handler.requests[0]["method"], "GET")
        self.assertEqual(handler.requests[0]["path"], "/tenant/post-queues/queue-1")

    def test_updates_queue_by_merging_current_state(self) -> None:
        updated = {
            **self.queue_body,
            "name": "Updated",
            "default_description": "caption",
        }
        detail = {"queue": {**updated, "id": "queue-1", "default_title": "", "default_tags": [], "default_post_options": {}}, "items": []}
        with api_server({"id": "queue-1"}) as (base_url, handler):
            handler.response_queue = [
                (200, {"Content-Type": "application/json"}, json.dumps(detail).encode()),
                (200, {"Content-Type": "application/json"}, b'{"id":"queue-1"}'),
            ]
            result = run_cli("queue", "update", "queue-1", "--name", "Updated", base_url=base_url)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(handler.requests[0]["method"], "GET")
        self.assertEqual(handler.requests[1]["method"], "PATCH")
        self.assertEqual(json.loads(handler.requests[1]["body"])["name"], "Updated")

    def test_queue_delete_requires_yes(self) -> None:
        result = run_cli("queue", "delete", "queue-1")

        self.assertEqual(result.returncode, 2)
        self.assertIn("--yes", json.loads(result.stderr)["error"]["message"])

    def test_deletes_queue(self) -> None:
        with api_server(b"", status=204) as (base_url, handler):
            result = run_cli("queue", "delete", "queue-1", "--yes", base_url=base_url)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"deleted": True, "resource": "queue", "id": "queue-1"},
        )
        self.assertEqual(handler.requests[0]["method"], "DELETE")
        self.assertEqual(handler.requests[0]["path"], "/tenant/post-queues/queue-1")


class QueueItemTests(unittest.TestCase):
    def test_creates_queue_item(self) -> None:
        body = {
            "post_kind": "text",
            "media_asset_ids": [],
            "title": "",
            "description": "queued caption",
            "tags": [],
        }
        with api_server({"id": "item-1"}) as (base_url, handler):
            result = run_cli(
                "queue-item", "add", "queue-1", "--kind", "text",
                "--description", "queued caption",
                base_url=base_url,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(handler.requests[0]["method"], "POST")
        self.assertEqual(
            handler.requests[0]["path"], "/tenant/post-queues/queue-1/items"
        )
        self.assertEqual(json.loads(handler.requests[0]["body"]), body)

    def test_updates_queue_item_without_media_replacement(self) -> None:
        body = {
            "post_kind": "text",
            "title": "",
            "description": "updated caption",
            "tags": [],
        }
        detail = {"queue": {"id": "queue-1"}, "items": [{"id": "item-1", **body, "description": "old"}]}
        with api_server({"id": "item-1"}) as (base_url, handler):
            handler.response_queue = [
                (200, {"Content-Type": "application/json"}, json.dumps(detail).encode()),
                (200, {"Content-Type": "application/json"}, b'{"id":"item-1"}'),
            ]
            result = run_cli("queue-item", "update", "queue-1", "item-1", "--description", "updated caption", base_url=base_url)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(handler.requests[0]["method"], "GET")
        self.assertEqual(
            handler.requests[1]["path"],
            "/tenant/post-queues/queue-1/items/item-1",
        )
        self.assertEqual(json.loads(handler.requests[1]["body"]), body)

    def test_item_delete_requires_yes(self) -> None:
        result = run_cli("queue-item", "delete", "queue-1", "item-1")

        self.assertEqual(result.returncode, 2)
        self.assertIn("--yes", json.loads(result.stderr)["error"]["message"])

    def test_deletes_queue_item(self) -> None:
        with api_server(b"", status=204) as (base_url, handler):
            result = run_cli(
                "queue-item",
                "delete",
                "queue-1",
                "item-1",
                "--yes",
                base_url=base_url,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "deleted": True,
                "resource": "queue-item",
                "id": "item-1",
                "queue_id": "queue-1",
            },
        )
        self.assertEqual(handler.requests[0]["method"], "DELETE")
        self.assertEqual(
            handler.requests[0]["path"],
            "/tenant/post-queues/queue-1/items/item-1",
        )


class ErrorContractTests(unittest.TestCase):
    def test_invalid_json_input_is_usage_error_before_network(self) -> None:
        result = run_cli("post", "create", "--input", "-", stdin="{not-json")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr)["error"]["type"], "usage")

    def test_http_error_preserves_status_and_json_detail_without_key(self) -> None:
        with api_server({"detail": "invalid post"}, status=422) as (base_url, _):
            result = run_cli("account", "list", base_url=base_url)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        error = json.loads(result.stderr)["error"]
        self.assertEqual(error["type"], "http")
        self.assertEqual(error["status"], 422)
        self.assertEqual(error["detail"], {"detail": "invalid post"})
        self.assertNotIn("test-api-key", result.stderr)

    def test_http_error_redacts_a_reflected_api_key(self) -> None:
        with api_server({"test-api-key": "bad test-api-key value"}, status=400) as (
            base_url,
            _,
        ):
            result = run_cli("account", "list", base_url=base_url)

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("test-api-key", result.stderr)
        self.assertIn("[REDACTED]", result.stderr)

    def test_invalid_success_response_is_response_error(self) -> None:
        with api_server(b"not-json") as (base_url, _):
            result = run_cli("account", "list", base_url=base_url)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr)["error"]["type"], "response")

    def test_network_failure_is_bounded_json_error(self) -> None:
        result = run_cli("account", "list")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr)["error"]["type"], "network")

    def test_timeout_becomes_bounded_network_error(self) -> None:
        namespace = runpy.run_path(str(CLI_PATH))
        config = namespace["Config"](
            api_key="test-api-key", base_url="http://127.0.0.1:8000"
        )
        opener = namespace["NO_REDIRECT_OPENER"]

        with mock.patch.object(opener, "open", side_effect=TimeoutError):
            with self.assertRaises(namespace["CliError"]) as raised:
                namespace["request_json"](config, "GET", "/tenant/connected-accounts")

        self.assertEqual(raised.exception.error_type, "network")
        self.assertNotIn("test-api-key", json.dumps(raised.exception.payload()))

    def test_oversized_success_and_error_bodies_are_bounded(self) -> None:
        oversized_success = b"x" * (10 * 1024 * 1024 + 1)
        with api_server(oversized_success) as (base_url, _):
            success_result = run_cli("account", "list", base_url=base_url)

        oversized_error = b"x" * (64 * 1024 + 1)
        with api_server(oversized_error, status=500) as (base_url, _):
            error_result = run_cli("account", "list", base_url=base_url)

        self.assertEqual(success_result.returncode, 1)
        self.assertEqual(json.loads(success_result.stderr)["error"]["type"], "response")
        self.assertEqual(error_result.returncode, 1)
        self.assertLess(len(error_result.stderr), 1024)

    def test_oversized_json_input_is_rejected_before_network(self) -> None:
        oversized_input = '{"value":"' + ("x" * (10 * 1024 * 1024)) + '"}'
        result = run_cli("post", "create", "--input", "-", stdin=oversized_input)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"]["type"], "usage")


if __name__ == "__main__":
    unittest.main()
