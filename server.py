"""
Hill Climb Racing 2 - Private TCP Server
Listens on the configured TCP port (default: 22994).
"""

import asyncio
import struct
import random
import logging
import os
from cipher import HCR2Framer
from handlers import MessageDispatcher
from hcr2_proto import get_message_class

FSMessageCls = get_message_class("FSMessage")

DEFAULT_PORTS = [22994]
LOGGER = logging.getLogger("hcr2.server")
MAX_PACKET_SIZE = 10 * 1024 * 1024


class HCR2ClientSession:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, client_id: int):
        self.reader = reader
        self.writer = writer
        self.client_id = client_id
        self.session_id = random.SystemRandom().getrandbits(63) or 1
        self.framer = HCR2Framer()
        self.dispatcher = MessageDispatcher(self.session_id)
        self.peer = writer.get_extra_info("peername")
        self.sockname = writer.get_extra_info("sockname")
        self.local_port = self.sockname[1] if self.sockname else 0
        self.read_timeout = float(os.environ.get("HCR2_READ_TIMEOUT", "120"))

    async def run(self):
        LOGGER.info(
            "Client connected to port %s from %s (ID: %s, Session: 0x%X)",
            self.local_port, self.peer, self.client_id, self.session_id
        )
        decrypted_buffer = bytearray()
        first_chunk = True

        try:
            while True:
                chunk = await asyncio.wait_for(self.reader.read(4096), timeout=self.read_timeout)
                if not chunk:
                    LOGGER.info("Client %s disconnected (EOF).", self.client_id)
                    break

                # Check if client sent plaintext HTTP request (e.g. analytics or ad server)
                if first_chunk and (
                    chunk.startswith(b"POST ")
                    or chunk.startswith(b"GET ")
                    or chunk.startswith(b"HEAD ")
                ):
                    LOGGER.info("Plaintext HTTP request detected on port %s", self.local_port)
                    http_resp = (
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Type: text/plain\r\n"
                        b"Content-Length: 2\r\n"
                        b"Connection: close\r\n\r\nOK"
                    )
                    self.writer.write(http_resp)
                    await self.writer.drain()
                    LOGGER.info("Replied 200 OK to %s", self.peer)
                    return

                first_chunk = False
                LOGGER.debug("Received %s bytes on port %s", len(chunk), self.local_port)

                # Decrypt raw bytes through the incoming stream cipher
                decrypted_bytes = self.framer.decrypt_bytes(chunk)
                decrypted_buffer.extend(decrypted_bytes)

                # Process all complete framed packets
                while len(decrypted_buffer) >= 4:
                    payload_len = struct.unpack(">I", decrypted_buffer[:4])[0]

                    if payload_len > MAX_PACKET_SIZE:
                        LOGGER.warning("Invalid packet size %s from %s; closing socket", payload_len, self.peer)
                        return

                    if len(decrypted_buffer) < 4 + payload_len:
                        if len(decrypted_buffer) > MAX_PACKET_SIZE + 4:
                            LOGGER.warning("Incomplete oversized frame from %s", self.peer)
                            return
                        break

                    payload = bytes(decrypted_buffer[4:4 + payload_len])
                    del decrypted_buffer[:4 + payload_len]

                    # Parse Protobuf
                    try:
                        in_msg = FSMessageCls()
                        in_msg.ParseFromString(payload)
                        set_fields = [
                            (f[0].name, f[1])
                            for f in in_msg.ListFields()
                        ]
                        LOGGER.debug("Decoded FSMessage (%s bytes): %s", len(payload), set_fields)
                    except Exception as e:
                        LOGGER.warning("Failed to parse FSMessage protobuf (%s bytes): %s", len(payload), e)
                        continue

                    # Dispatch and generate responses
                    responses = self.dispatcher.handle(in_msg)
                    for resp in responses:
                        packet = self.framer.pack_message(resp)
                        self.writer.write(packet)
                        await self.writer.drain()
                        LOGGER.debug(
                            "Sent response: MessageType=%s, MessageNumber=%s, Session=0x%X, len=%s",
                            resp.MessageType, resp.MessageNumber, resp.Session, len(packet)
                        )

        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            LOGGER.info("Client %s read timed out", self.client_id)
        except ConnectionResetError:
            LOGGER.info("Client %s connection reset", self.client_id)
        except Exception:
            LOGGER.exception("Error handling client %s", self.client_id)
        finally:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            LOGGER.info("Session closed for client %s", self.client_id)


class HCR2PrivateServer:
    def __init__(self, host: str = "0.0.0.0", ports=None):
        self.host = host
        if isinstance(ports, int):
            self.ports = [ports]
        elif isinstance(ports, (list, tuple)):
            self.ports = list(ports)
        else:
            self.ports = DEFAULT_PORTS

        self.client_counter = 0
        self.servers = []
        self.connection_semaphore = asyncio.Semaphore(256)

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ):
        async with self.connection_semaphore:
            self.client_counter += 1
            session = HCR2ClientSession(reader, writer, self.client_counter)
            await session.run()

    async def start(self):
        listening_info = []

        for port in self.ports:
            if not 1 <= port <= 65535:
                raise ValueError(f"Invalid TCP port: {port}")
            try:
                srv = await asyncio.start_server(
                    self.handle_connection,
                    self.host,
                    port
                )
                self.servers.append(srv)

                for s in srv.sockets:
                    listening_info.append(str(s.getsockname()))

            except Exception as e:
                LOGGER.exception("Failed to bind port %s", port)

        if not self.servers:
            raise RuntimeError("No server sockets could be bound")

        LOGGER.info("Listening on %s", ", ".join(listening_info))
        LOGGER.info("Protocol: FSMessage protobuf with legacy XOR framing")
        await asyncio.gather(*(srv.serve_forever() for srv in self.servers))


if __name__ == "__main__":
    server = HCR2PrivateServer("0.0.0.0", DEFAULT_PORTS)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\nServer shutdown gracefully.")