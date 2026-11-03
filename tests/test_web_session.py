import base64
import concurrent.futures
import io
import json
import os
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from test_kimi import kimi
import kimi_web_session as session


ORIGIN = "https://www.kimi.com"


def token(expiry=3600, subject="same", audience="kimi.com"):
  payload = {"exp": time.time() + expiry, "sub": subject, "aud": [audience],
             "device_id": "synthetic-device", "ssid": "synthetic-session"}
  body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
  return "header." + body + ".signature"


def usage_payload():
  return {"usages": [{"scope": "FEATURE_CODING",
    "detail": {"limit": "1000", "remaining": "750", "resetTime": "2026-11-10T00:00:00Z"},
    "limits": [{"window": {"duration": 5, "timeUnit": "TIME_UNIT_HOUR"},
      "detail": {"limit": "100", "used": "10", "resetTime": "2026-11-04T00:00:00Z"}}]}]}


class WebsiteCollectorTests(unittest.TestCase):
  def setUp(self):
    self.home = Path(tempfile.mkdtemp(prefix="kimi-web-collector-test-"))
    (self.home / "credentials").mkdir()
    (self.home / "credentials/kimi-code.json").write_text(json.dumps({"access_token": token(-3600)}))

  def test_expired_code_login_does_not_prevent_three_website_windows(self):
    responses = [usage_payload(), {"subscriptionBalance": {"amountUsedRatio": 0.4, "expireTime": "2026-12-01T00:00:00Z"}}]
    with patch.object(kimi, "web_login", return_value=token()), patch.object(kimi.urllib.request, "build_opener") as build:
      build.return_value.open.side_effect = [io.BytesIO(json.dumps(p).encode()) for p in responses]
      record = kimi.collect(self.home)
      requests = [c.args[0] for c in build.return_value.open.call_args_list]
    self.assertEqual([w["title"] for w in record["limits"]], ["Session", "Weekly", "Monthly total"])
    self.assertEqual([w["percent"] for w in record["limits"]], [0.1, 0.25, 0.4])
    self.assertEqual(record["usageStatusText"], "")
    self.assertEqual(len(requests), 2)
    self.assertTrue(all(r.full_url.startswith(ORIGIN + "/apiv2/") for r in requests))
    self.assertEqual(json.loads(requests[0].data), {"scope": ["FEATURE_CODING"]})
    self.assertEqual(requests[0].get_header("X-msh-device-id"), "synthetic-device")
    self.assertEqual(requests[0].get_header("X-msh-session-id"), "synthetic-session")
    self.assertEqual(requests[0].get_header("X-traffic-id"), "same")

  def test_monthly_failure_does_not_trigger_code_client_or_discard_short_windows(self):
    with patch.object(kimi, "web_login", return_value=token()), patch.object(kimi, "fetch_web", return_value=usage_payload()), patch.object(kimi, "fetch_monthly", side_effect=TimeoutError("secret")), patch.object(kimi.urllib.request, "build_opener") as build:
      record = kimi.collect(self.home)
      build.assert_not_called()
    self.assertEqual(len(record["limits"]), 2)
    self.assertEqual(record["usageStatusText"], "Monthly quota unavailable")
    self.assertNotIn("secret", json.dumps(record))
    self.assertNotIn("Open Kimi Code", json.dumps(record))

  def test_monthly_breakdown_is_collected_without_extra_request(self):
    responses = [usage_payload(), {"subscriptionBalance": {
      "amountUsedRatio": 0.4, "kimiCodeUsedRatio": 0.1,
      "expireTime": "2026-12-01T00:00:00Z"}}]
    with patch.object(kimi, "web_login", return_value=token()), patch.object(kimi.urllib.request, "build_opener") as build:
      build.return_value.open.side_effect = [io.BytesIO(json.dumps(p).encode()) for p in responses]
      record = kimi.collect(self.home)
      self.assertEqual(build.return_value.open.call_count, 2)
    self.assertEqual([w["title"] for w in record["limits"]],
      ["Session", "Weekly", "Monthly total", "Monthly Kimi share", "Monthly Code share"])
    self.assertAlmostEqual(record["limits"][3]["percent"], 0.3)
    self.assertEqual(record["limits"][4]["percent"], 0.1)
    self.assertEqual(record["usageStatusText"], "")
    self.assertTrue(all(w["resetsAt"] == "2026-12-01T00:00:00Z" for w in record["limits"][2:]))

  def test_counter_meanings_missing_values_and_window_selection(self):
    payload = usage_payload()
    item = payload["usages"][0]
    item["limits"].insert(0, {"window": {"duration": 1, "timeUnit": "TIME_UNIT_HOUR"}, "detail": {"limit": 10, "used": 9}})
    self.assertEqual([x["percent"] for x in kimi.web_quota_limits(payload)], [0.1, 0.25])
    item["detail"]["used"] = "1200"
    self.assertEqual(kimi.web_quota_limits(payload)[1]["percent"], 1.2)
    item["detail"] = {"limit": 100}
    self.assertEqual([x["title"] for x in kimi.web_quota_limits(payload)], ["Session"])
    item["limits"] = []
    for detail in ({"limit": 0, "used": 0}, {"limit": 10, "remaining": 11}, {"limit": True, "used": 0}, {"limit": 10, "used": "NaN"}):
      item["detail"] = detail
      with self.subTest(detail=detail), self.assertRaises(kimi.UsageError):
        kimi.web_quota_limits(payload)

  def test_refresh_request_matches_official_auth_host_and_snake_case_body(self):
    old = token(-1)
    with patch.object(kimi, "post_json", return_value={}) as request:
      kimi.renew_web(ORIGIN, "synthetic-refresh", old)
    url, body, headers = request.call_args.args
    self.assertEqual(url, "https://auth.kimi.com/api/account.gateway.v1.AuthService/RefreshToken")
    self.assertEqual(body, {"refresh_token": "synthetic-refresh"})
    self.assertNotIn("Authorization", headers)
    self.assertNotIn("Cookie", headers)
    self.assertEqual(headers["Origin"], ORIGIN)
    with patch.object(kimi, "post_json") as request, self.assertRaises(kimi.UsageError):
      kimi.renew_web("https://www.kimi.ai", "synthetic-refresh", old)
    request.assert_not_called()


