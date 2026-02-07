from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType
from Crypto.Cipher import AES

try:
    from .const import WS_PATH, ERROR_CODES
except ImportError:  # pragma: no cover - for script usage
    from const import WS_PATH, ERROR_CODES

_LOGGER = logging.getLogger(__name__)


@dataclass
class HomesideIdentity:
    controller_name: Optional[str] = None
    project_name: Optional[str] = None
    serial: Optional[str] = None


class HomesideClient:
    def __init__(
        self,
        host: str,
        session: ClientSession,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._host = host
        self._session = session
        self._username = username or ""
        self._password = password or ""
        self._ws: ClientWebSocketResponse | None = None
        self._identity = HomesideIdentity()
        self._lock = asyncio.Lock()
        self._login_success: bool | None = None
        self._session_level: int | None = None
        self._client_nonce1: int | None = None
        self._client_nonce2: int | None = None
        self._challenge_confirmation: int | None = None
        self._peek_context = 0
        self._advise_context = 200100
        self._items_per_read = 80
        self._slave_items_per_read = 80
        self._items_per_read_min_limit = 5
        self._error_codes: dict[int, str] = {}

    @property
    def identity(self) -> HomesideIdentity:
        return self._identity

    @property
    def ws_url(self) -> str:
        return f"ws://{self._host}{WS_PATH}"

    async def connect(self) -> None:
        async with self._lock:
            if self._ws and not self._ws.closed:
                return
            self._ws = await self._session.ws_connect(
                self.ws_url,
                protocols=["EXOsocket"],
                heartbeat=60,
                receive_timeout=None,
            )
            await self._send_json(
                {
                    "method": "versionOffer",
                    "params": {"version": 1, "featureLevel": 0, "capabilities": 0},
                }
            )
            await self._await_method("versionAck")
            await self._send_json(
                {
                    "method": "identity",
                    "params": {
                        "implementation": "ControllerWebFramework",
                        "implementationVersion": "2.0-0-00",
                        "sessionID": 1,
                    },
                }
            )
            msg = await self._await_method("identity")
            params = msg.get("params", {})
            self._identity = HomesideIdentity(
                controller_name=params.get("controllerName"),
                project_name=params.get("projectName"),
                serial=params.get("serial"),
            )

            await self._load_error_codes()

            if self._username or self._password:
                await self.login(self._username, self._password)

    async def close(self) -> None:
        async with self._lock:
            if self._ws and not self._ws.closed:
                await self._ws.close()
            self._ws = None

    async def ping(self) -> None:
        async with self._lock:
            await self._send_json({"method": "ping"})
            await self._await_method("pingAck")

    async def login(self, username: str, password: str) -> None:
        self._client_nonce1 = self._swap_end(self._rand_u32())
        await self._send_json(
            {
                "method": "getChallenge",
                "params": {"clientNonce1": self._client_nonce1},
            }
        )
        challenge = await self._await_method("authChallenge")
        server_nonce = challenge.get("params", {}).get("serverNonce")
        if server_nonce is None:
            raise ConnectionError("Auth challenge missing serverNonce")

        client_nonce2, response, confirmation = self._compute_auth_response(
            username, password, server_nonce
        )
        self._client_nonce2 = client_nonce2
        self._challenge_confirmation = confirmation
        await self._send_json(
            {
                "method": "authenticate",
                "params": {
                    "user": username,
                    "clientNonce2": client_nonce2,
                    "challengeResponse": response,
                },
            }
        )

        auth_reply = await self._await_method("authenticateReply")
        if "error" in auth_reply:
            raise ConnectionError(f"Login failed: {auth_reply['error']}")

        confirmation_reply = auth_reply.get("params", {}).get("confirmation")
        if (
            confirmation_reply is None
            or confirmation_reply != self._challenge_confirmation
        ):
            raise ConnectionError("Login confirmation mismatch")

        session_level = await self._await_method("sessionLevel")
        self._session_level = session_level.get("params", {}).get("sessionLevel")
        self._login_success = True

    async def peek(self, full_path: str, variables: list[str]) -> dict[str, Any]:
        _LOGGER.debug("Peek on %s with %d variables", full_path, len(variables))
        return await self.read_points(variables)

    async def add_advise(self, full_path: str, variables: list[str]) -> dict[str, Any]:
        _LOGGER.debug("AddAdvise on %s with %d variables", full_path, len(variables))
        return await self.read_points(variables, advise=True)

    async def read_points(
        self, variables: list[str], advise: bool = False
    ) -> dict[str, Any]:
        values, _errors = await self.read_points_with_errors(variables, advise=advise)
        return values

    async def read_points_with_errors(
        self, variables: list[str], advise: bool = False
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        if not variables:
            return {}, {}

        async with self._lock:
            objects = self._build_read_objects(variables)
            pending_contexts: set[int] = set()
            for obj in objects:
                context = self._next_context(advise=advise)
                pending_contexts.add(context)
                await self._send_json(self._build_read_message(context, obj))

            updates = await self._await_updates(pending_contexts)
            values: dict[str, Any] = {}
            errors: dict[str, dict[str, Any]] = {}
            for payload in updates.values():
                values.update(payload.get("values", {}))
                errors.update(payload.get("errors", {}))
            return values, errors

    async def write_point(self, variable: str, value: float | int) -> bool:
        """Write a single value to a device point.
        
        Args:
            variable: Point address in format "device:item" (e.g., "0:332")
            value: Value to write (int or float)
            
        Returns:
            True if write was successful, False otherwise
            
        Raises:
            ValueError: If variable format is invalid
            ConnectionError: If WebSocket is not connected
        """
        if ":" not in variable:
            raise ValueError(f"Invalid variable format: {variable}. Expected 'device:item'")
        
        device_str, item_str = variable.split(":", 1)
        try:
            device = int(device_str)
            item = int(item_str)
        except ValueError:
            raise ValueError(f"Invalid variable address: {variable}")
        
        async with self._lock:
            context = self._next_context(advise=False)
            
            # Build write message
            message = {
                "method": "write",
                "context": context,
                "params": {
                    "kind": "indexedPoints",
                    "devices": [
                        {
                            "device": device,
                            "items": [item],
                            "values": [value]
                        }
                    ]
                }
            }
            
            _LOGGER.info("Writing %s = %s", variable, value)
            await self._send_json(message)
            
            # Wait for write confirmation
            try:
                updates = await self._await_updates({context}, timeout=5.0)
                result = updates.get(context, {})
                errors = result.get("errors", {})
                
                if variable in errors:
                    error_info = errors[variable]
                    _LOGGER.error(
                        "Write failed for %s: %s (%s)",
                        variable,
                        error_info.get("code"),
                        error_info.get("text")
                    )
                    return False
                
                _LOGGER.info("Write successful for %s", variable)
                return True
                
            except TimeoutError:
                _LOGGER.error("Write timeout for %s", variable)
                return False

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if not self._ws or self._ws.closed:
            raise ConnectionError("WebSocket is not connected")
        await self._ws.send_json(payload)

    async def _await_method(self, method: str) -> dict[str, Any]:
        return await self._await_message(method, field="method")

    async def _await_message(self, name: str, field: str = "messageName") -> dict[str, Any]:
        if not self._ws or self._ws.closed:
            raise ConnectionError("WebSocket is not connected")

        while True:
            data = await self._receive_json()
            if data is None:
                continue

            if data.get(field) == name:
                return data

    async def get_debug_info(self) -> dict[str, Any]:
        """Get diagnostic information from device debug endpoints"""
        import re
        from html.parser import HTMLParser
        
        class DebugParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.data = {}
                self.current_key = None
                self.in_td = False
                self.td_count = 0
                self.td_data = []
                
            def handle_starttag(self, tag, attrs):
                if tag == "td":
                    self.in_td = True
                    
            def handle_endtag(self, tag):
                if tag == "td":
                    self.in_td = False
                    self.td_count += 1
                elif tag == "tr":
                    if len(self.td_data) >= 2:
                        key = self.td_data[0].strip()
                        value = self.td_data[-1].strip()
                        if key and value:
                            self.data[key] = value
                    self.td_data = []
                    self.td_count = 0
                    
            def handle_data(self, data):
                if self.in_td:
                    self.td_data.append(data)
        
        result = {}
        
        # Get memory info
        try:
            url = f"http://{self._host}/debug/mem"
            async with self._session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    parser = DebugParser()
                    parser.feed(html)
                    
                    # Extract HEAP info
                    if "HEAP" in parser.data:
                        # Parse "8192" from data
                        for key, val in parser.data.items():
                            if "Avail:" in key:
                                match = re.search(r'(\d+)', val)
                                if match:
                                    result["heap_available"] = int(match.group(1))
                            elif "Used:" in key:
                                match = re.search(r'(\d+)', val)
                                if match:
                                    result["heap_used"] = int(match.group(1))
                            elif "Max:" in key:
                                match = re.search(r'(\d+)', val)
                                if match:
                                    result["heap_max"] = int(match.group(1))
                            elif "Err:" in key:
                                match = re.search(r'(\d+)', val)
                                if match:
                                    result["heap_errors"] = int(match.group(1))
        except Exception as e:
            _LOGGER.debug("Failed to get memory info: %s", e)
        
        # Get network info
        try:
            url = f"http://{self._host}/debug/exoline"
            async with self._session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    # Extract EXOline sessions count
                    match = re.search(r'EXOline TCP sessions[^<]*?(\d+)/(\d+)', html)
                    if match:
                        result["exoline_sessions_active"] = int(match.group(1))
                        result["exoline_sessions_max"] = int(match.group(2))
                    
                    # Extract external IP if connected
                    match = re.search(r'(\d+\.\d+\.\d+\.\d+)\s+\(reverse\)', html)
                    if match:
                        result["external_connection"] = match.group(1)
                    else:
                        result["external_connection"] = None
                        
                    # Extract Modbus sessions
                    match = re.search(r'Modbus TCP sessions[^<]*?(\d+)/(\d+)', html)
                    if match:
                        result["modbus_sessions_active"] = int(match.group(1))
                        result["modbus_sessions_max"] = int(match.group(2))
        except Exception as e:
            _LOGGER.debug("Failed to get network info: %s", e)
        
        # Get BACnet info
        try:
            url = f"http://{self._host}/debug/bacnet"
            async with self._session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    match = re.search(r'version[^<]*?(\d+\.\d+\.\d+\.\d+)', html)
                    if match:
                        result["bacnet_version"] = match.group(1)
                    match = re.search(r'device id[^<]*?(\d+)', html)
                    if match:
                        result["bacnet_device_id"] = int(match.group(1))
        except Exception as e:
            _LOGGER.debug("Failed to get BACnet info: %s", e)
        
        return result

    async def ensure_connected(self) -> None:
        if not self._ws or self._ws.closed:
            await self.connect()

    async def _receive_json(self, timeout: float | None = None) -> dict[str, Any] | None:
        if not self._ws or self._ws.closed:
            raise ConnectionError("WebSocket is not connected")

        try:
            msg = await asyncio.wait_for(self._ws.receive(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError("Timed out waiting for WebSocket message")

        if msg.type == WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                _LOGGER.debug("Skipping non-JSON message: %s", msg.data)
                return None

            if data.get("method") == "identity":
                params = data.get("params", {})
                self._identity = HomesideIdentity(
                    controller_name=params.get("controllerName"),
                    project_name=params.get("projectName"),
                    serial=params.get("serial"),
                )
            return data

        if msg.type == WSMsgType.BINARY:
            _LOGGER.debug("Ignoring binary message len=%s", len(msg.data))
            return None

        if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
            raise ConnectionError("WebSocket closed")

        return None

    async def _await_updates(
        self, contexts: set[int], timeout: float = 10.0
    ) -> dict[int, dict[str, dict[str, Any]]]:
        if not contexts:
            return {}

        results: dict[int, dict[str, Any]] = {}
        deadline = time.monotonic() + timeout
        pending = set(contexts)

        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for update messages")

            data = await self._receive_json(timeout=remaining)
            if not data:
                continue
            if data.get("method") != "update":
                continue

            context = data.get("context")
            if context in pending:
                results[context] = self._parse_update_details(data)
                pending.remove(context)

        return results

    def _build_read_message(self, context: int, device_items: dict[str, Any]) -> dict[str, Any]:
        return {
            "method": "read",
            "context": context,
            "params": {"kind": "indexedPoints", "devices": [device_items]},
        }

    def _build_read_objects(self, variables: list[str]) -> list[dict[str, Any]]:
        grouped: dict[int, list[int]] = {}
        for var in variables:
            if ":" not in var:
                _LOGGER.debug("Skipping variable without device:item format: %s", var)
                continue
            device_str, item_str = var.split(":", 1)
            try:
                device = int(device_str)
                item = int(item_str)
            except ValueError:
                _LOGGER.debug("Skipping invalid variable address: %s", var)
                continue

            grouped.setdefault(device, [])
            if item not in grouped[device]:
                grouped[device].append(item)

        objects: list[dict[str, Any]] = []
        for device, items in grouped.items():
            items_per_read = (
                self._items_per_read
                if device == 0
                else self._slave_items_per_read
            )
            remaining = list(items)
            while remaining:
                if len(remaining) < items_per_read + self._items_per_read_min_limit:
                    chunk = remaining
                    remaining = []
                else:
                    chunk = remaining[:items_per_read]
                    remaining = remaining[items_per_read:]
                objects.append({"device": device, "items": chunk})
        return objects

    def _parse_update(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._parse_update_details(data)["values"]

    def _parse_update_details(self, data: dict[str, Any]) -> dict[str, dict[str, Any]]:
        params = data.get("params", {})
        devices = params.get("devices", [])
        values: dict[str, Any] = {}
        errors: dict[str, dict[str, Any]] = {}
        for device_block in devices:
            device = device_block.get("device")
            items = device_block.get("items", [])
            device_values = device_block.get("values", [])
            device_errors = device_block.get("errors", [])
            for idx, item in enumerate(items):
                key = f"{device}:{item}"
                error = device_errors[idx] if idx < len(device_errors) else None
                value = device_values[idx] if idx < len(device_values) else None
                if error not in (None, 0):
                    _LOGGER.debug(
                        "Read error for %s: %s (%s)",
                        key,
                        error,
                        self._error_text(error),
                    )
                    errors[key] = {
                        "code": error,
                        "text": self._error_text(error),
                    }
                    values[key] = None
                else:
                    values[key] = value
        return {"values": values, "errors": errors}

    def _next_context(self, advise: bool = False) -> int:
        if advise:
            context = self._advise_context
            self._advise_context += 1
            if self._advise_context > 299999:
                self._advise_context = 200100
            return context
        context = self._peek_context
        self._peek_context += 1
        if self._peek_context > 99999:
            self._peek_context = 0
        return context

    async def _load_error_codes(self) -> None:
        if self._error_codes:
            return
        
        # Start with fallback error codes from const
        self._error_codes = ERROR_CODES.copy()
        
        # Try to load from device
        url = f"http://{self._host}/EXOsocketErrorCodes-en.json"
        try:
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Failed to load error codes: %s", resp.status)
                    return
                data = await resp.json()
        except Exception as exc:
            _LOGGER.debug("Failed to load error codes: %s", exc)
            return

        codes = data.get("codes", [])
        texts = data.get("texts", [])
        if isinstance(codes, list) and isinstance(texts, list):
            device_codes = {
                int(code): text
                for code, text in zip(codes, texts)
                if isinstance(code, int) and isinstance(text, str)
            }
            # Update with device codes (they take precedence)
            self._error_codes.update(device_codes)

    def _error_text(self, code: Any) -> str:
        try:
            return self._error_codes.get(int(code), f"Unknown error {code}")
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _rand_u32() -> int:
        return int.from_bytes(os.urandom(4), "big")

    @staticmethod
    def _swap_end(value: int) -> int:
        return int.from_bytes(value.to_bytes(4, "big"), "little")

    def _compute_auth_response(
        self, username: str, password: str, server_nonce: int
    ) -> tuple[int, int, int]:
        client_nonce2 = self._swap_end(self._rand_u32())
        payload = f"{username}\x00{password}\x00".encode("utf-8")
        digest = hashlib.sha256(payload).digest()
        words = [
            int.from_bytes(digest[i : i + 4], "big")
            for i in range(0, 32, 4)
        ]

        words[5] ^= self._swap_end(self._client_nonce1 or 0)
        words[6] ^= self._swap_end(server_nonce)
        words[7] ^= self._swap_end(client_nonce2)

        key_words = [
            words[0] ^ words[4],
            words[1] ^ words[5],
            words[2] ^ words[6],
            words[3] ^ words[7],
        ]
        key = b"".join(w.to_bytes(4, "big") for w in key_words)

        block_words = words[4:8]
        block = b"".join(w.to_bytes(4, "big") for w in block_words)
        cipher = AES.new(key, AES.MODE_ECB)
        enc = cipher.encrypt(block)
        word0 = int.from_bytes(enc[0:4], "big")
        word1 = int.from_bytes(enc[4:8], "big")
        confirmation = self._swap_end(word1)
        response = self._swap_end(word0)
        return client_nonce2, response, confirmation
