# Kimi protocol notes

Protocol comparison date: 2026-11-03. These are website/client implementation
details, not a stability guarantee for a public developer interface.

## Public references

- [Kimi console](https://www.kimi.com/code/console).
- [Website authentication implementation](https://statics.moonshot.cn/kimi-web/assets/c13feaf26e309-DanGvpez.js).
- [Website host constants](https://statics.moonshot.cn/kimi-web/assets/c06ce49e90813-CNEMg2ev.js).
- [Website balance mapping](https://statics.moonshot.cn/kimi-web/assets/c25eb991e4b24-BHwmR3lX.js).
- [CodexBar Kimi requests](https://github.com/steipete/CodexBar/blob/main/Sources/CodexBarCore/Providers/Kimi/KimiUsageFetcher.swift)
  and [response models](https://github.com/steipete/CodexBar/blob/main/Sources/CodexBarCore/Providers/Kimi/KimiModels.swift).
- [Moonshot AI Kimi Code](https://github.com/MoonshotAI/kimi-code).

## Requests and authentication

| Purpose | Request | Body |
|---|---|---|
| Short windows | POST `https://www.kimi.com/apiv2/kimi.gateway.billing.v1.BillingService/GetUsages` | `{"scope":["FEATURE_CODING"]}` |
| Monthly pool | POST `https://www.kimi.com/apiv2/kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats` | `{}` |
| Website renewal | POST `https://auth.kimi.com/api/account.gateway.v1.AuthService/RefreshToken` | `{"refresh_token":"<private value>"}` |
| Code fallback | GET configured `https://api.kimi.com/coding/v1/usages` or `.ai` equivalent | None |

Website usage authenticates with its own region's website access token in
Bearer authorization and the `kimi-auth` cookie. Requests use JSON, Connect
protocol version 1, matching origin/referrer, web platform, language, timezone
and browser user-agent fields. Optional identity fields map `device_id` to
`x-msh-device-id`, `ssid` to `x-msh-session-id`, and `sub` to `x-traffic-id`.
The current client metadata uses English and Asia/Hong_Kong.

Renewal sends the refresh token in the JSON body, without an access bearer
header or cookie. It validates and retains both returned credentials in a
private cache. Dynamic website shield metadata is not synthesized. Requests
reject redirects and have an eight-second timeout. `.ai` usage stays on its
own region; no international renewal host is guessed.

## Quota semantics

`FEATURE_CODING.detail` supplies weekly counters; only a five-hour limit is
labeled Session. Counters use `used / limit`, or valid remaining counters when
used is absent. Code fallback preserves short windows if website data is missing.

`subscriptionBalance.amountUsedRatio` is the shared monthly total.
`kimiCodeUsedRatio` is the Code contribution to that same total; the website
computes the non-Code Kimi contribution as `max(total - code, 0)`.
Both contributions use the full monthly pool as denominator. Missing/invalid
breakdown fields omit the share rows while retaining a valid total. These are
not separate monthly allowances. No Kimi chat five-hour or weekly quota is
fabricated from Code's limits.

## Browser and renewal boundaries

Only the matching Kimi origin in Chromium Default is read. The reader follows
active LevelDB manifests, sequence numbers, tombstones and checksums. It rejects
changing or symlinked profiles. The website and configured Code subjects must
match, even if an expired Code access token is used only to establish identity.
An expired access token cannot authorize a website usage request.

The independent cache is bound to the source browser credential pair. Browser
logout/deletion, changed source credentials or account/region mismatch prevents
reuse. A file lock serializes refresh, writes are atomic, and each collection
makes at most one renewal attempt. Browser and Code credential files remain
read-only. Credentials must never appear in logs or usage records.

The source installation verified successful token rotation and immediate cache
reuse. Long-term concurrent browser/plugin renewal remains unverified, and an
expired or revoked refresh token requires another website login. Tests in this
repository use synthetic payloads exclusively.
