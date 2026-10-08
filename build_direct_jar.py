#!/usr/bin/env python3
"""从已核对的 pg.jar 生成系统网络版本，保留原始 JAR。

只做等长默认配置替换，保留 DEX 指令、偏移和其他资源。
输入版本变化时停止，防止对未知二进制静默打补丁。
"""
import hashlib
import struct
import os
import tempfile
import zipfile
import zlib
from pathlib import Path

SOURCE_SHA256 = "f5344c269bc837a2821e435015a93984895be8955ddfd778a50f5f89955ef916"


def patch_dex(original):
    data = bytearray(original)
    replacements = [
        (b"global_singbox_proxy_map", b"global_singbox_proxy_maQ", 1),
        (b"proxy=127.0.0.1:10172", b"proxy=127.0.0.1;10172", 1),
        (b"127.0.0.1:10172", b"127.0.0.1;10172", 1),
    ]
    # Init.initSingBox 的空订阅门禁键经过 XOR 编码；独立命名空间
    # 避免原配置曾保存的订阅触发下载。默认值为空，因此直接返回。
    key = bytes([53, 14, 112, 213, 52, 190, 133, 151])
    encode = lambda value: bytes(c ^ key[i % len(key)] for i, c in enumerate(value))
    replacements.append((encode(b"global_singbox_subscribe_url"),
                         encode(b"direct_singbox_subscribe_url"), 1))
    for old, new, expected in replacements:
        if len(old) != len(new) or data.count(old) != expected:
            raise ValueError("pg.jar 补丁定位不匹配；请先核对新版本")
        data = data.replace(old, new)
    # DEX string_ids 必须保持 UTF-16 字典序；等长替换也需要检查排序。
    count, offset = struct.unpack_from("<II", data, 56)
    previous = None
    for i in range(count):
        cursor = struct.unpack_from("<I", data, offset + i * 4)[0]
        while data[cursor] & 128:
            cursor += 1
        cursor += 1
        end = data.index(0, cursor)
        text = bytes(data[cursor:end]).replace(b"\xc0\x80", b"\x00").decode("utf-8", "surrogatepass")
        current = text.encode("utf-16-be", "surrogatepass")
        if previous is not None and current <= previous:
            raise ValueError("补丁改变了 DEX 字符串排序；禁止输出")
        previous = current
    data[12:32] = hashlib.sha1(data[32:]).digest()
    struct.pack_into("<I", data, 8, zlib.adler32(data[12:]) & 0xffffffff)
    return bytes(data)


def build(root=None):
    root = Path(root) if root else Path(__file__).resolve().parent
    source = root / "jar/pg.jar"
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("pg.jar 版本已改变；禁止套用旧补丁")
    target = root / "jar/pg_direct.jar"
    # 定位检查先完成；临时文件完整写入后再原子替换已有有效产物。
    with zipfile.ZipFile(source) as src:
        dex = patch_dex(src.read("classes.dex"))
        handle, temporary = tempfile.mkstemp(prefix=".pg_direct-", suffix=".jar", dir=str(target.parent))
        os.close(handle)
        try:
            with zipfile.ZipFile(temporary, "w") as dst:
                for info in src.infolist():
                    data = dex if info.filename == "classes.dex" else src.read(info.filename)
                    dst.writestr(info, data)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    print("生成 jar/pg_direct.jar；原始 JAR 保留")
    return target


if __name__ == "__main__":
    build()
