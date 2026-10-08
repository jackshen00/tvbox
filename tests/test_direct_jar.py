import hashlib
import struct
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

from build_direct_jar import SOURCE_SHA256, build, patch_dex
ROOT = Path(__file__).resolve().parents[1]

class DirectJarTests(unittest.TestCase):
    def test_pinned_source_and_reproducible_dex(self):
        self.assertEqual(hashlib.sha256((ROOT / 'jar/pg.jar').read_bytes()).hexdigest(), SOURCE_SHA256)
        with zipfile.ZipFile(ROOT / 'jar/pg.jar') as src, zipfile.ZipFile(ROOT / 'jar/pg_direct.jar') as dst:
            original, direct = src.read('classes.dex'), dst.read('classes.dex')
            self.assertEqual(direct, patch_dex(original))
            self.assertEqual(len(direct), len(original))
            self.assertEqual(direct[12:32], hashlib.sha1(direct[32:]).digest())
            self.assertEqual(struct.unpack_from('<I', direct, 8)[0], zlib.adler32(direct[12:]) & 0xffffffff)
            for name in src.namelist():
                if name != 'classes.dex': self.assertEqual(src.read(name), dst.read(name))
    def test_isolated_proxy_map_and_default_direct_alias(self):
        with zipfile.ZipFile(ROOT / 'jar/pg_direct.jar') as z: data = z.read('classes.dex')
        self.assertNotIn(b'global_singbox_proxy_map', data)
        self.assertIn(b'global_singbox_proxy_maQ', data)
        self.assertNotIn(b'127.0.0.1:10172', data)
        self.assertIn(b'proxy=127.0.0.1;10172', data)
        key = bytes([53,14,112,213,52,190,133,151])
        encode = lambda value: bytes(c ^ key[i % len(key)] for i,c in enumerate(value))
        self.assertEqual(data.count(encode(b'global_singbox_subscribe_url')), 0)
        self.assertEqual(data.count(encode(b'direct_singbox_subscribe_url')), 1)
    def test_bad_patch_does_not_truncate_existing_jar(self):
        target = ROOT / 'jar/pg_direct.jar'; before = target.read_bytes()
        with patch('build_direct_jar.patch_dex', side_effect=ValueError('bad version')):
            with self.assertRaises(ValueError): build(ROOT)
        self.assertEqual(target.read_bytes(), before)
    def test_rejects_unknown_dex(self):
        with self.assertRaises(ValueError): patch_dex(bytes(128))

if __name__ == '__main__': unittest.main()
