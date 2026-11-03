# Roadmap

## Current phase

Standalone plugin package verified locally; publishing the first public version.

## Done

- Reviewed the existing extensions and upstream license.
- Assembled the latest shared panel, two collectors and authentication helpers
  under plugin id `kenne7hp.agents`, version `0.1.0`.
- Added installation instructions, compatibility/protocol notes, original
  copyright notices, reference credits and an original letter-K marker.
- Removed dependencies on personal staging/installed-plugin paths in the
  packaged tests. Personal backups, reference snapshots and credentials were
  never copied into this repository.
- Verified all 55 packaged tests, including both QML integration checks, with
  synthetic data. The personal snapshot-restoration test is not included because
  that local maintenance tool is not part of the distributed plugin.
- Verified a fresh temporary copy: all 55 tests, Bash syntax and Omarchy's
  native plugin validator passed.
- Scanned all 29 distributable files for personal paths and common credential
  formats; no matches. Checked Python syntax, local documentation links and
  executable collector permissions.
- Confirmed collector/helper bytes match the working installation and the
  installed source files remain unchanged.
- Initialized a local Git repository on `main`.
- Owner approved publication to `Kenne7hP/omarchy-agent-usage` on 2026-11-03.
- Created the public repository at
  <https://github.com/Kenne7hP/omarchy-agent-usage>.

## In progress

- Publishing the approved package to GitHub.

## Todo

- Upload and verify the public repository contents.
- Verify native Git-based installation after a remote repository exists.

## Blockers and limits

- Current desktop behavior is based on Omarchy 4.0.6; newer upstream versions
  already include Kimi and need a separate compatibility review.
- Long-term concurrent Kimi browser/plugin token renewal remains unverified.
- International Kimi website session renewal is not implemented.
- No new live credential or usage requests were made during packaging.
- Full desktop checks need Wayland socket access. The initial sandboxed test
  was blocked by the sandbox; the isolated test passed with that access allowed.

## Latest verification

- 2026-11-03: 55 tests passed with zero skips in both the repository and a fresh
  temporary copy. Native manifest validation, Bash/Python syntax, package scan
  and source-integrity checks passed. No installation or public upload performed.
