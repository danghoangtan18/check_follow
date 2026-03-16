#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


APP_NAME = "TikTokFollowChecker"
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)).resolve()


def get_data_dir() -> Path:
    if getattr(sys, "frozen", False) and sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / APP_NAME).resolve()

    executable_path = Path(
        sys.executable if getattr(sys, "frozen", False) else __file__
    ).resolve()
    return executable_path.parent


DATA_DIR = get_data_dir()
DEFAULT_INPUT_FILES = ("users.txt", "users.example.txt")
UNIVERSAL_DATA_SCRIPT_ID = "__UNIVERSAL_DATA_FOR_REHYDRATION__"
REQUEST_HEADERS = {
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "referer": "https://www.tiktok.com/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
}

try:
    import certifi
except ImportError:  # pragma: no cover - optional dependency fallback
    certifi = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check public TikTok follower/following stats",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="TikTok username, @username, or profile URL",
    )
    parser.add_argument(
        "--file",
        dest="file_path",
        help="Read usernames from a text file, one username per line",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON instead of a text table",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Paste multiple usernames directly into the tool",
    )
    return parser.parse_args()


def read_users_from_file(file_path: str) -> list[str]:
    content = Path(file_path).read_text(encoding="utf-8")
    return [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def read_users_from_stdin(interactive: bool) -> list[str]:
    if interactive:
        print("Nhap username TikTok, moi dong 1 user.")
        print("Ban co the paste ca danh sach. Nhan Enter o dong trong de bat dau check.")

    users: list[str] = []

    while True:
        try:
            line = input("> " if interactive else "")
        except EOFError:
            break

        stripped = line.strip()

        if interactive and not stripped:
            break

        if stripped and not stripped.startswith("#"):
            users.append(stripped)

    return users


def normalize_username(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        raise ValueError("Empty username")

    if value.lower().startswith(("http://", "https://")):
        parsed = urlparse(value)
        segments = [segment for segment in parsed.path.split("/") if segment]
        account_segment = next(
            (segment for segment in segments if segment.startswith("@")),
            None,
        )
        if not account_segment:
            raise ValueError(f"Could not find TikTok username in URL: {value}")
        return account_segment[1:]

    return value[1:] if value.startswith("@") else value


def extract_json_from_html(html: str, script_id: str) -> str:
    pattern = re.compile(
        rf'<script[^>]*id="{re.escape(script_id)}"[^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html)
    if not match:
        raise ValueError(f"Could not find script tag: {script_id}")
    return match.group(1)


def to_number(value: Any) -> int | None:
    if value in (None, ""):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def format_number(value: int | None) -> str:
    return "-" if value is None else f"{value:,}"


def should_retry(message: str) -> bool:
    retry_signals = (
        "Could not find script tag",
        "Could not parse TikTok embedded profile data",
        "HTTP 429",
        "Temporary failure",
        "timed out",
    )
    return any(signal in message for signal in retry_signals)


def create_ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())

    return ssl.create_default_context()


def fetch_profile_stats(username: str) -> dict[str, Any]:
    profile_url = f"https://www.tiktok.com/@{quote(username)}?lang=en"
    request = Request(profile_url, headers=REQUEST_HEADERS)
    ssl_context = create_ssl_context()

    try:
        with urlopen(request, timeout=20, context=ssl_context) as response:
            html = response.read().decode("utf-8", errors="replace")
            status_code = getattr(response, "status", 200)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except URLError as exc:
        reason = exc.reason if getattr(exc, "reason", None) else "Request failed"
        raise RuntimeError(str(reason)) from exc

    embedded_json = extract_json_from_html(html, UNIVERSAL_DATA_SCRIPT_ID)

    try:
        parsed_data = json.loads(embedded_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Could not parse TikTok embedded profile data") from exc

    detail = (
        parsed_data.get("__DEFAULT_SCOPE__", {})
        .get("webapp.user-detail")
    )
    if not detail:
        raise RuntimeError("TikTok profile payload was missing user detail data")

    user_info = detail.get("userInfo") or {}
    user = user_info.get("user") or {}
    stats = user_info.get("statsV2") or user_info.get("stats")

    if not stats:
        message = detail.get("statusMsg") or f"HTTP {status_code}"
        raise RuntimeError(message)

    unique_id = user.get("uniqueId") or username
    return {
        "ok": True,
        "input": username,
        "uniqueId": unique_id,
        "nickname": user.get("nickname") or "",
        "followers": to_number(stats.get("followerCount")),
        "following": to_number(stats.get("followingCount")),
        "likes": to_number(stats.get("heartCount", stats.get("heart"))),
        "videos": to_number(stats.get("videoCount")),
        "verified": bool(user.get("verified")),
        "privateAccount": bool(user.get("privateAccount")),
        "statusCode": detail.get("statusCode"),
        "statusMsg": detail.get("statusMsg") or "OK",
        "profileUrl": f"https://www.tiktok.com/@{unique_id}",
    }


def fetch_profile_stats_with_retry(
    username: str,
    max_attempts: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fetch_profile_stats(username)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            message = str(exc)
            if attempt == max_attempts or not should_retry(message):
                raise
            time.sleep(0.5 * attempt)

    if last_error is None:
        raise RuntimeError("Unknown error")
    raise last_error


def collect_stats(usernames: list[str]) -> list[dict[str, Any]]:
    return collect_stats_with_callback(usernames)


def collect_stats_with_callback(
    usernames: list[str],
    progress_callback: Any | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    total = len(usernames)

    for index, username in enumerate(usernames, start=1):
        try:
            result = fetch_profile_stats_with_retry(username)
        except Exception as exc:  # noqa: BLE001
            result = {
                "ok": False,
                "input": username,
                "uniqueId": username,
                "nickname": "",
                "followers": None,
                "following": None,
                "likes": None,
                "videos": None,
                "verified": False,
                "privateAccount": False,
                "statusCode": None,
                "statusMsg": str(exc),
                "profileUrl": f"https://www.tiktok.com/@{username}",
            }

        results.append(result)

        if progress_callback is not None:
            progress_callback(index, total, result)

    return results


def build_unique_usernames(raw_inputs: list[str]) -> list[str]:
    unique_usernames: list[str] = []
    seen: set[str] = set()

    for raw_input in raw_inputs:
        username = normalize_username(raw_input)
        if username not in seen:
            seen.add(username)
            unique_usernames.append(username)

    return unique_usernames


def print_table(results: list[dict[str, Any]]) -> None:
    rows = [
        {
            "username": result["uniqueId"],
            "followers": format_number(result["followers"]),
            "following": format_number(result["following"]),
            "likes": format_number(result["likes"]),
            "private": "yes" if result["privateAccount"] else "no",
            "verified": "yes" if result["verified"] else "no",
            "status": "ok" if result["ok"] else result["statusMsg"],
        }
        for result in results
    ]

    headers = [
        "username",
        "followers",
        "following",
        "likes",
        "private",
        "verified",
        "status",
    ]

    widths = {
        header: max(
            len(header),
            *(len(str(row[header])) for row in rows),
        )
        for header in headers
    }

    header_line = " | ".join(header.ljust(widths[header]) for header in headers)
    separator = "-+-".join("-" * widths[header] for header in headers)
    print(header_line)
    print(separator)

    for row in rows:
        print(
            " | ".join(
                str(row[header]).ljust(widths[header])
                for header in headers
            )
        )


def build_username_list(args: argparse.Namespace) -> list[str]:
    raw_inputs = list(args.inputs)

    if args.file_path:
        raw_inputs.extend(read_users_from_file(args.file_path))

    if args.interactive or (not raw_inputs and not args.file_path and sys.stdin.isatty()):
        raw_inputs.extend(read_users_from_stdin(interactive=True))

    elif not raw_inputs and not sys.stdin.isatty():
        raw_inputs.extend(read_users_from_stdin(interactive=False))

    if not raw_inputs:
        for file_name in DEFAULT_INPUT_FILES:
            for base_dir in (DATA_DIR, RESOURCE_DIR):
                default_file = base_dir / file_name
                if default_file.exists():
                    raw_inputs = read_users_from_file(str(default_file))
                    break
            if raw_inputs:
                break

    if not raw_inputs:
        raise RuntimeError(
            "No usernames provided. Try: "
            "python check_follow.py tiktok, "
            "python check_follow.py --interactive, "
            "or python check_follow.py --file users.example.txt"
        )

    return build_unique_usernames(raw_inputs)


def main() -> int:
    args = parse_args()

    try:
        usernames = build_username_list(args)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    results = collect_stats(usernames)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print_table(results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
