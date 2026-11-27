# DeHashed v2 API — endpoint reference

Reference retained from the existing custom client. Examples are illustrative;
account observations and credentials are excluded. Query syntax lives in `SEARCH-SYNTAX.md`.

Base URL: `https://api.dehashed.com`

Authentication: `Dehashed-Api-Key: <key>` — the only documented auth header.

Rate limit: **20 requests/second** per IP and credential. Exceeding it returns
HTTP 429 `{"error":"too many requests"}`. Repeated violations or proxy
circumvention can suspend the account. The helper script self-limits to
~16 req/s and backs off on 429.

---

## 1. Entitlement

`GET /v2/info/user` (free) is the authoritative pre-flight check:

```json
{"search_access": true, "search_credits": 100, "whois_credits": 0}
```

| Field | Meaning |
| --- | --- |
| `search_access` | `false` ⇒ every `/v2/search` returns 401 regardless of credits |
| `search_credits` | spendable only when `search_access` is true |
| `whois_credits` | `0` ⇒ every `/v2/whois/*` call fails |

A high credit balance does not imply access. An account can hold credits with no
active search subscription. This is a billing state, not a header problem.

**Verified negative:** adding `Dehashed-Email`, `Dehashed-User`, `X-Dehashed-Email`,
`Email`, `Dehashed-Account`, `From` or `X-Api-User` does not change entitlement.
Ten variants all returned the same 401. Set `DEHASHED_CONTACT_EMAIL` only if you
want to be identifiable to DeHashed.

Account entitlements and balances are private runtime state. Inspect them with
`status` when an actual lookup is requested; do not publish account snapshots.

---

## 2. POST /v2/search

Cost: **1 credit per request**, including each pagination page and pages with
zero results.

| Parameter | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `query` | string | yes | – | `field:value` grammar, `&` = AND |
| `page` | integer | no | 1 | |
| `size` | integer | no | 100 | 1–10,000 |
| `regex` | boolean | no | false | mutually exclusive with `wildcard` |
| `wildcard` | boolean | no | false | mutually exclusive with `regex` |
| `de_dupe` | boolean | no | false | removes repeated records across sources |

Response:

```json
{
  "balance": 99,
  "entries": [
    {
      "id": "<record-id>",
      "email": ["test@example.com"],
      "ip_address": ["127.0.0.1"],
      "username": ["username@example.com"],
      "password": ["<recovered-password>"],
      "hashed_password": ["<hash>:<salt>||<algorithm>"],
      "name": ["name"],
      "dob": ["01/02/60"],
      "license_plate": ["123456"],
      "address": ["example address"],
      "phone": ["+18005551234"],
      "company": ["example company"],
      "url": ["url.com"],
      "social": ["social username"],
      "cryptocurrency_address": ["0x..."],
      "database_name": "Example Database Name",
      "raw_record": {"le_only": true, "unstructured": true}
    }
  ],
  "took": "179µs",
  "total": 5
}
```

Empty attributes are omitted. Arrays can hold multiple values.

### Pagination limits

| Limit | Value |
| --- | --- |
| `size` | 1–10,000 |
| `page` | ≥ 1 |
| `page * size` | ≤ 50,000 |
| Deep session TTL | 10 minutes |

Pages entirely within the first 10,000 results may be requested in any order.
Deeper pages must be fetched sequentially; page N requires page N−1 in the same
session. `page*size > 50,000` is rejected. Restart from page 1 after a deep
session expires.

| Error | Cause |
| --- | --- |
| `400 size must be between 1 and 10000` | size out of range |
| `400 page must be 1 or greater` | page ≤ 0 |
| `400 pagination limit exceeded` | `page*size` > 50,000 |
| `400 deep pagination error: pages must be fetched sequentially` | skipped a page or session expired |
| `500 issue with pagination state` | transient; retry |

### Live query quirks (verified 2026-11-25)

| Query | Result |
| --- | --- |
| `email:test@example.com` | 1,982,342 hits, potentially unrelated first rows — too loose |
| `email:"test@example.com"` | 5,182 hits, first row exact — **use quotes** |
| `domain:example.com` | 200, total 0 |
| `domain:"example.com"` | 400 `Issue with query format` — **never quote domains** |
| `email:*@example.com` | 400 — leading wildcards are rejected |
| `email:test*&domain:example.com` + `wildcard=true` | 200, 83,806 hits |
| `email:test.*&domain=example.com` + `regex=true` | 200, 83,806 hits |
| `domain:example.com&data=collections` | 400 — `&data=` is web-only |

---

## 3. POST /v2/search-password

Free. No subscription or credits.

Request: `{"sha256_hashed_password": "<hex sha-256>"}`

Response: `{"results_found": 239561}`

Non-zero means the exact password string appears somewhere in the corpus. It
does **not** identify which user or account used it, and it is not proof that a
specific person chose it. The helper computes the SHA-256 locally and sends only
the digest.

---

## 4. GET /v2/info/user

Free. Returns `search_access`, `search_credits`, `whois_credits`.

---

## 5. GET /data-wells

Free. No API key or subscription required.

| Parameter | Notes |
| --- | --- |
| `count` | 20 or 50 |
| `page` | page number |
| `sort` | `added`, `name`, `date`, `records`; append `-ASC` for ascending; default descending |

Response:

```json
{
  "next_page": true,
  "total": 24092,
  "data_wells": [
    {
      "name": "Breach Name",
      "date": "2025-03-01",
      "description": "Description of breach.",
      "records": 500000,
      "data": "name,email,address,username",
      "is_sensitive": false
    }
  ]
}
```

