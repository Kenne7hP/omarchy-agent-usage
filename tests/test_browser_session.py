import base64
import ctypes
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import kimi_browser_session as session


KEY = b"_https://www.kimi.com\x00\x01access_token"


def varint(value):
  result = bytearray()
  while value >= 128:
    result.append((value & 127) | 128)
    value >>= 7
  return bytes(result) + bytes([value])


def field(value):
  return varint(len(value)) + value


def log_record(data, kind=1):
  return struct.pack("<IHB", session.masked_crc(bytes([kind]) + data), len(data), kind) + data


def block(entries):
  raw = b"".join(b"\0" + varint(len(key)) + varint(len(value)) + key + value for key, value in entries)
  return raw + struct.pack("<II", 0, 1)


def trailer(data, compressed=False):
  if compressed:
    lib = ctypes.CDLL("libsnappy.so.1")
    lib.snappy_max_compressed_length.argtypes = [ctypes.c_size_t]
    lib.snappy_max_compressed_length.restype = ctypes.c_size_t
    lib.snappy_compress.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    length = ctypes.c_size_t(lib.snappy_max_compressed_length(len(data)))
    output = ctypes.create_string_buffer(length.value)
    assert lib.snappy_compress(data, len(data), output, ctypes.byref(length)) == 0
    data = output.raw[:length.value]
  raw = data + bytes([1 if compressed else 0])
  return raw + struct.pack("<I", session.masked_crc(raw)), len(data)


def table(key, value, sequence=1, kind=1, compressed=False):
  internal = key + struct.pack("<Q", (sequence << 8) | kind)
  data, length = trailer(block([(internal, value)]), compressed)
  index, index_length = trailer(block([(internal, b"\0" + varint(length))]))
  footer = b"\0\0" + varint(len(data)) + varint(index_length)
  return data + index + footer.ljust(40, b"\0") + bytes.fromhex("57fb808b247547db")


def token(subject="same-account", audience="kimi.com", expiry=9999999999):
  payload = json.dumps({"sub": subject, "aud": [audience], "exp": expiry}).encode()
  return "header." + base64.urlsafe_b64encode(payload).decode().rstrip("=") + ".signature"


class BrowserSessionTests(unittest.TestCase):
  def setUp(self):
    self.root = Path(tempfile.mkdtemp(prefix="kimi-browser-test-"))

  def database(self, entries, log=b"", deleted=()):
    edit = b"\x01" + field(b"leveldb.BytewiseComparator") + b"\x02\x03"
    for number, content in entries.items():
      (self.root / f"{number:06d}.ldb").write_bytes(content)
      edit += b"\x07\0" + varint(number) + varint(len(content)) + field(b"a") + field(b"z")
    for number in deleted:
      edit += b"\x06\0" + varint(number)
    (self.root / "CURRENT").write_text("MANIFEST-000001\n")
    (self.root / "MANIFEST-000001").write_bytes(log_record(edit))
    (self.root / "000003.log").write_bytes(log)

  def test_current_manifest_ignores_removed_table_with_newer_sequence(self):
    self.database({1: table(KEY, b"old", sequence=99), 2: table(KEY, b"current", sequence=2)}, deleted=(1,))
    self.assertEqual(session.read_current_value(self.root, KEY), b"current")

  def test_sequence_order_and_tombstone_override_compacted_values(self):
    self.database({1: table(KEY, b"old", sequence=1), 2: table(KEY, b"new", sequence=2)})
    self.assertEqual(session.read_current_value(self.root, KEY), b"new")
    batch = struct.pack("<QI", 3, 1) + b"\0" + field(KEY)
    (self.root / "000003.log").write_bytes(log_record(batch))
    self.assertIsNone(session.read_current_value(self.root, KEY))

  def test_log_updates_override_tables(self):
    batch = struct.pack("<QI", 3, 1) + b"\x01" + field(KEY) + field(b"from-log")
    self.database({1: table(KEY, b"from-table")}, log_record(batch))
    self.assertEqual(session.read_current_value(self.root, KEY), b"from-log")

  def test_compressed_table_and_chromium_string_encoding(self):
    value = token()
    self.database({1: table(KEY, b"\x01" + value.encode(), compressed=True)})
    self.assertEqual(session.read_token(self.root), value)
    self.database({1: table(KEY, b"\0" + value.encode("utf-16-le"))})
    self.assertEqual(session.read_token(self.root), value)

  def test_expiry_wrong_audience_and_wrong_origin_are_rejected(self):
    for value in (token(expiry=1), token(audience="other.example")):
      self.database({1: table(KEY, b"\x01" + value.encode())})
      self.assertIsNone(session.read_token(self.root))
    with self.assertRaises(ValueError):
      session.read_token(self.root, "https://example.invalid")

  def test_corrupt_or_incomplete_storage_cannot_supply_stale_token(self):
    self.database({1: table(KEY, b"value")})
    (self.root / "000003.log").write_bytes(b"\x01\x02")
    with self.assertRaises(ValueError):
      session.read_current_value(self.root, KEY)
    (self.root / "000003.log").write_bytes(b"")
    data = (self.root / "000001.ldb").read_bytes()
    (self.root / "000001.ldb").write_bytes(bytes([data[0] ^ 1]) + data[1:])
    with self.assertRaises(ValueError):
      session.read_current_value(self.root, KEY)

  def test_symlinked_profile_is_rejected(self):
    self.database({1: table(KEY, b"value")})
    link = self.root / "alias"
    link.symlink_to(self.root, target_is_directory=True)
    with self.assertRaises(ValueError):
      session.read_current_value(link, KEY)

  def test_changing_profile_is_rejected(self):
    self.database({1: table(KEY, b"value")})
    original = Path.read_bytes
    def changing(path):
      data = original(path)
      if path.name == "000001.ldb":
        path.write_bytes(data + b"changed")
      return data
    with patch.object(Path, "read_bytes", changing), self.assertRaises(ValueError):
      session.read_current_value(self.root, KEY)

  def test_crc32c_known_vector(self):
    crc = 0xE3069283
    expected = (((crc >> 15) | (crc << 17)) + 0xA282EAD8) & 0xFFFFFFFF
    self.assertEqual(session.masked_crc(b"123456789"), expected)

  def test_session_pair_reads_only_exact_allowed_entries_and_detects_change(self):
    origin = "https://www.kimi.com"
    with patch.object(session, "read_credential", side_effect=["access", "refresh", "access", "refresh"]) as read:
      self.assertEqual(session.read_session(self.root, origin), {"access_token": "access", "refresh_token": "refresh"})
      self.assertEqual({call.args[2] for call in read.call_args_list}, {"access_token", "refresh_token"})
    with patch.object(session, "read_credential", side_effect=["access", "refresh", "access", "changed"]), self.assertRaises(ValueError):
      session.read_session(self.root, origin)
    with patch.object(session, "read_current_value") as read, self.assertRaises(ValueError):
      session.read_credential(self.root, origin, "unrelated_secret")
    read.assert_not_called()


if __name__ == "__main__":
  unittest.main()
