"""
Hill Climb Racing 2 - Protocol Buffers Schema Loader
Extracts serialized FileDescriptorProtos from libcocos2dcpp.so and builds Python message classes.
"""

import os
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SO_PATH = os.environ.get("HCR2_SO_PATH", "")
FALLBACK_SO_PATHS = (
    os.path.join(BASE_DIR, "libcocos2dcpp.so"),
    r"C:\Users\ASUS\Downloads\libcocos2dcpp.so",
)

# Descriptors: (offset, length, name)
DESCRIPTOR_TABLE = [
    (0x127FB14, 79, "Achievement.proto"),
    (0x127FBC8, 129, "DriverCustomization.proto"),
    (0x12AAE1C, 246, "Unlock.proto"),
    (0x127FD44, 0x2452, "hcr2_messages.proto"),
]

_pool = None
_classes = {}

def get_proto_pool(so_path: str = DEFAULT_SO_PATH) -> descriptor_pool.DescriptorPool:
    global _pool
    if _pool is not None:
        return _pool

    candidates = (so_path,) if so_path else FALLBACK_SO_PATHS
    so_path = next((path for path in candidates if os.path.isfile(path)), None)
    if so_path is None:
        searched = ", ".join(candidates)
        raise FileNotFoundError(
            f"libcocos2dcpp.so not found; set HCR2_SO_PATH (searched: {searched})"
        )

    with open(so_path, "rb") as f:
        data = f.read()

    pool = descriptor_pool.DescriptorPool()
    for pos, length, name in DESCRIPTOR_TABLE:
        fd = descriptor_pb2.FileDescriptorProto()
        raw_slice = data[pos : pos + length]
        fd.ParseFromString(raw_slice)
        pool.Add(fd)

    _pool = pool
    return _pool

def get_message_class(name: str, so_path: str = DEFAULT_SO_PATH):
    global _classes
    if name in _classes:
        return _classes[name]

    pool = get_proto_pool(so_path)
    msg_desc = pool.FindMessageTypeByName(name)
    if not msg_desc:
        raise KeyError(f"Message type '{name}' not found in proto pool")

    cls = message_factory.GetMessageClass(msg_desc)
    _classes[name] = cls
    return cls

# Convenience accessors
def FSMessage():
    return get_message_class("FSMessage")()

def GameStatus():
    return get_message_class("GameStatus")()

def GameParameters():
    return get_message_class("GameParameters")()

def Cup():
    return get_message_class("Cup")()

def WCRace():
    return get_message_class("WCRace")()

def JsonObject():
    return get_message_class("JsonObject")()