Useful for asking "does the corpus contain a breach relating to X" without
spending credits. Sweep once, cache, then grep offline.

---

## 6. Monitoring API

All endpoints take `Dehashed-Api-Key` and JSON. Mutating calls require explicit
confirmation in the helper (`--yes`). Monitoring has a separate entitlement; an
account without it gets 401 `account does not have monitoring API access`.

### Tasks

| Operation | Endpoint | Body |
| --- | --- | --- |
| create | `POST /v2/monitoring/create-task` | `{"type":"email","value":"..."}` |
| update | `POST /v2/monitoring/update-task` | `{"id":"...","type":"...","value":"...","active":true}` |
| set active | `POST /v2/monitoring/update-task` | `{"id":"...","active":false}` |
| delete | `POST /v2/monitoring/delete-task` | `{"id":"..."}` |
| list | `POST /v2/monitoring/get-tasks` | `{"page":1}` |
| get | `POST /v2/monitoring/get-task` | `{"id":"..."}` |

Task types: `email`, `username`, `phone`, `name`.

### Reports

| Operation | Endpoint | Body |
| --- | --- | --- |
| list | `POST /v2/monitoring/get-reports` | `{"page":1}` |
| get | `POST /v2/monitoring/get-report` | `{"id":"..."}` |

A report contains `tasks[]` with `results[]` in the same entry shape as
`/v2/search`.

### Notification channels

| Operation | Endpoint | Body |
| --- | --- | --- |
| list | `POST /v2/monitoring/get-channels` | `{}` |
| set | `POST /v2/monitoring/update-channel` | `{"type":"webhook","value":"https://..."}` |
| delete | `POST /v2/monitoring/delete-channel` | `{"channel":"webhook"}` |

Types: `webhook`, `email`.

Webhook payload when a report is generated:

```json
{"id": "report_id"}
```

### Monitoring domains

| Operation | Endpoint | Body |
| --- | --- | --- |
| list | `GET /v2/monitoring/get-domains` | – |
| update | `POST /v2/monitoring/update-domain` | `{"id":"...","domain":"example.com"}` |
| clear | `POST /v2/monitoring/clear-domain` | `{"id":"..."}` |

Domain format: `example.com`, no scheme or path.

---

## 7. WHOIS API

`POST /v2/whois/search` with `search_type` selecting the operation. All consume
WHOIS credits (not search credits).

| `search_type` | Extra fields | Cost |
| --- | --- | --- |
| `whois` | `domain` | 1 |
| `whois-history` | `domain` | 25 |
| `reverse-whois` | `include[]` max 4, `exclude[]` max 4, `reverse_type` `current`/`historic` | 1 |
| `reverse-ip` | `domain` = IP address | 1 |
| `reverse-mx` | `domain` = MX host | 1 |
| `reverse-ns` | `domain` = NS host | 1 |
| `subdomain-scan` | `domain` | 1 |

`reverse-whois` needs at least one include or exclude term. With
`whois_credits: 0`, every call fails with `400 not enough whois credits`.

`GET /v2/whois/credits` (free) returns `{"whois_credits": N}`.

---

## 8. Error reference

| HTTP | Message | Meaning |
| --- | --- | --- |
| 400 | `issue with authentication` | malformed auth |
| 400 | `Issue with query format` | bad query syntax |
| 400 | `size must be between 1 and 10000` | size out of range |
| 400 | `page must be 1 or greater` | page ≤ 0 |
| 400 | `pagination limit exceeded` | `page*size` > 50,000 |
| 400 | `deep pagination error...` | skipped deep page or session expired |
| 401 | `You need a search subscription and API credits...` | no search entitlement |
| 401 | `account does not have monitoring API access` | no monitoring entitlement |
| 403 | `Insufficient Credits` | balance exhausted |
| 429 | `too many requests` | rate limit; back off |
| 500 | `issue with pagination state` | transient; retry |

---

## 9. Free-first strategy

Because two useful endpoints are free and search is not:

1. `GET /v2/info/user` — is search possible?
2. `GET /data-wells` (cached sweep) — does the corpus contain a breach for this
   organisation, brand or supplier?
3. `POST /v2/search-password` — are the organisation's brand-derived or
   policy-relevant passwords already widely breached?
4. `POST /v2/search` — only the account-level exposure that nothing above can
   answer, within the credit budget.

---

## 10. Local spend guard (skill-side)

The CLI is deliberately conservative about spending:

- Paid calls are **off by default** (`--max-credits 0`). A caller must pass
  `--max-credits N` to authorise a spend.
- A shared ledger at `~/.cache/dehashed/budget.json` reserves credits before
  each paid request and caps **all sessions** at **10 credits/day** by default
  (`DEHASHED_DAILY_MAX_CREDITS`). Reservations are intentionally not refunded
  on failed requests, so a retry loop cannot drain the account.
- `~/.config/dehashed/PAUSE` blocks all paid calls across every session.
  `dehashed.py pause` / `resume` manage it.
- These are local guards, not vendor billing controls. Calls made outside this
  client (curl, the web UI, an older copy of the script) are invisible to the
  ledger. `/v2/info/user` remains the authoritative balance.

---

## 11. Evidence handling

- Record the exact query, timestamp, HTTP status and credit delta for every paid
  call. The helper prints these in the summary and stores them in the JSON
  `meta` block.
- Keep plaintext passwords and hashes in the engagement evidence directory, not
  in chat summaries or shared documents.
- Cache files and exports are created with mode 600; the cache directory is mode
  700. Remove the key file and cache at engagement cleanup.
- Breach data is personal data. Collect the minimum needed for the agreed scope.
