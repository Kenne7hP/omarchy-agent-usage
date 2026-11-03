# Omarchy Agent Usage

An Omarchy Agents panel derivative with Kimi website quota and Codex account
usage extensions. Keep the existing Python standard library, Bash and QML stack.

## Structure and naming

- Root `manifest.json`, `Main.qml`, `Panel.qml`, `Agent.qml`: installable plugin.
- `bin/`: executable collectors/updater and their Python helpers, under their
  existing runtime names.
- `assets/`: runtime SVG icons; record their provenance in `CREDITS.md`.
- `tests/test_*.py`: synthetic unit and isolated QML regression tests.
- `docs/`: protocol and compatibility notes, using descriptive kebab-case names.
- `licenses/`: unmodified third-party license texts, named after each project.
- `README.md`: features, requirements, installation and operation.
- `CREDITS.md`, `LICENSE`: provenance and redistribution terms.
- `ROADMAP.md`: actual project progress and latest verification.
- Temporary build/test artifacts belong in `/tmp`; do not copy local backups,
  browser profiles, credentials, usage records or personal maintenance logs here.

## Boundaries

- Preserve Omarchy's copyright and license. Attribute upstream work clearly.
- Change only what packaging and the two usage extensions require.
- Keep account tokens distinct from local/device counts. Missing data is not zero.
- Kimi monthly total and Kimi/Code contributions share the same denominator.
- Read only the configured Kimi account and exact matching Chromium origin.
  Never edit browser or Code credentials. Renewal may write only the documented
  private credential cache (directory 0700, files 0600), never the repository.
- No credentials, raw account responses, prompts, conversations or personal
  machine paths in source, examples, logs, tests or screenshots.
- Tests must use synthetic data and must not invoke live collectors or logins.
- Do not modify the installed desktop or package-owned Omarchy files as part
  of repository work. Public publication requires the owner's final approval.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v`
- `bash -n bin/omarchy-agent-usage-update`
- `omarchy plugin validate .`
- QML tests skip with an explicit reason if their runtime is unavailable.
  Full verification requires Quickshell and an Omarchy Wayland desktop.
- Verify a fresh temporary copy with the same checks; inspect package contents
  for credentials, local paths, caches and backups before publication.
- Update `ROADMAP.md` after implementation and verification. Mark only checked
  outcomes done; keep live compatibility and publication limitations explicit.
