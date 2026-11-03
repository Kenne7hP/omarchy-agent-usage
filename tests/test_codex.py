import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
  loader = importlib.machinery.SourceFileLoader(name, str(path))
  spec = importlib.util.spec_from_loader(name, loader)
  module = importlib.util.module_from_spec(spec)
  loader.exec_module(module)
  return module


codex = load("codex_usage", ROOT / "bin/omarchy-agent-usage-codex")
NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone(timedelta(hours=8)))


class AccountUsageTests(unittest.TestCase):
  def test_today_and_latest_selected_by_date_not_order(self):
    result = codex.account_usage_record({"dailyUsageBuckets": [
      {"startDate": "2026-11-03", "tokens": 1234567},
      {"startDate": "2026-11-01", "tokens": 100},
    ]}, NOW)
    self.assertEqual(result["todayTokens"], 1234567)
    self.assertEqual(result["latestDate"], "2026-11-03")
    self.assertEqual(result["status"], "available")
    self.assertEqual(result["queriedAt"], NOW.isoformat())

  def test_yesterday_is_not_today_or_zero(self):
    result = codex.account_usage_record({"dailyUsageBuckets": [
      {"startDate": "2026-11-02", "tokens": 500},
    ]}, NOW)
    self.assertIsNone(result["todayTokens"])
    self.assertEqual(result["latestDate"], "2026-11-02")
    self.assertEqual(result["latestTokens"], 500)
    self.assertEqual(result["status"], "pending")

  def test_zero_is_valid_only_when_reported(self):
    result = codex.account_usage_record({"dailyUsageBuckets": [
      {"startDate": "2026-11-03", "tokens": 0},
    ]}, NOW)
    self.assertEqual(result["todayTokens"], 0)
    self.assertEqual(result["status"], "available")

  def test_recent_days_preserve_zero_and_gaps_within_seven_day_window(self):
    result = codex.account_usage_record({"dailyUsageBuckets": [
      {"startDate": "2026-11-02", "tokens": 500},
      {"startDate": "2026-10-27", "tokens": 999},
      {"startDate": "2026-10-28", "tokens": 0},
      {"startDate": "2026-11-04", "tokens": 999},
    ]}, NOW)
    self.assertEqual(result["recentDays"], [
      {"date": "2026-10-28", "messageCount": 0},
      {"date": "2026-11-02", "messageCount": 500},
    ])
    self.assertIsNone(result["todayTokens"])

  def test_missing_and_malformed_data_stays_unavailable(self):
    for response in (None, {}, [], {"dailyUsageBuckets": None}, {"dailyUsageBuckets": {}}):
      with self.subTest(response=response):
        result = codex.account_usage_record(response, NOW)
        self.assertIsNone(result["todayTokens"])
        self.assertIsNone(result["latestTokens"])
        self.assertEqual(result["status"], "unavailable")
    result = codex.account_usage_record({"dailyUsageBuckets": [
      None, {"startDate": "2026-11-03", "tokens": True},
      {"startDate": "2026-11-03", "tokens": -1},
      {"startDate": "2026-11-03", "tokens": "123"},
      {"startDate": "2026-02-30", "tokens": 100},
    ]}, NOW)
    self.assertIsNone(result["todayTokens"])
    self.assertEqual(result["latestDate"], "")

  def test_midnight_uses_new_local_calendar_label(self):
    now = datetime(2026, 11, 4, 0, 1, tzinfo=NOW.tzinfo)
    result = codex.account_usage_record({"dailyUsageBuckets": [
      {"startDate": "2026-11-03", "tokens": 900},
    ]}, now)
    self.assertEqual(result["date"], "2026-11-04")
    self.assertIsNone(result["todayTokens"])
    self.assertEqual(result["latestDate"], "2026-11-03")

  def fetch(self, fail_usage=False):
    proc = Mock(stdin=io.StringIO(), stdout=io.StringIO())
    requests = []
    def reply(proc, messages, request_id, method, params=None, timeout=15):
      requests.append((method, params))
      if method == "account/read":
        return {"result": {"account": {"planType": "pro"}}}
      if method == "account/rateLimits/read":
        return {"result": {"rateLimits": {
          "primary": {"usedPercent": 25, "windowDurationMins": 300},
          "secondary": {"usedPercent": 50, "windowDurationMins": 10080},
        }}}
      if method == "account/usage/read":
        if fail_usage:
          raise TimeoutError("Synthetic failure must not leak into the panel")
        return {"result": {"dailyUsageBuckets": []}}
      return {"result": {}}
    with patch.object(codex, "find_command", return_value="/synthetic/codex"), \
         patch.object(codex.subprocess, "Popen", return_value=proc), \
         patch.object(codex, "rpc_request", side_effect=reply):
      result = codex.fetch_codex_rpc()
    proc.terminate.assert_called_once()
    return result, requests

  def test_account_query_does_not_request_a_thread(self):
    result, requests = self.fetch()
    self.assertIn(("account/usage/read", None), requests)
    self.assertEqual(result["accountUsage"]["status"], "pending")
    self.assertEqual(result["tierLabel"], "pro")

  def test_usage_failure_preserves_limits_and_local_stats(self):
    before = codex.local_stats()
    result, _ = self.fetch(fail_usage=True)
    self.assertEqual([w["percent"] for w in result["limits"]], [0.25, 0.5])
    self.assertEqual(result["usageStatusText"], "")
    self.assertEqual(result["accountUsage"]["status"], "requestFailed")
    self.assertTrue(result["accountUsage"]["queriedAt"])
    self.assertNotIn("Synthetic", json.dumps(result))
    self.assertEqual(codex.local_stats(), before)


