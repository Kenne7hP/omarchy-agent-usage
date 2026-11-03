"""Read one current Kimi access-token entry without opening/writing LevelDB.

Format references: google/leveldb doc/{log,table}_format.md,
db/version_edit.cc, table/format.cc. No profile copies or token caching.
"""

import base64
import ctypes
import json
import struct
import time
from pathlib import Path


def varint(data, pos):
  value = 0
  for shift in range(0, 70, 7):
    byte = data[pos]
    pos += 1
    value |= (byte & 127) << shift
    if byte < 128:
      return value, pos
  raise ValueError("Invalid LevelDB integer")


def field(data, pos):
  length, pos = varint(data, pos)
  if pos + length > len(data):
    raise ValueError("Incomplete LevelDB field")
  return data[pos:pos + length], pos + length


CRC_TABLE = []
for _index in range(256):
  _crc = _index
  for _bit in range(8):
    _crc = (_crc >> 1) ^ (0x82F63B78 if _crc & 1 else 0)
  CRC_TABLE.append(_crc)


def masked_crc(data):
  crc = 0xFFFFFFFF
  for byte in data:
    crc = CRC_TABLE[(crc ^ byte) & 255] ^ (crc >> 8)
  crc ^= 0xFFFFFFFF
  return (((crc >> 15) | (crc << 17)) + 0xA282EAD8) & 0xFFFFFFFF


def log_records(data):
  fragments = None
  for start in range(0, len(data), 32768):
    block = data[start:start + 32768]
    pos = 0
    while pos + 7 <= len(block):
      crc, length, kind = struct.unpack_from("<IHB", block, pos)
      pos += 7
      if kind == 0 and length == 0 and not any(block[pos:]):
        break
      payload = block[pos:pos + length]
      pos += length
      if len(payload) != length or masked_crc(bytes([kind]) + payload) != crc:
        raise ValueError("Incomplete or corrupt LevelDB log")
      if kind == 1 and fragments is None:
        yield payload
      elif kind == 2 and fragments is None:
        fragments = payload
      elif kind in (3, 4) and fragments is not None:
        fragments += payload
        if kind == 4:
          yield fragments
          fragments = None
      else:
        raise ValueError("Invalid LevelDB fragments")
    if pos < len(block) and any(block[pos:]):
      raise ValueError("Incomplete LevelDB trailer")
  if fragments is not None:
    raise ValueError("Incomplete LevelDB record")


def manifest_files(data):
  tables = set()
  logs = {2: 0, 9: 0}
  for record in log_records(data):
    pos = 0
    while pos < len(record):
      tag, pos = varint(record, pos)
      if tag == 1:
        comparator, pos = field(record, pos)
        if comparator != b"leveldb.BytewiseComparator":
          raise ValueError("Unsupported LevelDB comparator")
      elif tag in (2, 3, 4, 9):
        value, pos = varint(record, pos)
        if tag in logs:
          logs[tag] = value
      elif tag == 5:
        _, pos = varint(record, pos)
        _, pos = field(record, pos)
      elif tag in (6, 7):
        _, pos = varint(record, pos)
        number, pos = varint(record, pos)
        if tag == 6:
          tables.discard(number)
        else:
          _, pos = varint(record, pos)
          _, pos = field(record, pos)
          _, pos = field(record, pos)
          tables.add(number)
      else:
        raise ValueError("Unsupported LevelDB manifest")
  return tables, {number for number in logs.values() if number}


def table_block(data, handle):
  offset, pos = varint(handle, 0)
  size, _ = varint(handle, pos)
  raw = data[offset:offset + size + 5]
  if len(raw) != size + 5 or masked_crc(raw[:-4]) != struct.unpack("<I", raw[-4:])[0]:
    raise ValueError("Incomplete or corrupt LevelDB table")
  kind, compressed = raw[-5], raw[:-5]
  if kind == 0:
    return compressed
  if kind != 1:
    raise ValueError("Unsupported LevelDB compression")
  library = ctypes.CDLL("libsnappy.so.1")
  library.snappy_uncompressed_length.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
  library.snappy_uncompress.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
  length = ctypes.c_size_t()
  if library.snappy_uncompressed_length(compressed, len(compressed), ctypes.byref(length)) != 0 or length.value > 16 * 1024 * 1024:
    raise ValueError("Invalid Snappy block")
  output = ctypes.create_string_buffer(length.value)
  if library.snappy_uncompress(compressed, len(compressed), output, ctypes.byref(length)) != 0:
    raise ValueError("Invalid Snappy block")
  return output.raw[:length.value]


