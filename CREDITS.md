# Credits and provenance

## Omarchy

Based on **Omarchy's Agents panel by David Heinemeier Hansson and the Omarchy
contributors**, copyright David Heinemeier Hansson, MIT license.

- Upstream: <https://github.com/omacom/omarchy>
- Panel: <https://github.com/omacom/omarchy/tree/quattro/shell/plugins/agents>
- Original license: [licenses/omarchy.txt](licenses/omarchy.txt)

The baseline is the installed Omarchy package **4.0.6-1**, not the moving head
of `quattro`. `Main.qml`, `Panel.qml`, `Agent.qml`, the manifest, updater, Codex
collector and Claude/Codex/Fireworks SVG assets derive from that package.
The installed package did not supply a source commit identifier; no exact
commit correspondence is claimed. Current upstream has evolved since this
baseline and already contains its own Kimi collector.

## Extensions and packaging

**Ken (@Kenne7hP)**: Kimi website quota collection and monthly shared-pool
breakdown, independent website session renewal and scoped browser reader,
Codex account usage integration, panel additions, tests and standalone package.
These additions are also distributed under MIT.

`assets/kimi.svg` is an original, plain letter-K marker for this package, not
an extracted Kimi application icon. Other provider marks are retained from the
Omarchy baseline; their product names and marks belong to their respective
owners. No endorsement is implied by inclusion.

## Implementation references

- **CodexBar**, Peter Steinberger, MIT: public Kimi request and response
  implementation used to compare usage fields, headers and authentication.
  [Source](https://github.com/steipete/CodexBar/tree/main/Sources/CodexBarCore/Providers/Kimi)
  · [license notice](licenses/codexbar.txt).
- **Kimi Code**, Moonshot AI, MIT: public provider configuration and credential
  resolution implementation used to check account selection and usage mapping.
  [Source](https://github.com/MoonshotAI/kimi-code)
  · [license notice](licenses/kimi-code.txt).
- **Kimi website**, Moonshot AI: publicly served client code used to verify
  request fields, refresh behavior and the monthly split formula. Source links
  are recorded in [the protocol notes](docs/kimi-protocol.md). Website bundles
  and copied TypeScript reference files are not included in this repository.
- **OpenAI Codex app-server**: the installed protocol schema and official
  account usage documentation informed the account request and field mapping.
  [Protocol notes](docs/codex-account-usage.md).

Reference credits describe how the implementations were checked; they do not
claim that this package is an official client of any service. Third-party MIT
notices are retained separately from this project's license.
