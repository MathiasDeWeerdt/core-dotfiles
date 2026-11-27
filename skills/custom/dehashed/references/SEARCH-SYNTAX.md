# DeHashed search syntax

Verified against the vendor search guide and live `/v2/search` calls on
2026-11-25. The v2 API accepts the same `field:value` grammar as the web UI,
but transport parameters (`page`, `size`, `wildcard`, `regex`, `de_dupe`) are
JSON fields, not URL suffixes.

Base query grammar: `field:value`, joined with `&` (logical AND).

---

## 1. Fields

Documented search fields:

| Field | Example | Notes |
| --- | --- | --- |
| `email` | `email:"alice@example.com"` | quote the full address |
| `username` | `username:jsmith` | |
| `password` | `password:"<candidate-password>"` | plaintext password |
| `hashed_password` | `hashed_password:<password-hash>` | |
| `ip_address` | `ip_address:203.0.113.10` | |
| `name` | `name:"John Smith"` | quote multi-word values |
| `address` | `address:"123 Main St"` | |
| `phone` | `phone:+18005551234` | |
| `domain` | `domain:example.com` | **never quote** |
| `vin` | `vin:1HGBH41JXMN109186` | |

Fields that appear in results but are not in the documented search list:
`company`, `database_name`, `license_plate`, `social`, `url`,
`cryptocurrency_address`, `dob`, `raw_record`. `company:<value>` is observed in
the result schema and is likely searchable, but test with `--size 1` before
trusting a large query.

---

## 2. Quoting rules (verified)

| Value | Correct | Wrong | Evidence |
| --- | --- | --- | --- |
| exact email | `email:"test@example.com"` | `email:test@example.com` | unquoted returned 1,982,342 loose hits and a `unrelated@example.net` first row; quoted returned 5,182 hits with `test@example.com` first |
| domain | `domain:example.com` | `domain:"example.com"` | quoted domain returns HTTP 400 `Issue with query format` |
| multi-word name/address | `name:"John Smith"` | `name:John Smith` | space splits the query |
| wildcard/regex value | `email:joh*` | `email:"joh*"` | quotes make `*` literal |

General rule: quote emails and values containing spaces. Never quote domains.
Do not quote wildcard or regex patterns.

---

## 3. Combining fields

`&` joins field conditions; all conditions must match.

```text
username:example&email:example@example.com
email:example@example.com&username:test&ip_address:127.0.0.1
domain:example.com&username:admin
name:"john smith"&ip_address:127.0.0.1
```

There is no documented `OR`, `NOT`, or parenthesis syntax. Run separate queries
and merge locally if you need alternatives.

---

## 4. Wildcards

`?` replaces one character. `*` replaces zero or more characters.

```text
username:examp?e
email:examp*&domain:example.com
domain:exam*
```

Rules:

- **No leading wildcard.** `name:*ohn` is rejected; `name:Joh*` works.
- Email wildcards **must be split** into local part and domain:
  `email:joh*@example.com` is not reliable; use
  `email:joh*&domain:example.com`.
- API: set `"wildcard": true`. Web UI: append `&wildcard` to the query.
  The helper script accepts either form.
- You cannot combine wildcard and regex in one search.

---

## 5. Regex

```text
name:joh?n(ath[oa]n)
email:joh?n(ath[oa]n)&domain:hotmail.com
username:^admin[0-9]+$
```

Rules:

- Must specify a field. A bare regex is rejected.
- No `/.../` wrapper is needed in the current API; the field value is the
  pattern.
- Email regex **must be split** into local part and domain:
  `email:/joh?n(ath[oa]n)/@hotmail.com` does not work;
  `email:joh?n(ath[oa]n)&domain:hotmail.com` does.
- API: set `"regex": true`. Web UI: append `&regex`.
- You cannot combine regex and wildcard in one search.

---

## 6. Web-only operators

The web UI accepts `&data=<origin>` to restrict results to one data well:

```text
domain:example.com&data=collections
```

**This returns HTTP 400 through the v2 API** (verified 2026-11-25). Use the
`database_name` field in returned entries to attribute or filter results
locally instead.

The web UI also accepts `&size=N`, `&wildcard` and `&regex` as URL suffixes.
The helper script strips and converts these to JSON parameters. Do not put
`&data=` in an API query.

---

## 7. Pagination

| Parameter | Range | Default |
| --- | --- | --- |
| `size` | 1–10,000 | 100 |
| `page` | 1–50,000/size | 1 |
| `page * size` | ≤ 50,000 | – |

- Pages whose results fit entirely within the first 10,000 (`page*size ≤
  10,000`) can be requested in any order.
- Deeper pages must be fetched sequentially: page N requires page N−1 in the
  same session.
- The deep-pagination session expires 10 minutes after creation or after
  10 minutes of inactivity. Restart from page 1 if it expires.
- `page*size > 50,000` returns `pagination limit exceeded`.
- A skipped deep page returns
  `deep pagination error: pages must be fetched sequentially`.

Cost: **one search credit per request/page**, including a page with zero
results. A cached page costs nothing.

---

## 8. Result interpretation

| Field | Meaning |
| --- | --- |
| `total` | corpus matches for the query, not unique people |
| `entries[].database_name` | source breach/data well |
| `entries[].email` etc. | arrays; a record can hold several values |
| `password` | plaintext, when the source contained it |
| `hashed_password` | `hash:salt||TYPE` or bare hash, depending on source |
| `raw_record.le_only` | record is law-enforcement-only |
| `raw_record.unstructured` | record came from unstructured text |

Caveats:

- `de_dupe: true` removes repeated records across sources. It makes a summary
  easier to read but **hides which other breaches matched**. Default is off.
- A hit is evidence that the value appears in the corpus, not proof that a
  specific person still uses the password.
- Absence of a hit is not evidence of no exposure. Coverage is incomplete.

---

## 9. Copy-paste examples

```text
# exact person
email:"alice@example.com"
email:"alice@example.com"&username:alice

# organisation
domain:example.com
domain:example.com&username:admin

# local-part prefix at a domain (wildcard)
email:joh*&domain=example.com

# local-part pattern at a webmail domain (regex)
email:joh?n(ath[oa]n)&domain:hotmail.com

# password reuse
password:"<candidate-password>"

# infrastructure
ip_address:203.0.113.10
domain:example.com&ip_address:203.0.113.10

# identity
name:"John Smith"
phone:+18005551234
address:"123 Main St"
vin:1HGBH41JXMN109186
```

With the helper script (add `--max-credits N` to authorise a paid call; the
default is 0 and `~/.config/dehashed/PAUSE` blocks all paid calls):

```sh
python3 scripts/dehashed.py email 'alice@example.com' --max-credits 1
python3 scripts/dehashed.py domain example.com --size 100 --max-credits 1
python3 scripts/dehashed.py email-part joh --domain example.com --max-credits 1
python3 scripts/dehashed.py raw 'email:joh?n(ath[oa]n)&domain:hotmail.com' --regex --max-credits 1
```
