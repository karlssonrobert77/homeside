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
    from .diagnostics import get_debug_info as get_diagnostics_data
except ImportError:  # pragma: no cover - for script usage
    from const import WS_PATH, ERROR_CODES
    from diagnostics import get_debug_info as get_diagnostics_data

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
        keepalive_interval: int = 30,
        reconnect_delay: int = 5,
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
        self._error_codes: dict[int, str] = ERROR_CODES.copy()
        
        # Encryption state
        self._authenticated = False
        self._aes_key: bytes | None = None
        self._scbc_acc: bytearray | None = None  # Send CBC accumulator
        self._rcbc_acc: bytearray | None = None  # Receive CBC accumulator
        self._encryptor: AES = None
        self._decryptor: AES = None
        
        # Keep-alive management (configurable)
        self._keep_alive_task: asyncio.Task | None = None
        self._keep_alive_interval = keepalive_interval
        self._reconnect_delay = reconnect_delay
        self._last_activity = 0.0

    @property
    def identity(self) -> HomesideIdentity:
        return self._identity

    @property
    def ws_url(self) -> str:
        return f"ws://{self._host}{WS_PATH}"
    
    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected."""
        return self._ws is not None and not self._ws.closed

    async def connect(self) -> None:
        async with self._lock:
            if self._ws and not self._ws.closed:
                return
            
            # Initialize activity timestamp
            self._last_activity = time.monotonic()
            
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

            if self._username or self._password:
                await self.login(self._username, self._password)
            
            # Start keep-alive task
            self._start_keep_alive()

    async def close(self) -> None:
        # Stop keep-alive task first
        self._stop_keep_alive()
        
        async with self._lock:
            if self._ws and not self._ws.closed:
                await self._ws.close()
            self._ws = None
            self._authenticated = False

    async def ping(self) -> None:
        """Send ping to keep connection alive."""
        async with self._lock:
            if not self.is_connected:
                _LOGGER.debug("Skipping ping - not connected")
                return
            try:
                await self._send_json({"method": "ping"})
                await self._await_method("pingAck")
                self._last_activity = time.monotonic()
                _LOGGER.debug("Ping successful")
            except Exception as e:
                _LOGGER.warning("Ping failed: %s", e)
                # Connection is likely dead, close it so next ensure_connected will reconnect
                if self._ws and not self._ws.closed:
                    await self._ws.close()
                self._ws = None
                self._authenticated = False

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

        # Setup encryption - after successful authentication
        self._authenticated = True
        
        # Generate and send client IV (SCBCacc - Send CBC accumulator)
        self._scbc_acc = bytearray(os.urandom(16))
        await self._ws.send_bytes(self._scbc_acc)
        _LOGGER.debug("Sent client IV (%d bytes)", len(self._scbc_acc))
        
        # Setup AES encryptor/decryptor with the key from auth
        # Key was computed during _compute_auth_response
        from Crypto.Cipher import AES as AESCipher
        self._encryptor = AESCipher.new(self._aes_key, AESCipher.MODE_ECB)
        self._decryptor = AESCipher.new(self._aes_key, AESCipher.MODE_ECB)
        
        # Receive server's IV (RCBCacc - Receive CBC accumulator)
        msg = await self._ws.receive()
        if msg.type == WSMsgType.BINARY and len(msg.data) == 16:
            self._rcbc_acc = bytearray(msg.data)
            _LOGGER.debug("Received server IV (%d bytes)", len(self._rcbc_acc))
        else:
            raise ConnectionError(f"Expected 16-byte IV from server, got {msg.type}")

        # Now sessionLevel will come as encrypted binary message
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
    
    async def read_point(self, variable: str) -> Any:
        """Read a single point value.
        
        Args:
            variable: Point address in format "device:item" (e.g., "0:332")
            
        Returns:
            The value read from the point, or None if not found
        """
        values = await self.read_points([variable])
        return values.get(variable)

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

    async def write_point(self, variable: str, value: float | int | bool) -> bool:
        """Write a single value to a device point.
        
        Args:
            variable: Point address in format "device:item" (e.g., "0:332")
            value: Value to write (int, float, or bool)
            
        Returns:
            True if write was successful, False otherwise
            
        Raises:
            ValueError: If variable format is invalid
            PermissionError: If user session level doesn't allow write operations
            ConnectionError: If WebSocket is not connected
        """
        # Guest (1) and None (0) users can only read, never write
        if self._session_level is not None and self._session_level <= 1:
            raise PermissionError(
                f"Write operations not allowed for session level {self._session_level}. "
                "Only Operator (2) and above can write."
            )
        
        if ":" not in variable:
            raise ValueError(f"Invalid variable format: {variable}. Expected 'device:item'")
        
        device_str, item_str = variable.split(":", 1)
        try:
            device = int(device_str)
            item = int(item_str)
        except ValueError:
            raise ValueError(f"Invalid variable address: {variable}")
        
        # Convert boolean to int (0/1) for compatibility with Homeside/EXO systems
        if isinstance(value, bool):
            value = 1 if value else 0
        
        async with self._lock:
            context = self._next_context(advise=False)
            
            # Build write message - note: writes use different structure than reads!
            # Read uses: {"device": X, "items": [Y], "values": [Z]}
            # Write uses: {"device": X, "writes": [{"item": Y, "value": Z}]}
            message = {
                "method": "write",
                "context": context,
                "params": {
                    "kind": "indexedPoints",
                    "devices": [
                        {
                            "device": device,
                            "writes": [
                                {
                                    "item": item,
                                    "value": value
                                }
                            ]
                        }
                    ]
                }
            }
            
            _LOGGER.info("Writing %s = %s", variable, value)
            await self._send_json(message)
            
            # Wait for write confirmation (server responds with "writeResult" method)
            # Note: writeResult structure: {devices: [{device: X, writes: [{item: Y, error: null/code}]}]}
            try:
                write_result = await asyncio.wait_for(
                    self._await_method("writeResult"), 
                    timeout=2.0
                )
                
                # Check if this is our write result
                result_context = write_result.get("context")
                if result_context != context:
                    _LOGGER.warning(f"Received writeResult for different context: {result_context} (expected {context})")
                
                # Check for errors in the response
                params = write_result.get("params", {})
                if params.get("kind") == "indexedPoints":
                    devices = params.get("devices", [])
                    for dev in devices:
                        if dev.get("device") == device:
                            # writeResult uses "writes" array with item and error fields
                            writes = dev.get("writes", [])
                            for write_entry in writes:
                                if write_entry.get("item") == item:
                                    error = write_entry.get("error")
                                    if error is not None:
                                        _LOGGER.error(
                                            "Write failed for %s: error code %s",
                                            variable,
                                            error
                                        )
                                        return False
                                    else:
                                        _LOGGER.info("Write successful for %s", variable)
                                        # Wait for device to update before reading back
                                        await asyncio.sleep(0.3)
                                        # Read back to confirm and update cached state
                                        confirmed_value = await self.read_point(variable)
                                        _LOGGER.debug("Confirmed value for %s: %s", variable, confirmed_value)
                                        return True
                
                # If we didn't find our write in the response
                _LOGGER.warning("Write result did not contain confirmation for %s", variable)
                # Still wait and read back
                await asyncio.sleep(0.3)
                await self.read_point(variable)
                return True
                
            except (TimeoutError, asyncio.TimeoutError):
                # Timeout might mean the write succeeded but no confirmation was sent
                # or the response couldn't be decrypted. Assume success.
                _LOGGER.debug("No writeResult received within timeout for %s (assuming success)", variable)
                # Wait for device to update and read back
                await asyncio.sleep(0.3)
                await self.read_point(variable)
                return True

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if not self._ws or self._ws.closed:
            raise ConnectionError("WebSocket is not connected")
        
        if self._authenticated:
            # Send encrypted
            json_str = json.dumps(payload)
            encrypted = self._encrypt_message(json_str)
            await self._ws.send_bytes(encrypted)
        else:
            # Send plain JSON
            await self._ws.send_json(payload)
        
        # Track activity for keep-alive
        self._last_activity = time.monotonic()

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
        """Get diagnostic information from device debug endpoints.
        
        Wrapper method that calls the diagnostics module.
        """
        return await get_diagnostics_data(self._session, self._host)

    async def ensure_connected(self) -> None:
        """Ensure websocket is connected. Retry a few times on transient failures."""
        if self._ws and not self._ws.closed:
            return

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                _LOGGER.info("Reconnecting to Homeside (attempt %d/3)...", attempt + 1)
                await self.connect()
                _LOGGER.info("Successfully reconnected to Homeside")
                return
            except (ConnectionError, TimeoutError, asyncio.TimeoutError) as exc:
                last_exc = exc
                _LOGGER.warning("Connection attempt %d failed: %s", attempt + 1, exc)
                if attempt < 2:
                    # Use configured reconnect delay with exponential backoff
                    await asyncio.sleep(self._reconnect_delay * (2 ** attempt))
            except Exception as exc:
                last_exc = exc
                _LOGGER.error("Unexpected error during connection attempt %d: %s", attempt + 1, exc, exc_info=True)
                if attempt < 2:
                    await asyncio.sleep(self._reconnect_delay)
        
        # If we reached here, all retries failed
        if last_exc:
            _LOGGER.error("Failed to connect to Homeside after 3 attempts")
            raise last_exc
    
    def _start_keep_alive(self) -> None:
        """Start the keep-alive background task."""
        if self._keep_alive_task is None or self._keep_alive_task.done():
            self._keep_alive_task = asyncio.create_task(self._keep_alive_loop())
            _LOGGER.debug("Keep-alive task started")
    
    def _stop_keep_alive(self) -> None:
        """Stop the keep-alive background task."""
        if self._keep_alive_task and not self._keep_alive_task.done():
            self._keep_alive_task.cancel()
            _LOGGER.debug("Keep-alive task stopped")
        self._keep_alive_task = None
    
    async def _keep_alive_loop(self) -> None:
        """Background task to keep WebSocket connection alive."""
        _LOGGER.info("Keep-alive loop started (interval: %ds)", self._keep_alive_interval)
        try:
            while True:
                await asyncio.sleep(self._keep_alive_interval)
                
                if not self.is_connected:
                    _LOGGER.debug("Keep-alive: Connection lost, will reconnect on next operation")
                    continue
                
                # Check if we've had recent activity
                time_since_activity = time.monotonic() - self._last_activity
                if time_since_activity < self._keep_alive_interval:
                    _LOGGER.debug("Keep-alive: Skipping ping (recent activity: %.1fs ago)", time_since_activity)
                    continue
                
                # Send ping
                try:
                    await self.ping()
                except Exception as e:
                    _LOGGER.warning("Keep-alive ping failed: %s", e)
        except asyncio.CancelledError:
            _LOGGER.debug("Keep-alive loop cancelled")
        except Exception as e:
            _LOGGER.error("Keep-alive loop error: %s", e, exc_info=True)

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
            # Track activity for keep-alive
            self._last_activity = time.monotonic()
            return data

        if msg.type == WSMsgType.BINARY:
            # After authentication, binary messages are encrypted
            if self._authenticated and self._rcbc_acc is not None:
                try:
                    _LOGGER.debug("Received binary message, length: %d bytes", len(msg.data))
                    decrypted_text = self._decrypt_message(msg.data)
                    _LOGGER.debug("Decrypted text: %s", decrypted_text[:200] if len(decrypted_text) > 200 else decrypted_text)
                    data = json.loads(decrypted_text)
                    _LOGGER.debug("Decrypted message: %s", data.get("method", "unknown"))
                    # Track activity for keep-alive
                    self._last_activity = time.monotonic()
                    return data
                except Exception as e:
                    _LOGGER.error("Failed to decrypt message: %s", e)
                    _LOGGER.debug("Raw binary data (first 100 bytes): %s", msg.data[:100].hex())
                    return None
            else:
                _LOGGER.debug("Ignoring binary message len=%s (not authenticated)", len(msg.data))
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
        # NOTE: Web UI converts username to lowercase before hashing
        # See app.main.min.js.raw.js: i.toLowerCase()+String.fromCharCode(0)+r+String.fromCharCode(0)
        payload = f"{username.lower()}\x00{password}\x00".encode("utf-8")
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
        
        # Store AES key for later encryption/decryption
        self._aes_key = key

        block_words = words[4:8]
        block = b"".join(w.to_bytes(4, "big") for w in block_words)
        cipher = AES.new(key, AES.MODE_ECB)
        enc = cipher.encrypt(block)
        word0 = int.from_bytes(enc[0:4], "big")
        word1 = int.from_bytes(enc[4:8], "big")
        confirmation = self._swap_end(word1)
        response = self._swap_end(word0)
        return client_nonce2, response, confirmation

    def _encrypt_message(self, text: str) -> bytes:
        """Encrypt a text message using AES with custom CBC mode.
        
        Based on Web UI implementation in app.main.min.js.raw.js: Crypto_EncodeMsg
        """
        # Encode text to bytes
        text_bytes = text.encode('utf-8')
        
        # Calculate padded size (multiple of 16)
        padded_size = 16 * ((len(text_bytes) + 16) // 16)
        
        # Create output buffer
        output = bytearray(padded_size)
        
        # Generate random IV for this message
        import secrets
        msg_iv = secrets.token_bytes(16)
        
        # Place IV at the end
        output[-16:] = msg_iv
        
        # Copy text data
        output[:len(text_bytes)] = text_bytes
        
        # Set length indicator in last byte (length % 16)
        output[-1] = (output[-1] & 0xF0) | (len(text_bytes) % 16)
        
        # Encrypt each 16-byte block with CBC chaining
        for i in range(0, len(output), 16):
            # XOR block with SCBCacc (CBC mode)
            block = bytearray(16)
            for j in range(16):
                block[j] = self._scbc_acc[j] ^ output[i + j]
            
            # Encrypt block
            encrypted = self._encryptor.encrypt(bytes(block))
            
            # XOR encrypted result with original block and store
            for j in range(16):
                self._scbc_acc[j] = encrypted[j] ^ output[i + j]
                output[i + j] = encrypted[j]
        
        return bytes(output)

    def _decrypt_message(self, data: bytes) -> str:
        """Decrypt a binary message using AES with custom CBC mode.
        
        Based on Web UI implementation in app.main.min.js.raw.js: Crypto_DecodeMsg
        """
        if len(data) % 16 != 0:
            raise ValueError(f"Invalid encrypted message length: {len(data)}")
        
        output = bytearray(len(data))
        
        # Decrypt each 16-byte block
        for i in range(0, len(data), 16):
            # Get encrypted block
            enc_block = data[i:i+16]
            
            # Decrypt block
            decrypted = self._decryptor.decrypt(enc_block)
            
            # XOR with RCBCacc and store
            for j in range(16):
                output[i + j] = decrypted[j] ^ self._rcbc_acc[j]
            
            # Update RCBCacc for next block (CBC chaining)
            for j in range(16):
                self._rcbc_acc[j] = enc_block[j] ^ output[i + j]
        
        # Extract actual message length from last byte
        msg_length = output[-1] & 0x0F
        if msg_length == 0:
            msg_length = len(output) - 16
        else:
            msg_length = len(output) - 16 + msg_length
        
        # Return decoded text
        return output[:msg_length].decode('utf-8')
