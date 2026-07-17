from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://public-api.post-queue.com"
API_PREFIX = "/v1"
CONFIG_PATH = Path(__file__).resolve().parent.parent / ".env"
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_ERROR_BYTES = 64 * 1024


class CliError(Exception):
    def __init__(
        self,
        error_type: str,
        message: str,
        *,
        exit_code: int,
        status: int | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.exit_code = exit_code
        self.status = status
        self.detail = detail

    def payload(self) -> dict[str, Any]:
        error: dict[str, Any] = {"type": self.error_type, "message": self.message}
        if self.status is not None:
            error["status"] = self.status
        if self.detail is not None:
            error["detail"] = self.detail
        return {"error": error}


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliError("usage", message, exit_code=2)


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url
        return None


NO_REDIRECT_OPENER = urllib.request.build_opener(RejectRedirects)


def validate_base_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise CliError(
            "usage", "POST_QUEUE_BASE_URL is invalid.", exit_code=2
        ) from error
    is_loopback = parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    is_loopback_origin = is_loopback and parsed.scheme in {"http", "https"}
    is_production_origin = (
        parsed.scheme == "https"
        and parsed.hostname == "public-api.post-queue.com"
        and port in {None, 443}
    )
    if not is_production_origin and not is_loopback_origin:
        raise CliError(
            "usage",
            "POST_QUEUE_BASE_URL must be the Post Queue API or a loopback origin.",
            exit_code=2,
        )
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CliError(
            "usage",
            "POST_QUEUE_BASE_URL must be an origin without credentials.",
            exit_code=2,
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise CliError(
            "usage",
            "POST_QUEUE_BASE_URL must not include a path, query, or fragment.",
            exit_code=2,
        )
    return value.rstrip("/")


def load_config() -> Config:
    saved = read_config_file()
    api_key = os.environ.get("POST_QUEUE_API_KEY", saved.get("POST_QUEUE_API_KEY", "")).strip()
    if not api_key:
        raise CliError(
            "configuration",
            "POST_QUEUE_API_KEY is required.",
            exit_code=2,
        )
    if any(character.isspace() for character in api_key):
        raise CliError(
            "configuration",
            "POST_QUEUE_API_KEY must not contain whitespace.",
            exit_code=2,
        )
    base_url = validate_base_url(
        os.environ.get("POST_QUEUE_BASE_URL", saved.get("POST_QUEUE_BASE_URL", DEFAULT_BASE_URL)).strip()
    )
    return Config(api_key=api_key, base_url=base_url)


def read_config_file() -> dict[str, str]:
    try:
        lines = CONFIG_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise CliError("configuration", f"Could not read {CONFIG_PATH}: {error}.", exit_code=2) from error
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, value = stripped.partition("=")
        if separator and name in {"POST_QUEUE_API_KEY", "POST_QUEUE_BASE_URL"}:
            values[name] = value.strip().strip("'\"")
    return values


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(prog="post_queue.py")
    resources = parser.add_subparsers(dest="resource", required=True)
    accounts = resources.add_parser("account")
    account_commands = accounts.add_subparsers(dest="command", required=True)
    account_commands.add_parser("list")

    media = resources.add_parser("media")
    media_commands = media.add_subparsers(dest="command", required=True)
    media_upload = media_commands.add_parser("upload")
    media_upload.add_argument("file")

    posts = resources.add_parser("post")
    post_commands = posts.add_subparsers(dest="command", required=True)
    post_create = post_commands.add_parser("create")
    add_post_fields(post_create, require_core=True)
    post_commands.add_parser("list")
    post_get = post_commands.add_parser("get")
    post_get.add_argument("group_id")
    post_update = post_commands.add_parser("update")
    post_update.add_argument("group_id")
    add_post_fields(post_update, require_core=False)
    post_delete = post_commands.add_parser("delete")
    post_delete.add_argument("group_id")
    post_delete.add_argument("--yes", action="store_true")

    queues = resources.add_parser("queue")
    queue_commands = queues.add_subparsers(dest="command", required=True)
    queue_create = queue_commands.add_parser("create")
    add_queue_fields(queue_create, require_core=True)
    queue_commands.add_parser("list")
    queue_get = queue_commands.add_parser("get")
    queue_get.add_argument("queue_id")
    queue_update = queue_commands.add_parser("update")
    queue_update.add_argument("queue_id")
    add_queue_fields(queue_update, require_core=False)
    queue_delete = queue_commands.add_parser("delete")
    queue_delete.add_argument("queue_id")
    queue_delete.add_argument("--yes", action="store_true")

    queue_items = resources.add_parser("queue-item")
    item_commands = queue_items.add_subparsers(dest="command", required=True)
    item_create = item_commands.add_parser("add")
    item_create.add_argument("queue_id")
    add_item_fields(item_create, require_kind=True)
    item_update = item_commands.add_parser("update")
    item_update.add_argument("queue_id")
    item_update.add_argument("item_id")
    add_item_fields(item_update, require_kind=False, allow_media=False)
    item_delete = item_commands.add_parser("delete")
    item_delete.add_argument("queue_id")
    item_delete.add_argument("item_id")
    item_delete.add_argument("--yes", action="store_true")
    return parser


def add_copy_fields(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title")
    parser.add_argument("--description")
    parser.add_argument("--tag", action="append", default=None)
    parser.add_argument("--clear-tags", action="store_true")


def add_option_fields(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--youtube-privacy", choices=("public", "unlisted", "private"))
    parser.add_argument(
        "--tiktok-privacy",
        choices=(
            "PUBLIC_TO_EVERYONE",
            "MUTUAL_FOLLOW_FRIENDS",
            "FOLLOWER_OF_CREATOR",
            "SELF_ONLY",
        ),
    )
    for name in (
        "tiktok-draft", "tiktok-disable-comment", "tiktok-auto-add-music",
        "tiktok-brand-content", "tiktok-brand-organic",
        "tiktok-music-usage-confirmed", "facebook-draft",
    ):
        parser.add_argument(f"--{name}", action=argparse.BooleanOptionalAction)


def add_post_fields(parser: argparse.ArgumentParser, *, require_core: bool) -> None:
    parser.add_argument("--account", action="append", required=require_core)
    if not require_core:
        parser.add_argument("--remove-account", action="append")
    parser.add_argument("--kind", choices=("video", "image", "carousel", "text"), required=require_core)
    parser.add_argument("--run-at", required=require_core)
    parser.add_argument("--media", action="append", default=None)
    add_copy_fields(parser)
    add_option_fields(parser)


def add_queue_fields(parser: argparse.ArgumentParser, *, require_core: bool) -> None:
    parser.add_argument("--name", required=require_core)
    parser.add_argument("--account", action="append", required=require_core)
    if not require_core:
        parser.add_argument("--remove-account", action="append")
    schedule = parser.add_mutually_exclusive_group(required=require_core)
    schedule.add_argument("--interval-minutes", type=int)
    schedule.add_argument("--cron")
    parser.add_argument("--next-run-at")
    parser.add_argument("--timezone")
    add_copy_fields(parser)
    add_option_fields(parser)


def add_item_fields(
    parser: argparse.ArgumentParser, *, require_kind: bool, allow_media: bool = True
) -> None:
    parser.add_argument("--kind", choices=("video", "image", "carousel", "text"), required=require_kind)
    if allow_media:
        parser.add_argument("--media", action="append", default=None)
    add_copy_fields(parser)


def read_limited(response: Any, limit: int) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise CliError(
            "response", "Server response exceeded the size limit.", exit_code=1
        )
    return body


def redact_value(value: Any, secret: str) -> Any:
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]")
    if isinstance(value, list):
        return [redact_value(item, secret) for item in value]
    if isinstance(value, dict):
        return {
            str(key).replace(secret, "[REDACTED]"): redact_value(item, secret)
            for key, item in value.items()
        }
    return value


def request_json(
    config: Config,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {config.api_key}",
        "User-Agent": "post-queue-cli/1.0",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{config.base_url}{API_PREFIX}{path}",
        method=method,
        headers=headers,
        data=data,
    )
    try:
        with NO_REDIRECT_OPENER.open(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            if response.status == 204:
                return None
            body = read_limited(response, MAX_RESPONSE_BYTES)
    except urllib.error.HTTPError as error:
        detail_body = error.read(MAX_ERROR_BYTES + 1)
        if len(detail_body) > MAX_ERROR_BYTES:
            detail: Any = "HTTP error body exceeded the size limit."
        else:
            try:
                detail = json.loads(detail_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                detail = detail_body.decode("utf-8", errors="replace")
        detail = redact_value(detail, config.api_key)
        raise CliError(
            "http",
            f"Post Queue returned HTTP {error.code}.",
            exit_code=1,
            status=error.code,
            detail=detail,
        ) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise CliError("network", "Could not reach Post Queue.", exit_code=1) from error
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CliError(
            "response", "Post Queue returned invalid JSON.", exit_code=1
        ) from error


def require_string(payload: Any, field: str) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get(field), str):
        raise CliError(
            "response",
            f"Post Queue response is missing string field {field!r}.",
            exit_code=1,
        )
    return payload[field]


def validate_upload_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise CliError(
            "response", "Post Queue returned an invalid upload URL.", exit_code=1
        ) from error
    is_loopback_http = parsed.scheme == "http" and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if parsed.scheme != "https" and not is_loopback_http:
        raise CliError(
            "response", "Post Queue returned an unsafe upload URL.", exit_code=1
        )
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port is None
        and ":" in parsed.netloc.rsplit("]", 1)[-1]
    ):
        raise CliError(
            "response", "Post Queue returned an invalid upload URL.", exit_code=1
        )
    return value


def put_file(
    upload_url: str, file_path: Path, content_type: str, size_bytes: int
) -> None:
    headers = {
        "Content-Type": content_type,
        "Content-Length": str(size_bytes),
        "User-Agent": "post-queue-cli/1.0",
    }
    try:
        with file_path.open("rb") as upload_file:
            request = urllib.request.Request(
                upload_url,
                method="PUT",
                headers=headers,
                data=upload_file,
            )
            with NO_REDIRECT_OPENER.open(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                read_limited(response, MAX_ERROR_BYTES)
    except urllib.error.HTTPError as error:
        raise CliError(
            "http",
            f"Media upload returned HTTP {error.code}.",
            exit_code=1,
            status=error.code,
        ) from error
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as error:
        raise CliError("network", "Could not upload media.", exit_code=1) from error


def upload_media(config: Config, file_name: str) -> Any:
    file_path = Path(file_name)
    try:
        size_bytes = file_path.stat().st_size
    except OSError as error:
        raise CliError(
            "usage", f"Could not read media file: {error}.", exit_code=2
        ) from error
    if not file_path.is_file() or size_bytes == 0:
        raise CliError(
            "usage", "Media file must be a non-empty regular file.", exit_code=2
        )
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    presign = request_json(
        config,
        "POST",
        "/tenant/media-assets/presign",
        {
            "filename": file_path.name,
            "content_type": content_type,
            "size_bytes": size_bytes,
        },
    )
    media_asset_id = require_string(presign, "media_asset_id")
    upload_url = validate_upload_url(require_string(presign, "upload_url"))
    public_url = require_string(presign, "public_url")
    put_file(upload_url, file_path, content_type, size_bytes)
    return request_json(
        config,
        "POST",
        "/tenant/media-assets",
        {
            "media_asset_id": media_asset_id,
            "asset_type": "uploaded",
            "object_url": public_url,
            "content_type": content_type,
            "filename": file_path.name,
        },
    )


def option_changes(arguments: argparse.Namespace) -> dict[str, Any]:
    mapping = {
        "youtube_privacy": "youtube_privacy_status",
        "tiktok_privacy": "tiktok_privacy_level",
        "tiktok_draft": "tiktok_draft",
        "tiktok_disable_comment": "tiktok_disable_comment",
        "tiktok_auto_add_music": "tiktok_auto_add_music",
        "tiktok_brand_content": "tiktok_brand_content",
        "tiktok_brand_organic": "tiktok_brand_organic",
        "tiktok_music_usage_confirmed": "tiktok_music_usage_confirmed",
        "facebook_draft": "facebook_draft",
    }
    return {
        target: value
        for source, target in mapping.items()
        if (value := getattr(arguments, source, None)) is not None
    }


def merged_tags(arguments: argparse.Namespace, current: list[str] | None = None) -> list[str]:
    if arguments.clear_tags:
        return []
    if arguments.tag is not None:
        return arguments.tag
    return current or []


def uploaded_ids(config: Config, paths: list[str] | None) -> list[str]:
    return [require_string(upload_media(config, path), "id") for path in paths or []]


def validate_media(kind: str, paths: list[str] | None) -> None:
    count = len(paths or [])
    valid = {"text": count == 0, "video": count == 1, "image": count == 1,
             "carousel": 2 <= count <= 10}[kind]
    if not valid:
        raise CliError("usage", f"Invalid media count for {kind}.", exit_code=2)


def post_body(arguments: argparse.Namespace, config: Config, current: dict[str, Any] | None = None) -> dict[str, Any]:
    current_kind = (current or {}).get("post_kind")
    kind = arguments.kind or current_kind
    if not isinstance(kind, str):
        raise CliError("response", "Post response is missing post_kind.", exit_code=1)
    if current is not None and arguments.kind is not None and arguments.kind != current_kind:
        raise CliError("usage", "Post kind cannot be changed.", exit_code=2)
    if arguments.media is not None:
        validate_media(kind, arguments.media)
        media_ids = uploaded_ids(config, arguments.media)
    else:
        media_ids = list((current or {}).get("media_asset_ids", []))
        if current is None:
            validate_media(kind, None)
    old_posts = (current or {}).get("posts", [])
    old_by_account = {post["connected_account_id"]: post for post in old_posts}
    accounts = list(old_by_account)
    for account_id in arguments.account or []:
        if account_id not in accounts:
            accounts.append(account_id)
    removed = set(getattr(arguments, "remove_account", None) or [])
    accounts = [account_id for account_id in accounts if account_id not in removed]
    if current is None:
        accounts = arguments.account
    if not accounts:
        raise CliError("usage", "At least one account is required.", exit_code=2)
    changes = option_changes(arguments)
    posts = []
    for account_id in accounts:
        old = old_by_account.get(account_id, {})
        options = dict(old.get("options", {}))
        options.update(changes)
        posts.append({
            "connected_account_id": account_id,
            "title": arguments.title if arguments.title is not None else old.get("title", ""),
            "description": arguments.description if arguments.description is not None else old.get("description", ""),
            "tags": merged_tags(arguments, old.get("tags", [])),
            "options": options,
        })
    return {
        "post_kind": kind,
        "media_asset_ids": media_ids,
        "run_at": arguments.run_at or (current or {}).get("run_at"),
        "posts": posts,
    }


def queue_body(arguments: argparse.Namespace, current: dict[str, Any] | None = None) -> dict[str, Any]:
    old = current or {}
    if arguments.interval_minutes is not None:
        schedule = {"kind": "interval", "interval_minutes": arguments.interval_minutes}
    elif arguments.cron is not None:
        if not arguments.timezone:
            raise CliError("usage", "--timezone is required with --cron.", exit_code=2)
        schedule = {"kind": "cron", "expression": arguments.cron, "timezone": arguments.timezone}
    else:
        schedule = old.get("schedule")
    if not isinstance(schedule, dict):
        raise CliError("usage", "A queue schedule is required.", exit_code=2)
    next_run_at = arguments.next_run_at if arguments.next_run_at is not None else old.get("next_run_at")
    if schedule["kind"] == "interval" and not next_run_at:
        raise CliError("usage", "--next-run-at is required for an interval queue.", exit_code=2)
    accounts = list(old.get("connected_account_ids", []))
    for account_id in arguments.account or []:
        if account_id not in accounts:
            accounts.append(account_id)
    removed = set(getattr(arguments, "remove_account", None) or [])
    accounts = [account_id for account_id in accounts if account_id not in removed]
    if current is None:
        accounts = arguments.account
    if not accounts:
        raise CliError("usage", "At least one account is required.", exit_code=2)
    changes = option_changes(arguments)
    defaults = {account: dict(old.get("default_post_options", {}).get(account, {})) for account in accounts}
    for options in defaults.values():
        options.update(changes)
    return {
        "name": arguments.name if arguments.name is not None else old.get("name"),
        "connected_account_ids": accounts,
        "schedule": schedule,
        "next_run_at": next_run_at if schedule["kind"] == "interval" else None,
        "default_title": arguments.title if arguments.title is not None else old.get("default_title", ""),
        "default_description": arguments.description if arguments.description is not None else old.get("default_description", ""),
        "default_tags": merged_tags(arguments, old.get("default_tags", [])),
        "default_post_options": defaults,
    }


def item_body(arguments: argparse.Namespace, config: Config, current: dict[str, Any] | None = None) -> dict[str, Any]:
    old = current or {}
    kind = arguments.kind or old.get("post_kind")
    if not isinstance(kind, str):
        raise CliError("response", "Queue item is missing post_kind.", exit_code=1)
    body = {
        "post_kind": kind,
        "title": arguments.title if arguments.title is not None else old.get("title", ""),
        "description": arguments.description if arguments.description is not None else old.get("description", ""),
        "tags": merged_tags(arguments, old.get("tags", [])),
    }
    if current is None:
        validate_media(kind, arguments.media)
        body["media_asset_ids"] = uploaded_ids(config, arguments.media)
    return body


def with_group_id(response: Any) -> Any:
    if not isinstance(response, dict) or "group_id" in response:
        return response
    jobs = response.get("jobs", [])
    if jobs and isinstance(jobs[0], dict):
        group_id = jobs[0].get("payload", {}).get("crosspost_group_id")
        if isinstance(group_id, str):
            return {"group_id": group_id, **response}
    return response


def list_posts(config: Config) -> list[dict[str, Any]]:
    jobs = request_json(config, "GET", "/tenant/jobs")
    if not isinstance(jobs, list):
        raise CliError("response", "Jobs response must be a list.", exit_code=1)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        if not isinstance(job, dict) or job.get("job_type") != "publish":
            continue
        payload = job.get("payload")
        group_id = payload.get("crosspost_group_id") if isinstance(payload, dict) else None
        if not isinstance(group_id, str):
            raise CliError("response", "Publish job is missing crosspost_group_id.", exit_code=1)
        grouped.setdefault(group_id, []).append(job)
    return [
        {"group_id": group_id, "jobs": group_jobs}
        for group_id, group_jobs in grouped.items()
    ]


def dispatch(arguments: argparse.Namespace, config: Config) -> Any:
    if arguments.resource == "account" and arguments.command == "list":
        return request_json(config, "GET", "/tenant/connected-accounts")
    if arguments.resource == "media" and arguments.command == "upload":
        return upload_media(config, arguments.file)
    if arguments.resource == "post":
        if arguments.command == "create":
            return with_group_id(request_json(config, "POST", "/tenant/crossposts", post_body(arguments, config)))
        if arguments.command == "list":
            return list_posts(config)
        group_id = urllib.parse.quote(arguments.group_id, safe="")
        path = f"/tenant/posts/{group_id}"
        if arguments.command == "get":
            return request_json(config, "GET", path)
        if arguments.command == "update":
            current = request_json(config, "GET", path)
            return request_json(config, "PATCH", path, post_body(arguments, config, current))
        if arguments.command == "delete":
            if not arguments.yes:
                raise CliError(
                    "usage",
                    "Deleting a post requires explicit confirmation with --yes.",
                    exit_code=2,
                )
            request_json(config, "DELETE", path)
            return {"deleted": True, "resource": "post", "id": arguments.group_id}
    if arguments.resource == "queue":
        base_path = "/tenant/post-queues"
        if arguments.command == "create":
            return request_json(config, "POST", base_path, queue_body(arguments))
        if arguments.command == "list":
            return request_json(config, "GET", base_path)
        queue_id = urllib.parse.quote(arguments.queue_id, safe="")
        path = f"{base_path}/{queue_id}"
        if arguments.command == "get":
            return request_json(config, "GET", path)
        if arguments.command == "update":
            detail = request_json(config, "GET", path)
            if not isinstance(detail, dict) or not isinstance(detail.get("queue"), dict):
                raise CliError("response", "Post Queue response is missing queue.", exit_code=1)
            return request_json(config, "PATCH", path, queue_body(arguments, detail["queue"]))
        if arguments.command == "delete":
            if not arguments.yes:
                raise CliError(
                    "usage",
                    "Deleting a queue requires explicit confirmation with --yes.",
                    exit_code=2,
                )
            request_json(config, "DELETE", path)
            return {"deleted": True, "resource": "queue", "id": arguments.queue_id}
    if arguments.resource == "queue-item":
        queue_id = urllib.parse.quote(arguments.queue_id, safe="")
        base_path = f"/tenant/post-queues/{queue_id}/items"
        if arguments.command == "add":
            return request_json(config, "POST", base_path, item_body(arguments, config))
        item_id = urllib.parse.quote(arguments.item_id, safe="")
        path = f"{base_path}/{item_id}"
        if arguments.command == "update":
            detail = request_json(config, "GET", f"/tenant/post-queues/{queue_id}")
            items = detail.get("items", []) if isinstance(detail, dict) else []
            current = next((item for item in items if item.get("id") == arguments.item_id), None)
            if current is None:
                raise CliError("response", "Queue item was not found in the queue response.", exit_code=1)
            return request_json(config, "PATCH", path, item_body(arguments, config, current))
        if arguments.command == "delete":
            if not arguments.yes:
                raise CliError(
                    "usage",
                    "Deleting a queue item requires explicit confirmation with --yes.",
                    exit_code=2,
                )
            request_json(config, "DELETE", path)
            return {
                "deleted": True,
                "resource": "queue-item",
                "id": arguments.item_id,
                "queue_id": arguments.queue_id,
            }
    raise CliError("usage", "Unsupported command.", exit_code=2)


def main() -> int:
    try:
        arguments = build_parser().parse_args()
        result = dispatch(arguments, load_config())
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    except CliError as error:
        json.dump(error.payload(), sys.stderr, ensure_ascii=False)
        sys.stderr.write("\n")
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
