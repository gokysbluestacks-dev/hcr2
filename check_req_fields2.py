from google.protobuf import descriptor_pb2

path = r"C:\Users\ASUS\Downloads\libcocos2dcpp.so"
with open(path, "rb") as f:
    data = f.read()

pos = 0x127FD44
fd = descriptor_pb2.FileDescriptorProto()
fd.ParseFromString(data[pos : pos + 0x2452])

for m in fd.message_type:
    req = [f.name for f in m.field if f.label == descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED]
    if req:
        print(f"Message {m.name} has required fields: {req}")
