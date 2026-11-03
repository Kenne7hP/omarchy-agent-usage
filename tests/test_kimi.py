import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("kimi", str(ROOT / "bin/omarchy-agent-usage-kimi"))
spec = importlib.util.spec_from_loader(loader.name, loader)
kimi = importlib.util.module_from_spec(spec)
loader.exec_module(kimi)


class CollectorTests(unittest.TestCase):
  def setUp(self):
    self.home = Path(tempfile.mkdtemp(prefix="kimi-test-"))
    (self.home / "credentials").mkdir()
    self.login("kimi-code", "synthetic-token")
    browser = patch.object(kimi, "web_login", side_effect=kimi.UsageError("Synthetic test has no web login"))
    browser.start()
    self.addCleanup(browser.stop)

  def login(self, name, token):
    (self.home / "credentials" / (name + ".json")).write_text(json.dumps({"access_token": token}))

  def test_all_windows_are_used_ratios_and_months_remain_distinct(self):
    payload = {"usages": {
      key: {"used_ratio": ratio, "reset_time": "2026-12-01T00:00:00Z"}
      for (key, _, _), ratio in zip(kimi.WINDOWS, [0, 0.2, "0.4", 1.1])
    }}
    limits = kimi.quota_limits(payload)
    self.assertEqual([x["percent"] for x in limits], [0, 0.2, 0.4, 1.1])
    self.assertEqual([x["title"] for x in limits], ["Session", "Weekly", "Monthly total", "Monthly Code share"])
    self.assertTrue(all(x["resetsAt"] == "2026-12-01T00:00:00Z" for x in limits))

  def test_invalid_ratios_are_rejected(self):
    for value in [None, "", True, False, "nan", "inf", -0.1, {}]:
      with self.subTest(value=value), self.assertRaises(kimi.UsageError):
        kimi.quota_limits({"usages": {"limit_5h": {"used_ratio": value}}})
    for payload in [None, {}, [], {"usages": {}}, {"usages": []}]:
      with self.subTest(payload=payload), self.assertRaises(kimi.UsageError):
        kimi.quota_limits(payload)

  def test_configured_scoped_token_and_global_host(self):
    self.login("kimi-code-env-test", "scoped-token")
    (self.home / "config.toml").write_text(
      '[providers."managed:kimi-code"]\nbase_url="https://api.kimi.ai/coding/v1/"\n'
      'oauth={storage="file",key="oauth/kimi-code-env-test"}\n')
    self.assertEqual(kimi.read_login(self.home), ("https://api.kimi.ai/coding/v1/usages", "scoped-token"))

  def test_unsafe_endpoint_and_token_paths_do_not_make_requests(self):
    for config in [
      'base_url="https://example.invalid/coding/v1"',
      'oauth={key="oauth/../outside"}',
      'oauth={key="oauth/../../outside"}',
      'oauth={storage="keyring",key="oauth/kimi-code"}',
    ]:
      (self.home / "config.toml").write_text('[providers."managed:kimi-code"]\n' + config)
      with patch.object(kimi.urllib.request, "build_opener") as opener:
        record = kimi.collect(self.home)
        self.assertTrue(record["usageStatusText"])
        self.assertEqual(record["limits"], [])
        opener.assert_not_called()

  def test_request_matches_official_headers_method_and_no_body(self):
    payload = {"usages": {"limit_5h": {"used_ratio": 0.37},
                           "limit_month_total": {"used_ratio": 0.5}}}
    with patch.object(kimi.urllib.request, "build_opener") as build:
      build.return_value.open.return_value = io.BytesIO(json.dumps(payload).encode())
      record = kimi.collect(self.home)
      request = build.return_value.open.call_args.args[0]
      self.assertEqual(request.full_url, kimi.DEFAULT_BASE + "/usages")
      self.assertEqual(request.get_method(), "GET")
      self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-token")
      self.assertEqual(request.get_header("Accept"), "application/json")
      self.assertIsNone(request.data)
      self.assertEqual(build.return_value.open.call_args.kwargs["timeout"], 8)
    self.assertEqual(record["limits"][0]["percent"], 0.37)
    self.assertFalse(record["hasLocalStats"])
    self.assertNotIn("synthetic-token", json.dumps(record))

  def test_auth_and_network_failures_do_not_expose_exception_bodies(self):
    for error in [
      urllib.error.HTTPError(kimi.DEFAULT_BASE, 401, "synthetic-token", {}, None),
      urllib.error.HTTPError(kimi.DEFAULT_BASE, 429, "synthetic-token", {}, None),
      urllib.error.URLError("synthetic-token"),
      TimeoutError("synthetic-token"),
    ]:
      with patch.object(kimi.urllib.request, "build_opener") as build:
        build.return_value.open.side_effect = error
        record = kimi.collect(self.home)
      self.assertTrue(record["ready"])
      self.assertTrue(record["usageStatusText"])
      self.assertEqual(record["limits"], [])
      self.assertNotIn("synthetic-token", json.dumps(record))
      if isinstance(error, urllib.error.HTTPError):
        error.close()

  def test_malformed_credentials_and_response_stay_valid_json(self):
    (self.home / "credentials/kimi-code.json").write_text("not json")
    record = kimi.collect(self.home)
    self.assertTrue(record["usageStatusText"])
    self.login("kimi-code", "synthetic-token")
    with patch.object(kimi.urllib.request, "build_opener") as build:
      build.return_value.open.return_value = io.BytesIO(b"not json synthetic-token")
      record = kimi.collect(self.home)
    self.assertNotIn("synthetic-token", json.dumps(record, allow_nan=False))
    self.assertTrue(record["usageStatusText"])

  def test_unconfigured_machine_stays_hidden(self):
    home = self.home / "absent"
    with patch.object(kimi.urllib.request, "build_opener") as build:
      record = kimi.collect(home)
      build.assert_not_called()
    self.assertFalse(record["ready"])
    self.assertEqual(record["usageStatusText"], "")

  def test_authenticated_request_does_not_follow_redirects(self):
    handler = kimi.NoRedirect()
    self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, "https://example.invalid"))


