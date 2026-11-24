from hcr2_proto import get_message_class

FSMessageCls = get_message_class("FSMessage")
for f in FSMessageCls.DESCRIPTOR.fields:
    if f.name == "Version":
        print(f"Version: label={f.label}, type={f.type}")
