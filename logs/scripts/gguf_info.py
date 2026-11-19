"""Print the metadata of a GGUF file: what kind of model it is and what it expects.

    python logs/scripts/gguf_info.py <file.gguf> [--tensors]

Reads only the header; never loads the weights. Used to find out which runtime a model needs.
"""
import struct
import sys

TYPES = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}


def read_str(f):
    (n,) = struct.unpack("<Q", f.read(8))
    return f.read(n).decode("utf-8", "replace")


def read_val(f, t):
    if t in TYPES:
        fmt = "<" + TYPES[t]
        return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]
    if t == 8:
        return read_str(f)
    if t == 9:
        (et,) = struct.unpack("<I", f.read(4))
        (n,) = struct.unpack("<Q", f.read(8))
        vals = [read_val(f, et) for _ in range(n)]
        return vals if n <= 12 else f"[{n} items, first: {vals[:4]}]"
    raise ValueError(f"unknown type {t}")


with open(sys.argv[1], "rb") as f:
    magic, version = f.read(4), struct.unpack("<I", f.read(4))[0]
    n_tensors, n_kv = struct.unpack("<QQ", f.read(16))
    print(f"magic {magic!r}  version {version}  tensors {n_tensors}  metadata keys {n_kv}")
    for _ in range(n_kv):
        key = read_str(f)
        (t,) = struct.unpack("<I", f.read(4))
        val = read_val(f, t)
        text = str(val)
        print(f"  {key} = {text[:300]}")
    if "--tensors" in sys.argv:
        for i in range(min(n_tensors, 400)):
            name = read_str(f)
            (nd,) = struct.unpack("<I", f.read(4))
            dims = struct.unpack("<" + "Q" * nd, f.read(8 * nd))
            (dt,) = struct.unpack("<I", f.read(4))
            f.read(8)
            if i < 25 or i % 40 == 0:
                print(f"  tensor {name} {dims} type {dt}")