def block_entries(data):
  count = struct.unpack("<I", data[-4:])[0]
  end = len(data) - 4 * (count + 1)
  if end < 0:
    raise ValueError("Invalid LevelDB block")
  pos, previous = 0, b""
  while pos < end:
    shared, pos = varint(data, pos)
    unshared, pos = varint(data, pos)
    size, pos = varint(data, pos)
    if shared > len(previous) or pos + unshared + size > end:
      raise ValueError("Invalid LevelDB entry")
    key = previous[:shared] + data[pos:pos + unshared]
    pos += unshared
    value = data[pos:pos + size]
    pos += size
    yield key, value
    previous = key


def table_entries(data):
  if len(data) < 48 or data[-8:] != bytes.fromhex("57fb808b247547db"):
    raise ValueError("Invalid LevelDB table footer")
  footer = data[-48:-8]
  _, pos = varint(footer, 0)
  _, pos = varint(footer, pos)
  for _, handle in block_entries(table_block(data, footer[pos:])):
    yield from block_entries(table_block(data, handle))


def read_current_value(directory, target):
  snapshots = {}

  def read(path):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
      raise ValueError("Symlinked browser profile")
    before = path.stat()
    content = path.read_bytes()
    after = path.stat()
    stamp = lambda s: (s.st_ino, s.st_size, s.st_mtime_ns)
    if stamp(before) != stamp(after):
      raise ValueError("Browser storage changed during read")
    snapshots[path] = stamp(after)
    return content

  current = read(directory / "CURRENT").decode().strip()
  if not current.startswith("MANIFEST-") or not current[9:].isdigit():
    raise ValueError("Invalid current LevelDB manifest")
  tables, logs = manifest_files(read(directory / current))
  newest = (-1, None)
  for number in tables:
    for key, value in table_entries(read(directory / f"{number:06d}.ldb")):
      if key[:-8] == target:
        packed = struct.unpack("<Q", key[-8:])[0]
        sequence, kind = packed >> 8, packed & 255
        if kind not in (0, 1):
          raise ValueError("Invalid LevelDB value type")
        if sequence > newest[0]:
          newest = (sequence, value if kind == 1 else None)
  for number in logs:
    for record in log_records(read(directory / f"{number:06d}.log")):
      sequence, count = struct.unpack_from("<QI", record)
      pos = 12
      for offset in range(count):
        kind, pos = record[pos], pos + 1
        if kind not in (0, 1):
          raise ValueError("Invalid LevelDB batch")
        key, pos = field(record, pos)
        value, pos = field(record, pos) if kind == 1 else (None, pos)
        if key == target and sequence + offset > newest[0]:
          newest = (sequence + offset, value)
      if pos != len(record):
        raise ValueError("Invalid LevelDB batch length")
  for path, expected in snapshots.items():
    s = path.stat()
    if (s.st_ino, s.st_size, s.st_mtime_ns) != expected:
      raise ValueError("Browser storage changed during read")
  return newest[1]


def claims(token):
  if token.count(".") != 2:
    raise ValueError("Invalid Kimi session")
  payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))
  if not isinstance(payload, dict):
    raise ValueError("Invalid Kimi session claims")
  return payload


def read_credential(directory, origin, name):
  if origin not in ("https://www.kimi.com", "https://www.kimi.ai"):
    raise ValueError("Unsupported Kimi origin")
  if name not in ("access_token", "refresh_token"):
    raise ValueError("Unsupported Kimi credential")
  key = b"_" + origin.encode() + b"\x00\x01" + name.encode()
  raw = read_current_value(directory, key)
  if not raw:
    return None
  if raw[0] not in (0, 1):
    raise ValueError("Invalid Chromium string encoding")
  return raw[1:].decode("latin1" if raw[0] == 1 else "utf-16-le")


def read_session(directory, origin):
  access = read_credential(directory, origin, "access_token")
  if not access:
    return None
  refresh = read_credential(directory, origin, "refresh_token")
  if (access != read_credential(directory, origin, "access_token")
      or refresh != read_credential(directory, origin, "refresh_token")):
    raise ValueError("Browser session changed during read")
  return {"access_token": access, "refresh_token": refresh}


def read_token(directory, origin="https://www.kimi.com"):
  token = read_credential(directory, origin, "access_token")
  if not token:
    return None
  parsed = claims(token)
  audience = parsed.get("aud", [])
  if isinstance(audience, str):
    audience = [audience]
  if origin.removeprefix("https://www.") not in audience:
    return None
  if parsed.get("exp", 0) <= time.time() + 30:
    return None
  return token
