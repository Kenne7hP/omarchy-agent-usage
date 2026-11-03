"""Renew the exact browser-origin login without modifying browser or Code storage."""

import fcntl
import hashlib
import json
import math
import os
import stat
import time
from pathlib import Path

from kimi_browser_session import claims, read_session


class SessionError(Exception):
  pass


LOGIN_HELP = "Sign in to the Kimi website in Chromium, then refresh this panel."


def validate_access(token, origin, subject, fresh=False):
  parsed = claims(token)
  audience = parsed.get("aud", [])
  if isinstance(audience, str):
    audience = [audience]
  if not subject or parsed.get("sub") != subject or origin.removeprefix("https://www.") not in audience:
    raise SessionError("Chromium's Kimi account differs from Kimi Code or its region.")
  expiry = parsed.get("exp")
  if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry):
    raise SessionError(LOGIN_HELP)
  if fresh and expiry <= time.time() + 60:
    raise SessionError(LOGIN_HELP)
  return expiry


def private_file(path, flags):
  fd = os.open(path, (flags & ~os.O_TRUNC) | os.O_NOFOLLOW, 0o600)
  info = os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
    os.close(fd)
    raise SessionError("Kimi website credential cache has unsafe permissions.")
  if flags & os.O_TRUNC:
    os.ftruncate(fd, 0)
  return fd


def access_token(home, origin, code_token, refresh_request):
  """refresh_request accepts refresh/access tokens and returns the official pair."""
  if origin not in ("https://www.kimi.com", "https://www.kimi.ai"):
    raise SessionError("Unsupported Kimi website.")
  subject = claims(code_token).get("sub")
  browser = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "chromium/Default/Local Storage/leveldb"
  source = read_session(browser, origin)
  if not source:
    raise SessionError(LOGIN_HELP)
  expiry = validate_access(source["access_token"], origin, subject)
  # A fresh browser login needs no credential cache or refresh request.
  if expiry > time.time() + 60:
    return source["access_token"]
  if origin != "https://www.kimi.com":
    raise SessionError("Automatic renewal is not verified for kimi.ai. " + LOGIN_HELP)
  if not isinstance(source.get("refresh_token"), str) or not source["refresh_token"]:
    raise SessionError(LOGIN_HELP)

  directory = home / "credentials/omarchy-usage"
  if any(p.is_symlink() for p in (directory, *directory.parents)):
    raise SessionError("Kimi website credential cache must not use symlinks.")
  directory.mkdir(mode=0o700, exist_ok=True)
  info = directory.stat()
  if info.st_uid != os.getuid() or info.st_mode & 0o077:
    raise SessionError("Kimi website credential directory must be private (0700).")
  with os.fdopen(private_file(directory / "session.lock", os.O_CREAT | os.O_RDWR), "r+") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    # Bind the cache to both source entries. Logout/deletion/relogin invalidates it.
    if read_session(browser, origin) != source:
      raise SessionError("Kimi website session changed; refresh this panel again.")
    fingerprint = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    path = directory / "session.json"
    pair = source
    try:
      with os.fdopen(private_file(path, os.O_RDONLY)) as stream:
        cached = json.load(stream)
      if cached.get("source") == fingerprint and cached.get("origin") == origin:
        pair = cached
        validate_access(pair["access_token"], origin, subject)
    except FileNotFoundError:
      pass
    if validate_access(pair["access_token"], origin, subject) > time.time() + 60:
      return pair["access_token"]
    # Only one renewal attempt per collection. Never fall back to a stale pair
    # after a rotated refresh token is rejected.
    result = refresh_request(pair["refresh_token"], pair["access_token"])
    if not isinstance(result, dict) or not isinstance(result.get("refresh_token"), str) or not result["refresh_token"]:
      raise SessionError("Kimi returned an invalid renewed website session.")
    validate_access(result.get("access_token", ""), origin, subject, fresh=True)
    if read_session(browser, origin) != source:
      raise SessionError("Kimi website session changed during renewal; refresh again.")
    saved = {"source": fingerprint, "origin": origin,
             "access_token": result["access_token"], "refresh_token": result["refresh_token"]}
    temporary = directory / "session.pending"
    with os.fdopen(private_file(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY), "w") as stream:
      json.dump(saved, stream, separators=(",", ":"))
      stream.flush()
      os.fsync(stream.fileno())
    os.replace(temporary, path)
    return saved["access_token"]