@unittest.skipUnless(shutil.which("qs") and os.environ.get("WAYLAND_DISPLAY")
                     and Path("/usr/share/omarchy/shell/Ui").is_dir(),
                     "Full panel test requires Quickshell and an Omarchy Wayland desktop")
class QmlTests(unittest.TestCase):
  def test_real_panel_account_display_and_device_separation(self):
    root = Path(tempfile.mkdtemp(prefix="codex-qml-test-"))
    plugin, state = root / "plugin", root / "state"
    plugin.mkdir()
    for name in ("Main.qml", "Panel.qml"):
      shutil.copy2(ROOT / name, plugin / name)
    shutil.copy2(ROOT / "Agent.qml", plugin / "Agent.qml")
    (plugin / "assets").symlink_to(ROOT / "assets", target_is_directory=True)
    for name in ("Commons", "Ui"):
      (root / name).symlink_to(Path("/usr/share/omarchy/shell") / name, target_is_directory=True)
    (plugin / "bin").mkdir()
    (plugin / "bin/omarchy-agent-usage-update").write_text("#!/bin/bash\nexit 0\n")
    usage = state / "omarchy/agents/usage"
    usage.mkdir(parents=True)
    (usage / "codex.json").write_text(json.dumps({
      "id": "codex", "name": "Codex", "ready": True, "todayTotalTokens": 42,
      "limits": [{"label": "5h window", "percent": 0.25}],
      "accountUsage": {"date": "2026-11-03", "todayTokens": 1234567,
        "latestDate": "2026-11-03", "latestTokens": 1234567,
        "recentDays": [{"date": "2026-11-02", "messageCount": 0},
                       {"date": "2026-11-03", "messageCount": 1234567}],
        "queriedAt": NOW.isoformat(), "status": "available"},
    }))
    (root / "shell.qml").write_text('''
import QtQuick
import Quickshell
import "plugin" as Agents
ShellRoot {
  Agents.Main { id: usage }
  Agents.Panel { id: panel }
  Timer {
    interval: 1500; running: true
    onTriggered: {
      panel.nowMs = new Date(2026, 10, 3, 18, 0, 0).getTime()
      if (!panel.provider || panel.provider.providerId !== "codex")
        throw new Error("Codex panel did not load")
      var days = panel.accountDays()
      if (days.length !== 7 || days[0].date !== "2026-10-28"
          || days[0].messageCount !== null || days[5].messageCount !== 0
          || days[6].messageCount !== 1234567)
        throw new Error("Account seven-day chart lost dates, missing data, or zero")
      if (panel.accountDayTooltip(days[0]).indexOf("Not reported") < 0
          || panel.accountDayTooltip(days[5]).indexOf("0 tokens") < 0)
        throw new Error("Missing and zero tooltips are indistinguishable")
      if (panel.accountQueryText().indexOf("Queried") < 0
          || panel.accountQueryTooltip().indexOf("not the data cutoff") < 0)
        throw new Error("Query time missing")
      var record = {id: "codex", ready: true, todayTotalTokens: 42,
        accountUsage: {date: "2026-11-03", todayTokens: 1000}}
      usage.syncEnabled = true
      usage.syncDir = "/synthetic-unused"
      usage.aggregateData = {deviceCount: 2, providers: {codex: {todayTotalTokens: 84}}}
      var display = usage.displayProvider(record)
      if (display.todayTotalTokens !== 84 || display.accountUsage.todayTokens !== 1000)
        throw new Error("Account usage got merged with device totals")
      if (usage.providerSnapshot(record).accountUsage !== undefined)
        throw new Error("Account data leaked into device snapshots")
      if (usage.displayProvider({id: "kimi", ready: true}).accountUsage !== null)
        throw new Error("Kimi account behavior changed")
      panel.nowMs = new Date(2026, 10, 4, 0, 1, 0).getTime()
      days = panel.accountDays()
      if (days[6].date !== "2026-11-04" || days[6].messageCount !== null
          || days[5].date !== "2026-11-03" || days[5].messageCount !== 1234567)
        throw new Error("Midnight displayed yesterday as today")
      console.log("CODEX_PANEL_OK")
      Qt.quit()
    }
  }
}
'''.replace("/synthetic-unused", str(root / "sync")))
    # PanelWindow needs Wayland; an offscreen platform cannot instantiate the
    # real KeyboardPanel. This isolated instance stays closed and uses only
    # synthetic state and a no-op collector.
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700)
    display = Path(os.environ["WAYLAND_DISPLAY"])
    if not display.is_absolute():
      display = Path(os.environ["XDG_RUNTIME_DIR"]) / display
    env = {**os.environ, "QT_QPA_PLATFORM": "wayland", "QT_QPA_PLATFORMTHEME": "generic",
           "QT_QUICK_BACKEND": "software", "XDG_STATE_HOME": str(state),
           "XDG_CACHE_HOME": str(root / "cache"), "XDG_RUNTIME_DIR": str(runtime),
           "WAYLAND_DISPLAY": str(display)}
    result = subprocess.run(["qs", "--no-color", "-p", str(root)], env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=12)
    self.assertEqual(result.returncode, 0, result.stdout)
    self.assertIn("CODEX_PANEL_OK", result.stdout)
    for error in ("ReferenceError", "TypeError", "SyntaxError", "Failed to load configuration"):
      self.assertNotIn(error, result.stdout)


if __name__ == "__main__":
  unittest.main()
