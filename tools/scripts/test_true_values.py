from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any
import sys

import aiohttp

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from client import HomesideClient


VARIABLES_FILE = ROOT_DIR / "variables.json"


def _is_true_value(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return False


def _load_enabled_entries() -> list[dict[str, Any]]:
    if not VARIABLES_FILE.exists():
        return []
    raw = json.loads(VARIABLES_FILE.read_text(encoding="utf-8"))
    mapping = raw.get("mapping") or {}
    entries: list[dict[str, Any]] = []
    for address, info in mapping.items():
        if not isinstance(info, dict):
            continue
        if not info.get("enabled"):
            continue
        if not isinstance(address, str) or ":" not in address:
            continue
        entries.append(
            {
                "address": address,
                "name": str(info.get("name") or address),
                "type": str(info.get("type") or "sensor"),
            }
        )
    return entries


async def _run(host: str, username: str, password: str) -> int:
    entries = _load_enabled_entries()
    if not entries:
        print("No enabled addresses found in variables.json")
        return 1

    addresses = [entry["address"] for entry in entries]
    by_address = {entry["address"]: entry for entry in entries}

    async with aiohttp.ClientSession() as session:
        client = HomesideClient(host, session, username=username, password=password)
        try:
            await client.connect()
            values, errors = await client.read_points_with_errors(addresses)
        except (ConnectionError, aiohttp.ClientError) as exc:
            print(f"Connection failed: {exc}")
            return 1
        finally:
            await client.close()

    print("Enabled values:")
    for address in sorted(addresses):
        entry = by_address[address]
        value = values.get(address)
        print(f"{address} | {entry['type']} | {entry['name']} = {value}")

    errors_present = {address: err for address, err in errors.items() if err}
    if errors_present:
        print("\nErrors:")
        for address, err in sorted(errors_present.items()):
            print(f"{address} = {err}")

    return 0


def main() -> int:
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    parser = argparse.ArgumentParser(description="Fetch true values from Homeside")
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", default="")
    parser.add_argument("--pass", dest="password", default="")
    args = parser.parse_args()
    return asyncio.run(_run(args.host, args.user, args.password))


if __name__ == "__main__":
    raise SystemExit(main())
