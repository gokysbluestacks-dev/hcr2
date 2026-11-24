from hcr2_proto import get_message_class

GameStatusCls = get_message_class("GameStatus")
for f in GameStatusCls.DESCRIPTOR.fields:
    # FieldDescriptor.LABEL_REQUIRED = 2
    if f.label == 2:
        print(f"Required field in GameStatus: {f.name} (type {f.type})")
