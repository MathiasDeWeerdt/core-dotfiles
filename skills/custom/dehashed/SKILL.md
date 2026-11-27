---
name: dehashed
description: Query DeHashed breach data for emails, domains, usernames, passwords, hashes, phone numbers, IPs, names and addresses, with free-first checks, credit budgeting, caching and WHOIS/monitoring support. Use when checking whether an email, domain, brand, supplier or credential appears in breach data; when pivoting from an email to accounts or from a password to reused accounts; or whenever a task mentions DeHashed, breach-corpus lookup, credential exposure or leaked-credential analysis.
license: MIT
metadata:
  version: 2.0.1
---

# DeHashed breach-data lookups

A cached, budgeted client for the DeHashed v2 API. It is built to answer
"what does the corpus have for this selector" without wasting credits.

| File | Purpose |
| --- | --- |
| `scripts/dehashed.py` | CLI client (stdlib only) |
| `references/SEARCH-SYNTAX.md` | exact query grammar, quoting, wildcards, regex, pitfalls |
| `references/API.md` | every endpoint, cost, error and pagination rule |

Use the absolute path `~/.agents/skills/dehashed/scripts/dehashed.py` from any
working directory. This public package contains no API key or runtime data.
Keys belong in `$DEHASHED_API_KEY` or private `~/.config/dehashed/api_key` (0600);
caches and the shared budget ledger stay under `~/.cache/dehashed` (0700).
Keep exports in a private evidence directory outside Git, for example under
`~/.local/state/dehashed/evidence/`. The client rejects sensitive file writes
inside Git checkouts and inside the skill package, including through symlinks.
Only the DeHashed HTTPS origin receives API authentication; redirects are refused.

---

## 1. First run

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py status
```

Free. Shows entitlement and balances:

```
[=] search_access : True
[=] search_credits: <balance>
[=] whois_credits : 0
[=] daily guard   : 0/10 credits reserved today (10 left)
[=] paid state    : PAUSED
```

- `search_access=false` means `/v2/search` returns 401 **even with credits**.
  That is a subscription state on the DeHashed account; no header fixes it.
- `whois_credits=0` means all WHOIS commands fail. Do not spend time on them.
- The API key is read from `$DEHASHED_API_KEY` or
  `~/.config/dehashed/api_key` (mode 600). `init` stores it safely:

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py init
```

If a key was ever pasted into a chat, ticket or commit, rotate it at DeHashed.

### Spending gate

- **Paid calls are off by default.** The per-run budget is 0. Add
  `--max-credits 1` to authorise one credit; add more only with approval.
- A shared local ledger caps **all sessions** at **10 credits/day**. Inspect it
  with `dehashed.py budget`; override the cap only with
  `DEHASHED_DAILY_MAX_CREDITS`.
- **Paid-call pause is private per-machine state.** `dehashed.py pause` writes
  `~/.config/dehashed/PAUSE`; every session then refuses paid calls, even with
  `--max-credits`. Remove it with `dehashed.py resume` when spending is
  approved. Do **not** run `resume` or raise the caps on your own initiative;
  only on an explicit user instruction.
- Run `--dry-run` first for an unfamiliar query. It validates the request and
  shows the budget without calling `/v2/search`.
- Free: `status`, `budget`, `pw`, `pw-batch`, `wells`, `wells-grep`.
- `--refresh` bypasses the cache and spends again. Use it only when freshness
  matters.
- Paid requests are retried at most once. A timed-out request may already have
  been billed, so do not loop or parallelise paid searches.
- If a query returns `total=0` or a clear error, do not retry it with a bigger
  page size; the next request still costs a credit.

---

## 2. Lookup recipes

### Full email address

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py email 'alice@example.com' --size 100 --max-credits 1
```

The helper quotes the address automatically. Quoting matters: an unquoted
`email:test@example.com` returned loose matches;
the quoted form is intended for exact addresses.

### Domain (all emails at an organisation)

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py domain example.com --size 1000 --show 20 --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py domain example.com --all --size 1000 --max-credits 5
```

`domain:example.com` is the correct way to ask for an organisation's exposed
accounts. Never quote the domain — `domain:"example.com"` returns HTTP 400.

### Part of an email — local-part prefix

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py email-part alice --domain example.com --max-credits 1
```

Builds `email:alice*&domain:example.com` with `wildcard=true`. Without
`--domain`, it searches `email:alice*` across all domains, which can be very
large — add `--size 1 --show 1` for an existence check.

### Part of an email — pattern

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py email-part 'al?ce' --domain example.com --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py raw 'email:al(ice|yce)&domain:example.com' --regex --max-credits 1
```

DeHashed rejects **leading** wildcards: `*alice*` and `*@example.com` do not
work. Use a prefix (`alice*`) or a regex, and keep the domain in its own
`&domain:` clause. The helper enforces this.