class MonthlyTests(unittest.TestCase):
  def test_monthly_remains_available_when_code_token_expires(self):
    home = Path(tempfile.mkdtemp(prefix="kimi-monthly-test-"))
    (home / "credentials").mkdir()
    (home / "credentials/kimi-code.json").write_text('{"access_token":"synthetic-token"}')
    error = urllib.error.HTTPError(kimi.DEFAULT_BASE, 401, "unauthorized", {}, None)
    monthly = kimi.monthly_limit({"subscriptionBalance": {"amountUsedRatio": 0.73}})
    with patch.object(kimi.urllib.request, "build_opener") as build, patch.object(kimi, "web_login", return_value="synthetic-web-token"), patch.object(kimi, "fetch_monthly", return_value=[monthly]):
      build.return_value.open.side_effect = error
      record = kimi.collect(home)
    error.close()
    self.assertEqual(record["limits"], [monthly])
    self.assertEqual(record["usageStatusText"], "Kimi usage partially unavailable")
    self.assertNotIn("Open Kimi Code", record["authHelpText"])

  def test_shared_monthly_ratio_and_reset_are_used(self):
    limit = kimi.monthly_limit({"subscriptionBalance": {
      "feature": "FEATURE_OMNI", "type": "SUBSCRIPTION",
      "amountUsedRatio": 0.72, "kimiCodeUsedRatio": 0.13,
      "expireTime": "2026-12-01T00:00:00Z",
    }})
    self.assertEqual(limit["title"], "Monthly total")
    self.assertEqual(limit["percent"], 0.72)
    self.assertEqual(limit["resetsAt"], "2026-12-01T00:00:00Z")

  def test_missing_or_invalid_breakdown_preserves_total_without_inventing_zero(self):
    for code in [None, "", True, -0.1, "nan", "inf", {}]:
      limits = kimi.monthly_limits({"subscriptionBalance": {
        "amountUsedRatio": 0.7, "kimiCodeUsedRatio": code}})
      self.assertEqual([w["title"] for w in limits], ["Monthly total"])
      self.assertEqual(limits[0]["percent"], 0.7)

  def test_zero_code_share_and_nonnegative_kimi_share_follow_website(self):
    for total, code, expected in [(0.7, 0, 0.7), (0, 0, 0), (0.1, 0.2, 0), (1.2, 0.4, 0.8)]:
      limits = kimi.monthly_limits({"subscriptionBalance": {
        "amountUsedRatio": total, "kimiCodeUsedRatio": code}})
      self.assertAlmostEqual(limits[1]["percent"], expected)
      self.assertEqual(limits[2]["percent"], code)

  def test_gifts_other_features_and_missing_totals_are_not_monthly_quotas(self):
    for balance in [None, {}, {"kimiCodeUsedRatio": 0.4},
                    {"amountUsedRatio": 0.5, "type": "GIFT"},
                    {"amountUsedRatio": 0.5, "feature": "FEATURE_CODING"},
                    {"amountUsedRatio": "nan"}]:
      with self.subTest(balance=balance), self.assertRaises(kimi.UsageError):
        kimi.monthly_limit({"subscriptionBalance": balance})

  def test_request_matches_membership_reference_and_stays_in_region(self):
    for base, region in [(kimi.DEFAULT_BASE, "com"), ("https://api.kimi.ai/coding/v1", "ai")]:
      payload = {"subscriptionBalance": {"amountUsedRatio": 0.25}}
      with patch.object(kimi.urllib.request, "build_opener") as build:
        build.return_value.open.return_value = io.BytesIO(json.dumps(payload).encode())
        self.assertEqual(kimi.fetch_monthly(base + "/usages", "synthetic-token")[0]["percent"], 0.25)
        request = build.return_value.open.call_args.args[0]
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertEqual(request.full_url, "https://www.kimi." + region
          + "/apiv2/kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.data, b"{}")
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(headers["authorization"], "Bearer synthetic-token")
        self.assertEqual(headers["cookie"], "kimi-auth=synthetic-token")
        self.assertEqual(headers["origin"], "https://www.kimi." + region)
        self.assertEqual(headers["referer"], headers["origin"] + "/code/console")
        self.assertEqual(headers["connect-protocol-version"], "1")
        self.assertEqual(headers["x-msh-platform"], "web")
        self.assertEqual(build.return_value.open.call_args.kwargs["timeout"], 8)

  def test_unknown_source_cannot_forward_credentials(self):
    with patch.object(kimi.urllib.request, "build_opener") as build:
      with self.assertRaises(KeyError):
        kimi.fetch_monthly("https://example.invalid/usages", "synthetic-token")
      build.assert_not_called()

  def test_fallback_preserves_short_windows(self):
    home = Path(tempfile.mkdtemp(prefix="kimi-monthly-test-"))
    (home / "credentials").mkdir()
    (home / "credentials/kimi-code.json").write_text('{"access_token":"synthetic-token"}')
    short = {"usages": {"limit_5h": {"used_ratio": 0.1}, "limit_7d": {"used_ratio": 0.2}}}
    monthly = kimi.monthly_limit({"subscriptionBalance": {"amountUsedRatio": 0.73}})
    for fallback in [monthly, TimeoutError("synthetic-token")]:
      with patch.object(kimi.urllib.request, "build_opener") as build, patch.object(kimi, "fetch_web", side_effect=TimeoutError()), patch.object(kimi, "fetch_monthly") as fetch, patch.object(kimi, "web_login", return_value="synthetic-web-token"):
        build.return_value.open.return_value = io.BytesIO(json.dumps(short).encode())
        if isinstance(fallback, Exception): fetch.side_effect = fallback
        else: fetch.return_value = [fallback]
        record = kimi.collect(home)
        self.assertEqual([x["percent"] for x in record["limits"][:2]], [0.1, 0.2])
        self.assertEqual(len(record["limits"]), 2 if isinstance(fallback, Exception) else 3)
        self.assertEqual(bool(record["usageStatusText"]), isinstance(fallback, Exception))
        self.assertNotIn("synthetic-token", json.dumps(record))



class UpdaterTests(unittest.TestCase):
  def test_local_discovery_override_filters_and_flags(self):
    root = Path(tempfile.mkdtemp(prefix="kimi-updater-test-"))
    package, local, state = root / "package/bin", root / "local", root / "state"
    package.mkdir(parents=True)
    local.mkdir()
    updater = local / "omarchy-agent-usage-update"
    updater.write_text((ROOT / "bin/omarchy-agent-usage-update").read_text())
    calls = root / "calls"
    for directory, agent, marker in [(package, "codex", "packaged"), (local, "codex", "override"),
                                      (local, "kimi", "local-kimi"), (package, "claude", "packaged-claude")]:
      path = directory / ("omarchy-agent-usage-" + agent)
      path.write_text('#!/bin/bash\nprintf "%s %s\\n" "' + marker + '" "$*" >> "$TEST_CALLS"\n'
                      + 'printf \'{"id":"' + agent + '"}\\n\'\n')
      path.chmod(0o755)
    env = {**os.environ, "OMARCHY_PATH": str(package.parent), "XDG_STATE_HOME": str(state), "TEST_CALLS": str(calls)}
    subprocess.run(["bash", str(updater), "--force", "--except", "claude"], env=env, check=True)
    self.assertCountEqual(calls.read_text().splitlines(), ["override --force", "local-kimi --force"])
    self.assertEqual(sorted(p.name for p in (state / "omarchy/agents/usage").glob("*.json")), ["codex.json", "kimi.json"])
    subprocess.run(["bash", str(updater), "--limits-only", "kimi"], env=env, check=True)
    self.assertEqual(calls.read_text().splitlines()[-1], "local-kimi --limits-only")


@unittest.skipUnless(shutil.which("qs"), "Quickshell is required for the QML integration test")
class PanelTests(unittest.TestCase):
  def test_quickshell_discovery_status_and_icon(self):
    root = Path(tempfile.mkdtemp(prefix="kimi-qml-test-"))
    plugin, state, runtime = root / "plugin", root / "state", root / "runtime"
    plugin.mkdir()
    runtime.mkdir(mode=0o700)
    for name, source in [("Main.qml", ROOT / "Main.qml"),
                         ("Agent.qml", ROOT / "Agent.qml"),
                         ("kimi.svg", ROOT / "assets/kimi.svg")]:
      (plugin / name).write_bytes(source.read_bytes())
    (plugin / "bin").mkdir()
    (plugin / "bin/omarchy-agent-usage-update").write_text("#!/bin/bash\nexit 0\n")
    usage = state / "omarchy/agents/usage"
    usage.mkdir(parents=True)
    (usage / "kimi.json").write_text(json.dumps({
      "id": "kimi", "name": "Kimi Code", "ready": True,
      "hasLocalStats": False, "usageStatusText": "Kimi login required", "limits": [],
    }))
    (root / "shell.qml").write_text('''
import QtQuick
import Quickshell
import "plugin"
ShellRoot {
  Main { id: usage }
  Image { id: mark; source: "plugin/kimi.svg" }
  Timer {
    interval: 1500; running: true
    onTriggered: {
      var list = usage.enabledProviders
      if (list.length !== 1 || list[0].providerId !== "kimi"
          || list[0].usageStatusText !== "Kimi login required"
          || list[0].hasLocalStats !== false || mark.status !== Image.Ready)
        throw new Error("Kimi status or icon failed")
      var available = usage.displayProvider({ id: "kimi", ready: true,
        limits: [{ label: "Monthly Code", title: "Monthly Code", percent: 0.42 }] })
      if (!usage.providerHasData(available) || available.limits[0].percent !== 0.42)
        throw new Error("Kimi limits failed")
      if (usage.providerHasData(usage.displayProvider({id: "kimi", ready: false})))
        throw new Error("Unconfigured Kimi must remain hidden")
      if (usage.providerHasData(usage.displayProvider({id: "codex", ready: true, usageStatusText: "offline"})))
        throw new Error("Codex visibility changed")
      console.log("KIMI_QML_OK")
      Qt.quit()
    }
  }
}
''')
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "generic",
           "QT_QUICK_BACKEND": "software", "XDG_STATE_HOME": str(state),
           "XDG_CACHE_HOME": str(root / "cache"), "XDG_RUNTIME_DIR": str(runtime)}
    result = subprocess.run(["qs", "--no-color", "-p", str(root)], env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=12)
    self.assertEqual(result.returncode, 0, result.stdout)
    self.assertIn("KIMI_QML_OK", result.stdout)


if __name__ == "__main__":
  unittest.main()
