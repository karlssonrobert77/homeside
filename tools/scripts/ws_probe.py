import argparse
import hashlib
import json
import os
import ssl
import sys
import time
from typing import Optional

import websocket
from Crypto.Cipher import AES


def build_ws_url(host: str, path: str, use_tls: bool) -> str:
    scheme = "wss" if use_tls else "ws"
    if not path.startswith("/"):
        path = "/" + path
    return f"{scheme}://{host}{path}"


def connect_and_read(
    url: str,
    protocol: Optional[str],
    timeout: float,
    max_messages: int,
    read_duration: float,
    log_binary: bool,
    send_probes: bool,
    send_exo_sequence: bool,
    send_proto_sequence: bool,
    auth_flow: bool,
    exo_session_id: int,
    exo_user: str,
    exo_pass: str,
    send_peek: bool,
    peek_fullpath: str,
    peek_vars: list[str],
) -> int:
    ws = None
    try:
        sslopt = {"cert_reqs": ssl.CERT_NONE} if url.startswith("wss://") else None
        ws = websocket.WebSocket()
        ws.connect(url, timeout=timeout, subprotocols=[protocol] if protocol else None, sslopt=sslopt)
        print(f"Connected: {url} protocol={protocol or 'none'}")

        if send_proto_sequence:
            version_offer = {
                "method": "versionOffer",
                "params": {"version": 1, "featureLevel": 0, "capabilities": 0},
            }
            identity = {
                "method": "identity",
                "params": {
                    "implementation": "ControllerWebFramework",
                    "implementationVersion": "2.0-0-00",
                    "sessionID": exo_session_id,
                },
            }
            ping = {"method": "ping"}
            for payload in (version_offer, identity, ping):
                try:
                    ws.send(str(payload).replace("'", '"'))
                    print(f"Sent JSON: {payload}")
                    time.sleep(0.2)
                except Exception as exc:
                    print(f"Send failed: {exc}")

        if send_exo_sequence:
            connect_msg = {
                "messageName": "ConnectWebSocket",
                "scope": "EXOsocketEvent",
                "url": url,
                "EXOsocketSessionID": exo_session_id,
            }
            login_msg = {
                "messageName": "Login",
                "scope": "EXOsocketEvent",
                "user": exo_user,
                "pass": exo_pass,
            }
            for payload in (connect_msg, login_msg):
                try:
                    ws.send(str(payload).replace("'", '"'))
                    print(f"Sent JSON: {payload}")
                    time.sleep(0.2)
                except Exception as exc:
                    print(f"Send failed: {exc}")

        def build_read_objects(vars_list: list[str]) -> list[dict]:
            grouped: dict[int, list[int]] = {}
            for var in vars_list:
                if ":" not in var:
                    print(f"Skipping variable without device:item format: {var}")
                    continue
                device_str, item_str = var.split(":", 1)
                try:
                    device = int(device_str)
                    item = int(item_str)
                except ValueError:
                    print(f"Skipping invalid variable address: {var}")
                    continue
                grouped.setdefault(device, [])
                if item not in grouped[device]:
                    grouped[device].append(item)

            objects: list[dict] = []
            for device, items in grouped.items():
                objects.append({"device": device, "items": items})
            return objects

        if send_peek:
            objects = build_read_objects(peek_vars)
            context = 1
            for obj in objects:
                read_msg = {
                    "method": "read",
                    "context": context,
                    "params": {"kind": "indexedPoints", "devices": [obj]},
                }
                try:
                    ws.send(str(read_msg).replace("'", '"'))
                    print(f"Sent JSON: {read_msg}")
                except Exception as exc:
                    print(f"Send failed: {exc}")
                context += 1

        if send_probes:
            probes = [
                "",
                "ping",
                "{}",
                '{"type":"ping"}',
                '{"cmd":"hello"}',
            ]
            for payload in probes:
                try:
                    ws.send(payload)
                    print(f"Sent: {payload!r}")
                    time.sleep(0.2)
                except Exception as exc:
                    print(f"Send failed: {exc}")

        end_time = time.time() + read_duration
        i = 0
        client_nonce1: int | None = None
        client_nonce2: int | None = None
        challenge_confirmation: int | None = None

        def swap_end(u32: int) -> int:
            return int.from_bytes(u32.to_bytes(4, "big"), "little")

        def compute_auth_response(server_nonce: int) -> tuple[int, int, int]:
            nonlocal client_nonce2, challenge_confirmation

            rnd = int.from_bytes(os.urandom(4), "big")
            client_nonce2 = swap_end(rnd)
            payload = f"{exo_user.lower()}\x00{exo_pass}\x00".encode("utf-8")
            digest = hashlib.sha256(payload).digest()
            words = [
                int.from_bytes(digest[i : i + 4], "big")
                for i in range(0, 32, 4)
            ]

            words[5] ^= swap_end(client_nonce1 or 0)
            words[6] ^= swap_end(server_nonce)
            words[7] ^= swap_end(client_nonce2)

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
            challenge_confirmation = swap_end(word1)
            return client_nonce2, swap_end(word0), challenge_confirmation

        auth_pending = auth_flow

        while i < max_messages and time.time() < end_time:
            try:
                msg = ws.recv()
                if isinstance(msg, (bytes, bytearray)):
                    if log_binary:
                        preview = msg[:64].hex()
                        print(f"[{i+1}] <binary> len={len(msg)} hex={preview}")
                    else:
                        print(f"[{i+1}] <binary> len={len(msg)}")
                else:
                    print(f"[{i+1}] {msg}")
                    if auth_flow:
                        try:
                            data = json.loads(msg) if msg.startswith("{") else None
                        except Exception:
                            data = None
                        if isinstance(data, dict) and data.get("method") == "versionAck" and auth_pending:
                            rnd = int.from_bytes(os.urandom(4), "big")
                            client_nonce1 = swap_end(rnd)
                            get_challenge = {
                                "method": "getChallenge",
                                "params": {"clientNonce1": client_nonce1},
                            }
                            ws.send(str(get_challenge).replace("'", '"'))
                            print(f"Sent JSON: {get_challenge}")
                            auth_pending = False
                        if isinstance(data, dict) and data.get("method") == "authChallenge":
                            server_nonce = data.get("params", {}).get("serverNonce")
                            if server_nonce is not None:
                                client_nonce2, response, confirmation = compute_auth_response(server_nonce)
                                authenticate = {
                                    "method": "authenticate",
                                    "params": {
                                        "user": exo_user,
                                        "clientNonce2": client_nonce2,
                                        "challengeResponse": response,
                                    },
                                }
                                ws.send(str(authenticate).replace("'", '"'))
                                print(f"Sent JSON: {authenticate}")
                        if isinstance(data, dict) and data.get("method") == "authenticateReply":
                            confirmation = data.get("params", {}).get("confirmation")
                            print(f"AuthenticateReply confirmation={confirmation} expected={challenge_confirmation}")
                i += 1
            except websocket._exceptions.WebSocketTimeoutException:
                print("Timeout waiting for message")
                break
        return 0
    except Exception as exc:
        print(f"Connection failed: {exc}")
        return 1
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe ControllerWeb websocket endpoints")
    parser.add_argument("--host", default="192.168.217.163", help="Target host or host:port")
    parser.add_argument("--path", default="/_EXOsocket/", help="Websocket path")
    parser.add_argument("--protocol", default="EXOsocket", help="Websocket subprotocol")
    parser.add_argument("--timeout", type=float, default=5.0, help="Connect/recv timeout in seconds")
    parser.add_argument("--max-messages", type=int, default=10, help="Max messages to read")
    parser.add_argument("--read-duration", type=float, default=15.0, help="Seconds to wait for messages")
    parser.add_argument("--log-binary", action="store_true", help="Dump binary message hex preview")
    parser.add_argument("--no-send", action="store_true", help="Do not send probe messages")
    parser.add_argument("--exo-seq", action="store_true", help="Send EXOsocket ConnectWebSocket + Login JSON")
    parser.add_argument("--proto-seq", action="store_true", help="Send versionOffer + identity + ping JSON")
    parser.add_argument("--auth-flow", action="store_true", help="Run getChallenge/authenticate flow")
    parser.add_argument("--exo-session-id", type=int, default=12345, help="EXOsocket session id")
    parser.add_argument("--exo-user", default="", help="EXOsocket login user")
    parser.add_argument("--exo-pass", default="", help="EXOsocket login password")
    parser.add_argument("--peek", action="store_true", help="Send a Peek request")
    parser.add_argument("--peek-fullpath", default="Homeside_2160", help="Peek fullPath")
    parser.add_argument(
        "--peek-vars",
        default="AI_GT_UTE_LARM_Status",
        help="Comma-separated variable names",
    )
    parser.add_argument("--tls", action="store_true", help="Use wss://")
    args = parser.parse_args()

    url = build_ws_url(args.host, args.path, args.tls)
    return connect_and_read(
        url,
        args.protocol,
        args.timeout,
        args.max_messages,
        args.read_duration,
        args.log_binary,
        send_probes=not args.no_send,
        send_exo_sequence=args.exo_seq,
        send_proto_sequence=args.proto_seq,
        auth_flow=args.auth_flow,
        exo_session_id=args.exo_session_id,
        exo_user=args.exo_user,
        exo_pass=args.exo_pass,
        send_peek=args.peek,
        peek_fullpath=args.peek_fullpath,
        peek_vars=[v.strip() for v in args.peek_vars.split(",") if v.strip()],
    )


if __name__ == "__main__":
    raise SystemExit(main())
