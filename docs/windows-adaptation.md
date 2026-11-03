# Windows adaptation proposal

**Status: feasibility assessment only. Windows support is not implemented or
verified, and no Windows executable is available.** The current release requires
Omarchy on Linux. This document describes a proposed Windows version, not an
installation guide or a committed delivery schedule.

**中文摘要：** 可以做成 Windows 托盘应用，点击右下角图标查看 Kimi / Codex
用量。现有额度计算和数据解析可以复用；桌面界面、浏览器登录读取、凭据存储、
文件锁及程序启动需要适配。建议评估 Python + PySide6，最终必须在 Windows
实机验证登录、自动刷新和打包运行。目前仅完成方案评估，尚未开发 Windows 版。

## Proposed experience and first-version scope

- A system-tray icon opens a compact Kimi / Codex usage panel.
- Automatic refresh and manual refresh retain the existing quota semantics.
- Kimi shows Session, Weekly, Monthly total, Monthly Kimi share and Monthly
  Code share when available. All monthly rows use the same shared pool.
- Codex shows subscription limits and seven days of account token usage,
  separately from the three-day local usage chart. Missing data remains distinct
  from reported zero.
- Distribute a Windows executable with its required runtime bundled.

Keep the first version focused on these existing Kimi / Codex features. Porting
other providers or device aggregation is outside the proposed first-version
scope. Preserve the working Omarchy plugin while evaluating a separate Windows
entry point that shares the provider logic.

## Reuse and platform work

The assessment inspected the current collectors and authentication helpers.

| Component | Reusable behavior | Windows work |
|---|---|---|
| Quota and account parsing | Counter normalization, monthly breakdown, date selection, missing-value handling | Retain semantics and run the synthetic tests on Windows |
| Desktop panel | Existing layout and display concepts | Replace Omarchy and Quickshell-specific components with a Windows tray/window interface |
| Refresh orchestration | Refresh cadence and provider selection | Replace the Bash updater with a portable scheduler and process handling |
| Kimi browser login | Exact-origin/account checks and session-renewal logic | Locate and validate Windows browser profiles; test Chrome / Edge storage access and login matching |
| Kimi credential cache | Source-login binding, serialized refresh and atomic updates | Replace Unix owner/mode checks and file locking with Windows-appropriate protection and synchronization |
| Browser storage decompression | LevelDB parsing and validation | Replace the hard-coded `libsnappy.so.1` dependency with a Windows-compatible implementation or packaged library |
| Codex collection | Existing app-server requests and result mapping | Verify executable discovery, process launch, login availability and local data paths on Windows |
| Packaging | Provider assets, notices and documentation | Build a Windows executable, include dependencies and required notices, and test the distributed artifact |

Concrete Linux dependencies include `fcntl.flock`, `os.getuid`,
`os.O_NOFOLLOW`, Unix permission checks, Linux data directories and
`libsnappy.so.1`. Changing paths alone does not address them. Windows credential
protection must be designed explicitly; Unix `0700` / `0600` checks cannot simply
be treated as equivalent protection on Windows.

Chrome / Edge support is a target for investigation, not a confirmed capability.
Browser storage access, concurrent browser activity and session renewal must be
tested on the selected Windows/browser versions. Existing `.ai` automatic-renewal
limitations remain until its protocol is separately verified.

## Suggested implementation approach

**Python + PySide6** is the preferred candidate because the collectors already
use Python. It would preserve the data-processing logic while providing a new
tray/window interface. PySide6 is an additional dependency and would increase
the distribution size; adopting it requires a separate implementation decision.

Qt documents Windows support for
[`QSystemTrayIcon`](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html)
and [Qt for Python deployment](https://doc.qt.io/qtforpython-6.11/deployment/index.html).
Those capabilities establish a viable interface and packaging route, not proof
that this particular application works on Windows. The current panel also imports
Omarchy components and uses [Quickshell](https://quickshell.org/), so its desktop
integration must be adapted even if portions of the visual design are retained.

Before implementation, update repository guidance to define the shared provider
code, platform-specific components, dependencies and build/test conventions.
Retain Omarchy attribution and applicable third-party license notices.

## Required Windows acceptance checks

1. Build and run the packaged application on the declared Windows version and
   architecture without relying on the development machine's Python setup.
2. Verify tray activation, panel rendering, automatic/manual refresh and clean
   shutdown, with no unintended console windows.
3. Check Codex discovery and existing login, subscription limits, account usage
   and local statistics. A failed account query must preserve valid limits;
   account totals must remain separate from local totals.
4. Check Kimi profile selection and matching-account access. Verify initial login,
   expiry, renewal, restart/cache reuse, logout and account-switch handling while
   the browser is both open and closed. Never modify its or Code's credentials.
5. Verify credential protection and concurrent refresh behavior. Confirm no
   credentials or raw account responses enter logs, usage records or packages.
6. Test offline, missing-login and unsupported-version states. Run portable
   synthetic regressions and confirm that the existing Omarchy version still
   passes its own checks.

**The largest unverified area is Kimi browser-session access and renewal on
Windows.** Real Windows testing is required before claiming support. Current
Linux test results do not establish Windows compatibility. Track implementation
and verification progress in [ROADMAP.md](../ROADMAP.md).
