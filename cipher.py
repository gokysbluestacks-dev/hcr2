"""
Hill Climb Racing 2 - Stream Cipher and Packet Framing
Implements the 263-byte (0x107) rolling XOR stream cipher and 4-byte big-endian framing.
"""

import struct
from typing import Optional

# Static 263-byte XOR key extracted from libcocos2dcpp.so @ 0x127EA98
STATIC_KEY_TABLE = bytes([
    91, 66, 157, 177, 180, 64, 219, 131, 133, 53, 121, 55, 246, 179, 248, 156,
    71, 181, 225, 150, 116, 85, 146, 67, 173, 73, 144, 187, 124, 122, 199, 209,
    34, 56, 237, 180, 175, 18, 168, 49, 224, 37, 120, 217, 249, 30, 242, 157,
    8, 180, 240, 88, 66, 138, 250, 2, 225, 128, 161, 12, 18, 105, 221, 145,
    25, 208, 31, 24, 31, 147, 110, 36, 160, 118, 7, 48, 181, 211, 239, 201,
    166, 13, 217, 235, 88, 252, 57, 115, 128, 36, 54, 212, 204, 195, 108, 50,
    102, 110, 46, 171, 224, 114, 246, 18, 152, 151, 120, 102, 106, 73, 181, 5,
    245, 1, 179, 248, 172, 167, 3, 60, 64, 165, 239, 151, 142, 48, 86, 66,
    65, 125, 55, 30, 44, 53, 212, 182, 209, 10, 69, 146, 94, 227, 112, 217,
    152, 177, 174, 128, 209, 7, 90, 132, 133, 25, 222, 117, 168, 206, 206, 20,
    94, 166, 126, 106, 21, 201, 3, 26, 12, 14, 157, 146, 250, 137, 100, 85,
    242, 92, 187, 10, 68, 42, 120, 130, 177, 255, 218, 27, 106, 30, 22, 90,
    116, 119, 172, 107, 250, 4, 56, 217, 247, 4, 148, 45, 180, 14, 47, 131,
    175, 251, 169, 231, 111, 59, 72, 236, 176, 113, 76, 133, 6, 165, 242, 242,
    187, 95, 86, 152, 143, 252, 84, 79, 189, 164, 10, 113, 175, 226, 141, 191,
    40, 197, 153, 226, 126, 168, 79, 93, 128, 18, 18, 155, 98, 227, 27, 29,
    143, 163, 233, 233, 196, 244, 50
])

KEY_LEN = len(STATIC_KEY_TABLE) # 263

class HCR2StreamCipher:
    def __init__(self, key: bytes = STATIC_KEY_TABLE):
        self.key = key
        self.counter = 0

    def transform(self, data: bytes) -> bytes:
        k = self.key
        k_len = KEY_LEN
        c = self.counter
        out = bytearray(len(data))
        for i, b in enumerate(data):
            out[i] = b ^ k[(c + i) % k_len]
        self.counter += len(data)
        return bytes(out)

class HCR2Framer:
    """Handles serialization, framing, and bidirectional stream decryption."""
    def __init__(self):
        self.rx_cipher = HCR2StreamCipher()
        self.tx_cipher = HCR2StreamCipher()

    def pack_message(self, protobuf_msg) -> bytes:
        """Serializes and encrypts an outgoing FSMessage."""
        raw_payload = protobuf_msg.SerializeToString()
        header = struct.pack(">I", len(raw_payload))
        packet = header + raw_payload
        return self.tx_cipher.transform(packet)

    def decrypt_bytes(self, chunk: bytes) -> bytes:
        """Decrypts a raw byte chunk from the incoming socket stream."""
        return self.rx_cipher.transform(chunk)