class RenewalTests(unittest.TestCase):
  def setUp(self):
    self.home = Path(tempfile.mkdtemp(prefix="kimi-renewal-test-"))
    (self.home / "credentials").mkdir()
    self.directory = self.home / "credentials/omarchy-usage"
    self.code = token(-7200)
    self.source = {"access_token": token(-3600), "refresh_token": "synthetic-browser-refresh"}
    self.renewed = {"access_token": token(), "refresh_token": "synthetic-rotated-refresh"}
    self.refresh = Mock(return_value=self.renewed)
    self.browser = patch.object(session, "read_session", return_value=self.source).start()
    self.addCleanup(patch.stopall)

  def access(self):
    return session.access_token(self.home, ORIGIN, self.code, self.refresh)

  def test_renewed_pair_is_private_and_reused_without_touching_browser_or_code(self):
    self.assertEqual(self.access(), self.renewed["access_token"])
    self.refresh.assert_called_once_with(self.source["refresh_token"], self.source["access_token"])
    self.assertEqual(self.access(), self.renewed["access_token"])
    self.assertEqual(self.refresh.call_count, 1)
    cached = json.loads((self.directory / "session.json").read_text())
    self.assertEqual(cached["refresh_token"], self.renewed["refresh_token"])
    self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
    self.assertEqual((self.directory / "session.json").stat().st_mode & 0o777, 0o600)
    self.assertEqual(self.source["refresh_token"], "synthetic-browser-refresh")
    self.assertEqual(sorted(p.name for p in self.home.iterdir()), ["credentials"])

  def test_next_expiry_uses_rotated_refresh_token(self):
    self.access()
    with patch.object(session.time, "time", return_value=time.time() + 7200):
      self.refresh.return_value = {"access_token": token(10800), "refresh_token": "next-refresh"}
      self.access()
    self.assertEqual(self.refresh.call_args.args, ("synthetic-rotated-refresh", self.renewed["access_token"]))

  def test_parallel_collectors_refresh_only_once(self):
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
      results = list(pool.map(lambda _: self.access(), range(2)))
    self.assertEqual(results, [self.renewed["access_token"]] * 2)
    self.assertEqual(self.refresh.call_count, 1)

  def test_fresh_browser_needs_no_refresh_or_cache(self):
    self.source["access_token"] = token()
    self.assertEqual(self.access(), self.source["access_token"])
    self.refresh.assert_not_called()
    self.assertFalse(self.directory.exists())

  def test_logout_and_account_switch_cannot_reuse_cached_session(self):
    self.access()
    for source in (None, {"access_token": token(subject="different"), "refresh_token": "different"}):
      self.browser.return_value = source
      with self.assertRaises(session.SessionError):
        self.access()
    self.assertEqual(self.refresh.call_count, 1)

  def test_new_browser_login_replaces_old_source_binding(self):
    self.access()
    self.source = {"access_token": token(-10), "refresh_token": "new-browser-refresh"}
    self.browser.return_value = self.source
    self.access()
    self.assertEqual(self.refresh.call_args.args[0], "new-browser-refresh")

  def test_mismatched_expired_response_and_missing_rotation_are_not_saved(self):
    for pair in ({"access_token": token(subject="different"), "refresh_token": "new"},
                 {"access_token": token(-1), "refresh_token": "new"},
                 {"access_token": token(), "refresh_token": ""}):
      self.refresh.return_value = pair
      with self.subTest(pair_type=bool(pair["refresh_token"])), self.assertRaises(session.SessionError):
        self.access()
      self.assertFalse((self.directory / "session.json").exists())

  def test_session_change_during_renewal_does_not_save_new_credentials(self):
    self.browser.side_effect = [self.source, self.source, None]
    with self.assertRaises(session.SessionError):
      self.access()
    self.assertFalse((self.directory / "session.json").exists())

  def test_network_and_revocation_failures_do_not_save_or_retry(self):
    for error in (TimeoutError("synthetic-secret"), urllib.error.HTTPError(ORIGIN, 401, "synthetic-secret", {}, None)):
      self.refresh.side_effect = error
      before = self.refresh.call_count
      with self.assertRaises(type(error)):
        self.access()
      self.assertEqual(self.refresh.call_count, before + 1)
      self.assertFalse((self.directory / "session.json").exists())
      if isinstance(error, urllib.error.HTTPError): error.close()

  def test_symlink_or_public_cache_is_rejected_without_overwriting_target(self):
    self.directory.mkdir(mode=0o700)
    target = self.home / "untouched"
    target.write_text("do not modify")
    (self.directory / "session.pending").symlink_to(target)
    with self.assertRaises(OSError):
      self.access()
    self.assertEqual(target.read_text(), "do not modify")
    self.directory.chmod(0o755)
    with self.assertRaises(session.SessionError):
      self.access()

  def test_other_region_never_sends_refresh_token_to_china(self):
    self.source["access_token"] = token(-1, audience="kimi.ai")
    with self.assertRaises(session.SessionError):
      session.access_token(self.home, "https://www.kimi.ai", self.code, self.refresh)
    self.refresh.assert_not_called()

  def test_unsafe_hardlinked_pending_file_is_not_truncated(self):
    self.directory.mkdir(mode=0o700)
    target = self.home / "untouched"
    target.write_text("do not modify")
    target.chmod(0o600)
    os.link(target, self.directory / "session.pending")
    with self.assertRaises(session.SessionError):
      self.access()
    self.assertEqual(target.read_text(), "do not modify")


if __name__ == "__main__":
  unittest.main()
