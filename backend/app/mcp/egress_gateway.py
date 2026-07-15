import argparse
import asyncio
import base64
import secrets
from contextlib import suppress

from app.core.config import settings
from app.mcp.egress import MCPEgressDeniedError, resolve_egress_target

MAX_HEADER_BYTES = 16_384


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    try:
        request = await asyncio.wait_for(
            reader.readuntil(b"\r\n\r\n"),
            timeout=max(1.0, settings.mcp_egress_connect_timeout_seconds),
        )
        if len(request) > MAX_HEADER_BYTES:
            raise MCPEgressDeniedError("Proxy request headers are too large")
        lines = request.decode("latin-1").split("\r\n")
        method, authority, _version = lines[0].split(" ", 2)
        if method.upper() != "CONNECT":
            raise MCPEgressDeniedError("Only HTTPS CONNECT is supported")
        headers = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
        if not valid_proxy_token(headers.get("proxy-authorization")):
            await send_error(writer, 407, "Proxy Authentication Required")
            return
        host, port = parse_authority(authority)
        target = resolve_egress_target(host, port)
        upstream_reader = None
        last_error: Exception | None = None
        for address in target.addresses:
            try:
                upstream_reader, upstream_writer = await asyncio.wait_for(
                    asyncio.open_connection(address, target.port),
                    timeout=max(1.0, settings.mcp_egress_connect_timeout_seconds),
                )
                break
            except (OSError, asyncio.TimeoutError) as exc:
                last_error = exc
        if upstream_reader is None or upstream_writer is None:
            raise MCPEgressDeniedError(f"MCP egress connection failed: {last_error}")
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await tunnel(reader, writer, upstream_reader, upstream_writer)
    except (
        asyncio.IncompleteReadError,
        asyncio.LimitOverrunError,
        ValueError,
        MCPEgressDeniedError,
    ) as exc:
        await send_error(writer, 403, str(exc)[:200] or "Forbidden")
    except (asyncio.TimeoutError, OSError):
        await send_error(writer, 504, "Gateway Timeout")
    finally:
        if upstream_writer is not None:
            upstream_writer.close()
            with suppress(Exception):
                await upstream_writer.wait_closed()
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()


async def tunnel(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
) -> None:
    async def copy(source: asyncio.StreamReader, destination: asyncio.StreamWriter) -> None:
        while data := await source.read(65_536):
            destination.write(data)
            await destination.drain()

    tasks = {
        asyncio.create_task(copy(client_reader, upstream_writer)),
        asyncio.create_task(copy(upstream_reader, client_writer)),
    }
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in [*done, *pending]:
        with suppress(asyncio.CancelledError, ConnectionError, OSError):
            await task


def valid_proxy_token(value: str | None) -> bool:
    expected = (settings.mcp_egress_proxy_token or "").strip()
    if not expected or not value:
        return False
    scheme, separator, encoded = value.partition(" ")
    if not separator or scheme.lower() != "basic":
        return False
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception:  # noqa: BLE001 - malformed proxy credentials are denied.
        return False
    username, separator, token = decoded.partition(":")
    return bool(separator and username == "codemate" and secrets.compare_digest(token, expected))


def parse_authority(authority: str) -> tuple[str, int]:
    if authority.startswith("["):
        host, separator, port = authority[1:].partition("]:")
    else:
        host, separator, port = authority.rpartition(":")
    if not separator:
        raise MCPEgressDeniedError("CONNECT authority must include a port")
    return host, int(port)


async def send_error(writer: asyncio.StreamWriter, status: int, detail: str) -> None:
    if writer.is_closing():
        return
    body = detail.encode("utf-8", errors="replace")[:500]
    writer.write(
        f"HTTP/1.1 {status} Error\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
        + body
    )
    with suppress(ConnectionError, OSError):
        await writer.drain()


async def serve(host: str, port: int) -> None:
    if len((settings.mcp_egress_proxy_token or "").strip()) < 32:
        raise RuntimeError("MCP egress proxy token must contain at least 32 characters")
    if not settings.mcp_registry_host_allowlist:
        raise RuntimeError("MCP egress host allowlist must not be empty")
    if settings.mcp_egress_port_allowlist != {443}:
        raise RuntimeError("MCP egress gateway only permits TLS port 443")
    server = await asyncio.start_server(handle_client, host, port)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="CodeMate policy-enforcing MCP egress gateway")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    asyncio.run(serve(args.host, args.port))


if __name__ == "__main__":
    main()
