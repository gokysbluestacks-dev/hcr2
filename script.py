import idautils, idc
for s in idautils.Strings():
    if "zipped" in str(s).lower():
        print(hex(s.ea), str(s))