### Other selectors

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py username jsmith --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py password '<candidate-password>' --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py hash <password-hash> --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py name 'John Smith' --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py phone '+18005551234' --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py ip 203.0.113.10 --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py address '123 Main St' --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py company 'Acme Inc' --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py vin 1HGBH41JXMN109186 --max-credits 1
```

`auto` classifies an unknown selector and dispatches:

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py auto alice@example.com --size 100 --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py auto example.com --size 100 --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py auto 203.0.113.10 --size 100 --max-credits 1
```

### Free checks — use these first

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py pw '<candidate-password>'          # corpus-wide count, free
python3 ~/.agents/skills/dehashed/scripts/dehashed.py pw-batch candidates.txt   # bulk, free
python3 ~/.agents/skills/dehashed/scripts/dehashed.py wells-grep example acme   # offline after one sweep
python3 ~/.agents/skills/dehashed/scripts/dehashed.py wells-grep --name-only acme
python3 ~/.agents/skills/dehashed/scripts/dehashed.py wells                      # free sweep, cached
```

`pw` sends only the SHA-256 of the candidate and returns `results_found`. It
does not identify a user. `wells-grep` answers "is there a breach dataset
related to this name" without spending anything.

---

## 3. Smart lookup workflow

1. **Classify.** `auto <selector>` (or pick the field explicitly).
2. **Check entitlement.** `status` once per session. Stop on
   `search_access=false` or `whois_credits=0`.
3. **Free context.** For a brand/organisation, `wells-grep` the name. For a
   candidate password, `pw`. Both are free and cached.
4. **Targeted paid query.** Add `--max-credits 1` only when the spend is
   approved. Start with `--size 1 --show 1` to prove a hit exists, or
   `--size 100` for a readable sample. Do not fetch all pages until the first
   page proves the query is right.
5. **Read the summary.** Check `total`, top databases, unique emails/domains,
   plaintext vs hash-only, and the sample table.
6. **Pivot only on what is in scope.** Extract new selectors from the results:
   emails, usernames, domains, passwords. Each pivot is a new query; the cache
   makes repeats free.
7. **Export evidence.** `--out` writes the full records and a `meta` block with
   query, timestamp, pages, live requests and credit delta.

### Pivot patterns

**Email → other accounts via password reuse** (authorised scope only):

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py email 'alice@example.com' --reveal \
  --out ~/.local/state/dehashed/evidence/alice.json --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py pw '<recovered-password>'            # free prevalence
python3 ~/.agents/skills/dehashed/scripts/dehashed.py password '<recovered-password>' --size 100 --max-credits 1
```

The paid password search returns every account using that exact plaintext
password. Treat the output as evidence; do not try the password against a live
system without explicit approval and a lockout-aware, one-attempt plan.

**Domain → executives / high-value accounts:**

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py domain example.com --size 1000 --show 0 \
  --out ~/.local/state/dehashed/evidence/example-domain.json --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py email-part ceo --domain example.com --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py email-part admin --domain example.com --max-credits 1
```

**Username or phone → identity/email:**

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py username jsmith --size 100 --reveal --max-credits 1
python3 ~/.agents/skills/dehashed/scripts/dehashed.py phone '+18005551234' --size 100 --max-credits 1
```

**IP → accounts that used it:**

```sh
python3 ~/.agents/skills/dehashed/scripts/dehashed.py ip 203.0.113.10 --size 100 --max-credits 1
```

**Hash → plaintext pivot:** the API returns hashes, not cracks. Search the hash
to find other records, then use the free `pw` check only if you already have a
candidate plaintext. Do not present a hash as a cracked password.

---

## 4. Query rules that matter

Full detail: `references/SEARCH-SYNTAX.md`.

1. `field:value`, joined with `&` (AND). No documented OR/NOT.
2. Quote full emails: `email:"user@example.com"`.
3. Never quote domains: `domain:example.com`.
4. Quote multi-word names/addresses: `name:"John Smith"`.
5. No leading wildcards. `name:Joh*` works; `name:*ohn` is rejected.
6. Email wildcards/regex must be split:
   `email:alice*&domain:example.com`.
7. Wildcard and regex are mutually exclusive.
8. `&data=<origin>` is web-UI-only and returns 400 through the v2 API.

The helper enforces 2–6 for structured commands. Use `raw` only when you know
the grammar.

---

## 5. Cost and efficiency

| Operation | Cost |
| --- | --- |
| `/v2/info/user` | free |
| `/v2/search-password` | free |
| `/data-wells` | free |
| `/v2/search` | **1 credit per page/request** |
| `/v2/whois/search` | 1 credit; WHOIS history 25 |

Rules the helper applies:

- Default per-run budget is **0**: paid calls require explicit
  `--max-credits N`. The shared daily guard caps **all sessions** at
  **10 credits/day**. Cached pages do not count.
- `dehashed.py pause` blocks paid calls across all sessions; `dehashed.py
  resume` clears the block. `dehashed.py budget` shows today's ledger.
- `size` maxes at 10,000; `page*size ≤ 50,000`. A page with zero results still
  costs one credit.
- Rate limit is 20 req/s. The client sleeps ~0.06 s between calls and backs off
  on 429.
- Identical requests are served from `~/.cache/dehashed` and cost nothing.
  `--refresh` forces a live call.

