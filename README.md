# Omarchy Agent Usage

Kimi website quota details and Codex account daily tokens in Omarchy's native
Agents panel. A community derivative of [Omarchy](https://github.com/omacom/omarchy),
with extensions by [Ken (@Kenne7hP)](https://github.com/Kenne7hP).

在 Omarchy 原生 Agents 面板中查看 Kimi 官网额度及月度 Kimi / Code 分项，
以及 Codex 账户每日 token（模型计量单位）用量。基于原作者面板扩展，非官方插件。

## What it adds

- **Kimi:** website-first refresh with independent session renewal for `.com`;
  Session, Weekly, Monthly total, Monthly Kimi share and Monthly Code share.
  All monthly percentages use the **same shared monthly pool**. The Kimi share
  means non-Code membership usage, not exclusively chat. No separate Kimi chat
  short-window allowance is inferred.
- **Codex:** seven days of account token usage, separate from local and synced
  device totals. Missing days show **—**, reported zero shows **0**. The local
  chart shows three days while retaining the underlying statistics.
- Existing Omarchy agent discovery, quota meters, manual refresh and optional
  device aggregation remain available. Default refresh interval: 15 minutes.

Current upstream Omarchy already supports Kimi. This derivative packages the
website monthly breakdown and Codex account display from a **4.0.6** baseline;
it is not a replacement for every subsequent upstream improvement.

## Requirements and compatibility

- Omarchy **4.0.6** with its Quickshell shell and `qs.Commons` / `qs.Ui` components.
  Newer Omarchy versions have not been verified with this package.
- Python **3.11+**, Bash, `jq`, and `libsnappy.so.1` (Arch's `snappy` package).
  Verification used Python 3.14. These are runtime prerequisites, not bundled
  dependencies; no Python packages are required.
- Codex account display was checked against **Codex 0.166.0** and uses its
  existing app-server login. Unsupported account-usage requests leave quota
  bars intact. Service reporting delay and day-boundary timezone are unspecified.
- Kimi needs an existing **file-backed Kimi Code login** and a matching website
  account in **Chromium's Default profile**. Chrome, other profiles and keyring
  credential storage are not supported. `.ai` supports fresh website sessions,
  but automatic renewal is implemented only for `.com`.

## Install

The repository root is the plugin package; no build or separate installer is
needed. Review the source before enabling it:

```bash
omarchy plugin add https://github.com/Kenne7hP/omarchy-agent-usage.git
```

When prompted to enable it immediately, choose **No** and switch widgets below.

Use **one Agents widget at a time**: both this plugin and the built-in widget
write to Omarchy's shared usage directory. Disable your currently active Agents
widget before enabling this one. For the stock widget:

```bash
omarchy plugin disable omarchy.agents
omarchy plugin enable kenne7hp.agents --section right
```

If you use a personal clone, find its identifier with `omarchy plugin list` and
disable that identifier instead. Keep the old plugin installed so you can switch
back. Adding this package does not migrate a previous clone's settings.

For a local checkout, `omarchy plugin validate .` validates the package without
installing it.

To switch back to the stock widget:

```bash
omarchy plugin disable kenne7hp.agents
omarchy plugin enable omarchy.agents
```

For a previous personal clone, enable its identifier instead of the stock one.
The next refresh replaces cached usage records; disabling a plugin does not
delete credential caches or collected statistics.

## Use and settings

Click the bar icon to open the panel; use its refresh action or press `r` in the
popup. Opening it also refreshes quota/account data. A provider must be configured
and have displayable data to appear. Configured Kimi accounts remain visible
when login or network errors prevent collection.

Set the refresh interval, in seconds:

```bash
omarchy bar set kenne7hp.agents refreshIntervalSec 900 --json
```

Provider switches are one object, not dotted setting keys. To display only Kimi
and Codex on the tested baseline:

```bash
omarchy bar set kenne7hp.agents providers '{"kimi":{"enabled":true},"codex":{"enabled":true},"claude":{"enabled":false},"fireworks":{"enabled":false}}' --json
```

Other discovered providers are enabled unless explicitly disabled. The updater
prefers bundled Kimi/Codex collectors and uses other collectors from
`$OMARCHY_PATH/bin` (normally configured by Omarchy).

Optional device aggregation is inherited from Omarchy and defaults to **Off**.
Enabling it writes aggregate usage snapshots to the chosen sync folder.
Codex account tokens are excluded from those device snapshots to avoid double
counting. Treat usage statistics and device names as personal data.

## Data access and limitations

The Kimi collector reads the configured Code credential to match the website
account. It reads only matching Kimi-origin credentials from Chromium Default
and does not modify browser or Code credentials. The collector sends usage and
renewal requests to verified Kimi hosts; it sends no prompts or workspace content.

Renewed website credentials are stored separately at
`$KIMI_CODE_HOME/credentials/omarchy-usage/session.json`, defaulting to
`~/.kimi-code/credentials/omarchy-usage/session.json`. The directory is private
(0700), files are private (0600), and refresh is serialized. Never commit or share
this cache. Browser logout, changed credentials or an account mismatch invalidates
its binding to the browser login.

Renewal and immediate cache reuse were verified in the original installation.
Long-term concurrent browser/plugin renewal is **unverified**; the service may
invalidate a session and require another website login. Website endpoints and
browser storage formats can change. Details: [Kimi protocol](docs/kimi-protocol.md).

The Codex collector asks the existing app-server for account usage. Inherited
local statistics also read local Codex, pi/omp and opencode session metadata.
The panel's query time is **not** a service data cutoff or a guarantee of today's
complete total. See [Codex account usage](docs/codex-account-usage.md).

## Verify

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
bash -n bin/omarchy-agent-usage-update
omarchy plugin validate .
```

Tests use synthetic credentials and account data. They do not call live usage
services. Two QML integration tests require Quickshell; the full-panel test also
needs Omarchy components and a Wayland session. Missing runtime prerequisites
produce explicit skips, which do not establish desktop compatibility. Browser
compression tests need the Snappy runtime library.

See [ROADMAP.md](ROADMAP.md) for verified results and remaining work.

## Credit and license

Based on Omarchy's Agents panel by David Heinemeier Hansson and the Omarchy
contributors. Kimi website quota integration and Codex account usage extensions
by Ken (@Kenne7hP).

Distributed under the [MIT license](LICENSE). Original copyright and permission
notices are retained. See [CREDITS.md](CREDITS.md) for component provenance and
protocol references. This project is not affiliated with Omarchy, Moonshot AI
or OpenAI; product names identify the supported services.