Efficiency choices:

- **Existence check:** `--size 1 --show 1` (same 1 credit, tiny response).
- **Readable sample:** `--size 100` (1 credit).
- **Bulk domain pull:** `--all --size 1000 --max-credits 5` retrieves up to
  5,000 entries for 5 credits. `--size 100` would cost 50 credits for the same
  5,000 entries.
- **Noise:** `de_dupe` is **off** by default so every source breach stays
  attributable. Add `--dedupe` for a cleaner read when the source mix does not
  matter.
- **Dry run:** `--dry-run` prints the final query, flags, page plan, budget and
  entitlement without spending.

---

## 6. Output and evidence

```sh
--out ~/.local/state/dehashed/evidence/result.json      # full JSON + meta
--out ~/.local/state/dehashed/evidence/result.csv       # flattened CSV
--out ~/.local/state/dehashed/evidence/result.ndjson    # one record per line
--print-json                    # JSON to stdout, no summary
--show 0                        # summary without the sample table
--reveal                        # show plaintext passwords in the summary
--quiet                         # one-line summary
```

Defaults protect against casual password exposure: the summary masks plaintext
passwords, while the exported file contains full records. Exports and cache
files are written with mode 600; the cache directory is mode 700. Keep them in
the engagement evidence directory and remove them at cleanup.

Record for every paid call: exact query, timestamp, HTTP status, pages, credit
delta. The JSON `meta` block already contains these.

---

## 7. Authorised use

DeHashed holds other people's breached credentials. Use it for:

- the client's own domains, brands and staff, inside the agreed scope;
- lawful investigations and due diligence where you have a basis to query;
- validating exposure of a supplier or asset you are authorised to assess.

Do not use it to look up unrelated individuals or to access accounts. Do not
try recovered credentials against a live system without:

1. an explicit request naming the system;
2. confirmation that the target is in scope and the client accepts lockout risk;
3. a lockout-aware plan — one attempt per account, never a list.

If those are missing, report the exposure and stop.

Breach data is personal data. Collect the minimum, keep plaintext passwords in
the evidence directory only, and do not paste them into chat summaries or
shared documents.

---

## 8. Command reference

Paid commands need `--max-credits N`; the default is 0 (disabled).

| Command | Cost | Purpose |
| --- | --- | --- |
| `status` | free | entitlement + credits — run first |
| `budget` | free | today's shared spend guard |
| `pause` / `resume` | free | stop / allow all paid calls |
| `init` | – | store the API key (mode 600) |
| `auto <value>` | paid | detect email/domain/IP/phone and look up |
| `email <addr>` | paid | exact email (quoted) |
| `email-part <pattern>` | paid | local-part prefix/pattern; `--domain` to narrow |
| `domain <domain>` | paid | all records for a domain |
| `username`, `password`, `hash`, `name`, `phone`, `ip`, `address`, `company`, `vin` | paid | field lookup |
| `raw '<query>'` | paid | full query grammar; `--wildcard`/`--regex` |
| `pw <password>` | free | SHA-256 corpus count |
| `pw-batch <file>` | free | bulk password counts |
| `wells` | free | sweep and cache all data wells |
| `wells-grep <kw>...` | free | offline grep of the cached sweep |
| `whois <domain>` | 1 | current WHOIS |
| `whois-history <domain>` | 25 | historical WHOIS; needs `--max-credits 25 --yes` |
| `whois-reverse` | 1 | `--include`/`--exclude` terms |
| `whois-ip`, `whois-mx`, `whois-ns`, `whois-subdomains` | 1 | infrastructure pivots |
| `monitor ...` | free* | tasks, reports, channels, domains; mutations need `--yes` |
| `cache` | – | inspect, `--prune DAYS`, `--clear` |

`*` No documented credit cost, but monitoring depends on a separate
entitlement. The client reports the 401 clearly instead of retrying.

---

## 9. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `search_access=false` | no search subscription; credits are unusable. Fix on the DeHashed account. |
| `401 You need a search subscription...` | same; adding an email header does not help. |
| `403 Insufficient Credits` | balance exhausted; raise `--max-credits` only after topping up. |
| `Credit budget exhausted (0)` | paid calls are disabled by default; add `--max-credits 1` only with approval. |
| `paid calls are paused` | run `dehashed.py resume` after confirming the spend is authorised. |
| `daily budget guard` | 10 credits already reserved today; wait for the next day or raise the cap with approval. |
| `400 Issue with query format` | quoted domain, unquoted email, leading wildcard, wildcard+regex, or `&data=`. |
| `429 too many requests` | rate limit; the client backs off. Do not parallelise aggressively. |
| `deep pagination error` | start at page 1 and fetch sequentially within 10 minutes. |
| `not enough whois credits` | `whois_credits=0`; top up or skip WHOIS. |
| `account does not have monitoring API access` | separate entitlement; do not retry. |
| No API key | `init`, or export `DEHASHED_API_KEY`. |

If a query returns 0, that is not proof of no exposure. It means this corpus has
no matching record. State that limit in reporting.
