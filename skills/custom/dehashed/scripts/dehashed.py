#!/usr/bin/env python3
"""
DeHashed v2 API client for authorised breach-exposure lookups.

Design goals:
  * free endpoints first, paid searches only when they add information
  * one credit = one search page; hard budget per invocation
  * every successful search page is cached, so repeats are free
  * human-readable summary plus JSON/CSV/NDJSON export
  * no third-party dependencies

Key resolution order:
  1. $DEHASHED_API_KEY
  2. ~/.config/dehashed/api_key   (created by `dehashed.py init`, mode 600)

Optional identification header (does NOT change entitlement):
  $DEHASHED_CONTACT_EMAIL

The API key is never printed, logged or written to the cache.

Read SKILL.md before use. Breach data is personal data: collect the minimum,
store it in the engagement evidence directory, and never try recovered
credentials against a live system without explicit authorisation.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import ipaddress
import json
import os
import re
import sys
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl  # POSIX only; the ledger falls back to best-effort without it
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

VERSION = "2.0.1"
API = "https://api.dehashed.com"
CONFIG_DIR = os.path.expanduser("~/.config/dehashed")
KEY_FILE = os.path.join(CONFIG_DIR, "api_key")
CACHE_DIR = os.path.expanduser(os.environ.get("DEHASHED_CACHE_DIR", "~/.cache/dehashed"))
WELLS_CACHE = os.path.join(CACHE_DIR, "datawells_all.json")
LEDGER_FILE = os.path.join(CACHE_DIR, "budget.json")
PAUSE_FILE = os.path.join(CONFIG_DIR, "PAUSE")

# Paid calls are OFF unless the caller explicitly passes --max-credits N.
# A shared local ledger also caps every session's total spend per day.
DEFAULT_MAX_CREDITS = int(os.environ.get("DEHASHED_MAX_CREDITS", "0") or 0)
DAILY_MAX_CREDITS = int(os.environ.get("DEHASHED_DAILY_MAX_CREDITS", "10") or 10)
RATE_SLEEP = 0.06           # ~16 req/s, below the documented 20 req/s ceiling
MAX_PAGE_SIZE = 10_000
MAX_RESULTS = 50_000
HTTP_TIMEOUT = 90
PAID_RETRIES = 1            # a timed-out paid request may already have been billed

SEARCH_FIELDS = {
    "email": "email",
    "username": "username",
    "password": "password",
    "hashed_password": "hashed_password",
    "ip_address": "ip_address",
    "name": "name",
    "address": "address",
    "phone": "phone",
    "company": "company",
    "vin": "vin",
    "domain": "domain",
    "database_name": "database_name",
    "license_plate": "license_plate",
    "social": "social",
    "url": "url",
    "cryptocurrency_address": "cryptocurrency_address",
}

LOOKUP_KINDS = {
    "email": "email",
    "email-part": "email-part",
    "domain": "domain",
    "username": "username",
    "password": "password",
    "hash": "hashed_password",
    "name": "name",
    "phone": "phone",
    "ip": "ip_address",
    "address": "address",
    "company": "company",
    "vin": "vin",
}

COLUMNS = [
    "id", "email", "username", "password", "hashed_password", "name", "dob",
    "license_plate", "address", "phone", "company", "url", "social",
    "cryptocurrency_address", "ip_address", "database_name", "raw_record",
]

WHOIS_COSTS = {
    "whois": 1,
    "whois-history": 25,
    "reverse-whois": 1,
    "reverse-ip": 1,
    "reverse-mx": 1,
    "reverse-ns": 1,
    "subdomain-scan": 1,
}


# ------------------------------------------------------------------ exceptions
class DeHashedError(Exception):
    exit_code = 1


class UsageError(DeHashedError):
    exit_code = 2


class EntitlementError(DeHashedError):
    exit_code = 2


class BudgetError(DeHashedError):
    exit_code = 2


class ApiError(DeHashedError):
    exit_code = 3

    def __init__(self, status: int, message: str, payload: Any = None):
        self.status = status
        self.payload = payload
        super().__init__(message)


# ------------------------------------------------------------------ utilities
def eprint(*args: Any, **kwargs: Any) -> None:
    print(*args, file=sys.stderr, **kwargs)


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None and str(v) != ""]
    if isinstance(value, (tuple, set)):
        return [str(v) for v in value if v is not None and str(v) != ""]
    text = str(value)
    return [text] if text else []


def shorten(text: Any, width: int) -> str:
    text = "" if text is None else str(text).replace("\n", " ")
    if len(text) <= width:
        return text
    return text[: max(0, width - 3)] + "..."


def mask(value: str, reveal: bool, width: int = 24) -> str:
    if not value:
        return "-"
    return shorten(value, width) if reveal else "********"


def check_private_path(path: str) -> None:
    """Runtime credentials and breach data must never enter a skill or Git tree."""
    resolved = Path(path).expanduser().resolve()
    package = Path(__file__).resolve().parents[1]
    if resolved.is_relative_to(package):
        raise UsageError("Keep DeHashed credentials, caches, and evidence outside the skill package.")
    if any((parent / ".git").exists() for parent in (resolved, *resolved.parents)):
        raise UsageError("Keep DeHashed credentials, caches, and evidence outside Git checkouts.")


def ensure_private_dir(path: str, mode: int = 0o700) -> None:
    check_private_path(path)
    os.makedirs(path, mode=mode, exist_ok=True)
    os.chmod(path, mode)


@contextmanager
def private_output(path: str, newline: str | None = None):
    check_private_path(path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".dehashed-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as fh:
            yield fh
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def write_private(path: str, text: str) -> None:
    with private_output(path) as fh:
        fh.write(text)


# --------------------------------------------------------------- key handling
def load_key() -> str:
    key = os.environ.get("DEHASHED_API_KEY", "").strip()
    if key:
        return validate_key(key)
    check_private_path(KEY_FILE)
    try:
        fd = os.open(KEY_FILE, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        fd = None
    if fd is not None:
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise UsageError("DeHashed key file must be owned by you and mode 0600.")
            with os.fdopen(fd, encoding="utf-8", closefd=False) as fh:
                key = fh.read().strip()
        finally:
            os.close(fd)
        if key:
            return validate_key(key)
    raise UsageError(
        "No API key found.\n"
        f"  Set $DEHASHED_API_KEY or create {KEY_FILE} (mode 600).\n"
        "  Run: dehashed.py init"
    )


def validate_key(key: str) -> str:
    if not key or any(not 33 <= ord(character) <= 126 for character in key):
        raise UsageError("API key must be one nonempty value without whitespace or control characters.")
    return key


def headers() -> dict[str, str]:
    h = {
        "Dehashed-Api-Key": load_key(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f"dehashed-skill/{VERSION}",
    }
    contact = os.environ.get("DEHASHED_CONTACT_EMAIL", "").strip()
    if contact:
        # Identification only. Verified not to affect entitlement.
        h["Dehashed-Email"] = contact
    return h


# ------------------------------------------------------------------ transport
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # API authentication must never follow a redirect to another origin.
        return None


HTTP = urllib.request.build_opener(NoRedirect())


def request(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    *,
    retries: int = 3,
    sleep: bool = True,
) -> tuple[int, Any]:
    """Return (status_code, decoded_json_or_error_dict).

    Retries 429 with exponential backoff and transient 500 pagination-state
    errors. Never retries a 4xx that is not 429.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "api.dehashed.com" or parsed.fragment:
        raise UsageError("Authenticated requests must use the DeHashed HTTPS API origin.")
    payload = json.dumps(body).encode() if body is not None else None
    hdrs = headers()
    for attempt in range(retries + 1):
        if sleep:
            time.sleep(RATE_SLEEP)
        req = urllib.request.Request(url, method=method, data=payload, headers=hdrs)
        try:
            with HTTP.open(req, timeout=HTTP_TIMEOUT) as resp:
                raw = resp.read().decode(errors="replace")
                raw = raw.replace(hdrs["Dehashed-Api-Key"], "<redacted>")
                try:
                    return resp.status, json.loads(raw)
                except json.JSONDecodeError:
                    return resp.status, {"error": raw[:500]}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            exc.close()
            raw = raw.replace(hdrs["Dehashed-Api-Key"], "<redacted>")
            try:
                data: Any = json.loads(raw)
            except json.JSONDecodeError:
                data = {"error": raw[:500]}
            if exc.code == 429 and attempt < retries:
                wait = min(30, 2 ** attempt)
                eprint(f"[!] rate limited; retrying in {wait}s")
                time.sleep(wait)
                continue
            if exc.code == 500 and attempt < retries and "pagination" in raw.lower():
                wait = 2 ** attempt
                eprint(f"[!] transient pagination error; retrying in {wait}s")
                time.sleep(wait)
                continue
            return exc.code, data
        except Exception as exc:  # DNS, timeout, TLS, connection reset
            message = str(exc).replace(hdrs["Dehashed-Api-Key"], "<redacted>")
            if attempt < retries:
                wait = 2 ** attempt
                eprint(f"[!] transport error ({message}); retrying in {wait}s")
                time.sleep(wait)
                continue
            return 0, {"error": f"transport: {message}"}
    return 0, {"error": "request failed after retries"}


def api_error_hint(status: int, data: Any) -> str:
    text = json.dumps(data)[:800] if not isinstance(data, str) else data[:800]
    if status == 401:
        return (
            "Not authorised. /v2/info/user is the authoritative check.\n"
            "  - search_access=false means the account lacks a search subscription, "
            "even if search_credits > 0.\n"
            "  - Monitoring has its own entitlement and may be unavailable.\n"
            f"  API said: {text}"
        )
    if status == 403:
        return f"Insufficient credits or forbidden. API said: {text}"
    if status == 429:
        return f"Rate limited after retries. Slow down or wait. API said: {text}"
    if status == 400:
        return (
            "The API rejected the request. Common causes:\n"
            "  - a quoted domain (domain:example.com is correct, domain:\"example.com\" is not)\n"
            "  - an unquoted email (email:\"user@example.com\" is correct)\n"
            "  - a leading wildcard (name:*ohn is rejected; name:Joh* is accepted)\n"
            "  - wildcard and regex together\n"
            "  - page*size > 50,000\n"
            f"  API said: {text}"
        )
    return f"HTTP {status}: {text}"


# --------------------------------------------------------------------- caching
def _cache_path(kind: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    return os.path.join(CACHE_DIR, f"{kind}_{digest}.json")


def _cache_read(kind: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    path = _cache_path(kind, payload)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
        if isinstance(obj, dict) and "response" in obj:
            return {
                "response": obj["response"],
                "fetched_at": obj.get("fetched_at"),
                "request": obj.get("request"),
            }
        # Legacy cache format: raw response only.
        return {"response": obj, "fetched_at": None, "request": payload}
    except (OSError, json.JSONDecodeError):
        return None


def _cache_write(kind: str, payload: dict[str, Any], response: Any) -> str:
    ensure_private_dir(CACHE_DIR)
    path = _cache_path(kind, payload)
    wrapper = {"fetched_at": iso_now(), "request": payload, "response": response}
    write_private(path, json.dumps(wrapper, indent=1))
    return path


def _cache_has(kind: str, payload: dict[str, Any], refresh: bool) -> bool:
    return not refresh and os.path.exists(_cache_path(kind, payload))


# ------------------------------------------------------------------ spend ledger
def _today() -> str:
    return datetime.now().date().isoformat()


def _ledger_load() -> dict[str, Any]:
    """Load today's shared spend ledger. Resets automatically on a new day."""
    ensure_private_dir(CACHE_DIR)
    try:
        with open(LEDGER_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError
    except (OSError, ValueError, json.JSONDecodeError):
        data = {}
    if data.get("date") != _today():
        data = {"date": _today(), "spent": 0, "events": []}
    data.setdefault("spent", 0)
    data.setdefault("events", [])
    return data


def _ledger_save(data: dict[str, Any]) -> None:
    write_private(LEDGER_FILE, json.dumps(data, indent=1))


@contextmanager
def _ledger_lock():
    """Serialise reservations across concurrent skill sessions."""
    ensure_private_dir(CACHE_DIR)
    lock_path = LEDGER_FILE + ".lock"
    with open(lock_path, "a+", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def budget_reserve(credits: int, activity: str) -> str:
    """Reserve paid credits before a request. Raises BudgetError at the cap.

    Reserving before the request means a crash or timeout cannot under-count
    spend. Failed requests are intentionally not refunded: the guard is meant
    to stop retry loops, not to model the vendor's billing exactly.
    """
    if os.path.exists(PAUSE_FILE):
        raise BudgetError(
            f"paid calls are paused by {PAUSE_FILE}. "
            "Remove it or run `dehashed.py resume` when spending is approved."
        )
    with _ledger_lock():
        ledger = _ledger_load()
        spent = int(ledger.get("spent", 0))
        if spent + credits > DAILY_MAX_CREDITS:
            raise BudgetError(
                f"daily budget guard: {spent}/{DAILY_MAX_CREDITS} credits already "
                f"reserved today; '{activity}' needs {credits}. "
                "Raise DEHASHED_DAILY_MAX_CREDITS only with the account owner's approval."
            )
        event_id = f"{time.time_ns()}-{os.getpid()}"
        ledger["spent"] = spent + credits
        ledger["events"].append(
            {
                "id": event_id,
                "at": iso_now(),
                "credits": credits,
                "activity": activity,
                "status": "reserved",
            }
        )
        ledger["events"] = ledger["events"][-500:]
        try:
            _ledger_save(ledger)
        except OSError as exc:
            raise DeHashedError(
                f"cannot write the budget ledger {LEDGER_FILE}: {exc}. "
                "Paid calls are blocked until this is fixed."
            ) from exc
        return event_id


def budget_settle(event_id: str, status: str) -> None:
    try:
        with _ledger_lock():
            ledger = _ledger_load()
            for event in reversed(ledger["events"]):
                if event.get("id") == event_id:
                    event["status"] = status
                    break
            _ledger_save(ledger)
    except OSError as exc:
        eprint(f"[!] warning: could not update the budget ledger: {exc}")


def budget_remaining() -> tuple[int, int]:
    ledger = _ledger_load()
    spent = int(ledger.get("spent", 0))
    return max(0, DAILY_MAX_CREDITS - spent), spent


# ------------------------------------------------------------------- primitives
def get_status() -> dict[str, Any]:
    """Free. Entitlement and credit balance. Always call this first."""
    status, data = request("GET", f"{API}/v2/info/user")
    if status != 200 or not isinstance(data, dict):
        raise ApiError(status, api_error_hint(status, data), data)
    return data


def get_whois_credits() -> int | None:
    status, data = request("GET", f"{API}/v2/whois/credits")
    if status == 200 and isinstance(data, dict):
        try:
            return int(data.get("whois_credits"))
        except (TypeError, ValueError):
            return None
    return None


# ---------------------------------------------------------------- query builder
def _safe_value(value: str) -> str:
    if any(ch in value for ch in "\n\r&"):
        raise UsageError("values cannot contain '&' or newlines; use the 'raw' command for custom syntax")
    return value.strip()


def _quote(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def _field_value(field_name: str, value: str, *, exact_email: bool = False) -> str:
    value = _safe_value(value)
    if field_name == "domain":
        # Verified: domain:"example.com" returns 400. Never quote domains.
        return value
    if field_name == "email" and exact_email:
        return _quote(value)
    if field_name in ("name", "address") or any(ch.isspace() for ch in value):
        return _quote(value)
    if field_name in ("password", "phone", "company") and any(
        ch in value for ch in ' "'
    ):
        return _quote(value)
    return value


def _append_domain(query: str, domain: str | None) -> str:
    if not domain:
        return query
    domain = domain.strip().lstrip("@").lower()
    if not domain or any(ch in domain for ch in "\n\r& @"):
        raise UsageError(f"invalid domain filter: {domain!r}")
    return f"{query}&domain:{domain}"


def _strip_web_suffixes(query: str) -> tuple[str, bool, bool]:
    """Accept web-style &wildcard/&regex suffixes and convert to API flags."""
    wildcard = False
    regex = False
    if re.search(r"&wildcard(?:&|$)", query, re.I):
        wildcard = True
        query = re.sub(r"&wildcard(?=&|$)", "", query, flags=re.I)
    if re.search(r"&regex(?:&|$)", query, re.I):
        regex = True
        query = re.sub(r"&regex(?=&|$)", "", query, flags=re.I)
    query = re.sub(r"&size=\d+", "", query, flags=re.I)
    return query.strip("& "), wildcard, regex


def build_query(
    kind: str,
    value: str,
    *,
    domain: str | None = None,
    wildcard: bool = False,
    regex: bool = False,
) -> tuple[str, bool, bool]:
    """Return (query, wildcard, regex). Raises UsageError on unsafe syntax."""
    value = value.strip()
    if not value:
        raise UsageError("empty search value")

    if wildcard and regex:
        raise UsageError("wildcard and regex are mutually exclusive")

    if kind == "email":
        if "*" in value or "?" in value:
            return build_query(
                "email-part", value, domain=domain, wildcard=True, regex=regex
            )
        if "@" not in value:
            raise UsageError("an exact email must contain '@'; use email-part for a local part")
        return _append_domain(f"email:{_field_value('email', value, exact_email=True)}", domain), False, False

    if kind == "email-part":
        if value.startswith(("http://", "https://")):
            raise UsageError("email-part expects an email local part or pattern, not a URL")
        local = value
        embedded_domain = None
        if "@" in local:
            local, embedded_domain = local.rsplit("@", 1)
            embedded_domain = embedded_domain.lower()
        if not local:
            # "@example.com" and "*@example.com" mean "the whole domain".
            if embedded_domain:
                return build_query("domain", embedded_domain)
            raise UsageError("email-part needs a local part or pattern")
        if domain and embedded_domain and domain.lower().lstrip("@") != embedded_domain:
            raise UsageError(
                f"two different domains given: --domain {domain} and {embedded_domain}"
            )
        if not regex:
            if local.startswith(("*", "?")):
                raise UsageError(
                    "DeHashed rejects leading wildcards. Use a domain filter or regex "
                    "instead (e.g. email:john*&domain:example.com)."
                )
            if not any(ch in local for ch in "*?"):
                local += "*"
            wildcard = True
        return _append_domain(f"email:{local}", domain or embedded_domain), wildcard, regex

    if kind == "domain":
        raw = value.strip().lower()
        if "://" in raw:
            raw = urllib.parse.urlsplit(raw).netloc or raw.split("://", 1)[1]
        raw = raw.split("/", 1)[0].split(":", 1)[0]
        if raw.startswith("*."):
            raise UsageError(
                "DeHashed rejects leading wildcards. Query the parent domain "
                "(domain:example.com) or a specific subdomain instead."
            )
        if "*" in raw or "?" in raw:
            if raw.startswith(("*", "?")):
                raise UsageError("DeHashed rejects leading wildcards in domain searches")
            wildcard = True
        if not raw or any(ch.isspace() for ch in raw):
            raise UsageError(f"invalid domain: {value!r}")
        return f"domain:{_field_value('domain', raw)}", wildcard, regex

    if kind in ("password", "phone"):
        return f"{kind}:{_field_value(kind, value)}", wildcard, regex

    if kind == "hashed_password":
        return f"hashed_password:{_safe_value(value)}", wildcard, regex

    if kind == "ip_address":
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:
            raise UsageError(f"not a valid IP address: {value!r}") from exc
        return f"ip_address:{value}", wildcard, regex

    if kind in SEARCH_FIELDS:
        return f"{kind}:{_field_value(kind, value)}", wildcard, regex

    raise UsageError(f"unknown lookup kind: {kind}")


def detect_kind(value: str) -> tuple[str, str]:
    """Best-effort type detection for the `auto` command."""
    value = value.strip()
    if not value:
        raise UsageError("empty value")
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        return "email", value
    try:
        ipaddress.ip_address(value)
        return "ip_address", value
    except ValueError:
        pass
    if re.fullmatch(r"\+?[0-9][0-9 ()\-]{5,}", value):
        return "phone", value
    candidate = value
    if "://" in candidate:
        candidate = urllib.parse.urlsplit(candidate).netloc or candidate
    candidate = candidate.lower().split("/", 1)[0]
    if re.fullmatch(r"(?=.{3,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", candidate):
        return "domain", candidate
    return "raw", value


# ------------------------------------------------------------------- search core
@dataclass
class SearchSpec:
    query: str
    size: int = 100
    page: int = 1
    pages: int = 1
    all_pages: bool = False
    wildcard: bool = False
    regex: bool = False
    de_dupe: bool = False
    max_credits: int = DEFAULT_MAX_CREDITS
    refresh: bool = False


@dataclass
class SearchResult:
    spec: SearchSpec
    entries: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    pages_fetched: int = 0
    live_requests: int = 0
    cached_pages: int = 0
    credits_before: int | None = None
    credits_after: int | None = None
    took: str = ""
    started_at: str = ""
    finished_at: str = ""
    budget_stopped: bool = False


def _validate_spec(spec: SearchSpec) -> None:
    if spec.size < 1 or spec.size > MAX_PAGE_SIZE:
        raise UsageError(f"size must be between 1 and {MAX_PAGE_SIZE}")
    if spec.page < 1:
        raise UsageError("page must be 1 or greater")
    if spec.pages < 1 and not spec.all_pages:
        raise UsageError("pages must be 1 or greater")
    if spec.page * spec.size > MAX_RESULTS:
        raise UsageError(
            f"page*size must be <= {MAX_RESULTS:,} "
            f"(page {spec.page} x size {spec.size} = {spec.page * spec.size:,})"
        )
    if spec.wildcard and spec.regex:
        raise UsageError("wildcard and regex cannot both be true")
    if spec.max_credits < 0:
        raise UsageError("--max-credits must be >= 0")


def run_search(spec: SearchSpec) -> SearchResult:
    _validate_spec(spec)

    status = get_status()
    if not status.get("search_access"):
        raise EntitlementError(
            "Account lacks search access: /v2/info/user reports "
            f"search_access=false with search_credits={status.get('search_credits')}.\n"
            "Credits are unusable until a search subscription is active. "
            "An identifying email header does not change this."
        )

    result = SearchResult(
        spec=spec,
        started_at=iso_now(),
        credits_before=status.get("search_credits"),
        credits_after=status.get("search_credits"),
    )

    page = spec.page
    last_page = spec.page + spec.pages - 1 if not spec.all_pages else MAX_RESULTS
    while page <= last_page:
        if page * spec.size > MAX_RESULTS:
            break

        body = {
            "query": spec.query,
            "page": page,
            "size": spec.size,
            "wildcard": spec.wildcard,
            "regex": spec.regex,
            "de_dupe": spec.de_dupe,
        }
        cached = _cache_read("search", body) if not spec.refresh else None

        if cached is None and result.live_requests >= spec.max_credits:
            result.budget_stopped = True
            if not result.entries:
                raise BudgetError(
                    f"Credit budget exhausted ({spec.max_credits}) before the first live "
                    "request. Re-run with --max-credits N or use cached results."
                )
            eprint(
                f"[!] credit budget reached ({spec.max_credits}); "
                f"stopped after {result.pages_fetched} page(s), {len(result.entries)} entries"
            )
            break

        if cached is not None:
            data = cached["response"]
            result.cached_pages += 1
        else:
            event_id = budget_reserve(
                1, f"search page {page}: {shorten(spec.query, 120)}"
            )
            http_status, data = request(
                "POST", f"{API}/v2/search", body, retries=PAID_RETRIES
            )
            budget_settle(event_id, "ok" if http_status == 200 else f"http_{http_status}")
            if http_status != 200 or not isinstance(data, dict):
                raise ApiError(http_status, api_error_hint(http_status, data), data)
            result.live_requests += 1
            _cache_write("search", body, data)
            try:
                result.credits_after = int(data.get("balance"))
            except (TypeError, ValueError):
                pass
            result.took = str(data.get("took", ""))

        result.pages_fetched += 1
        total = data.get("total")
        if isinstance(total, int):
            result.total = total
        entries = data.get("entries") or []
        if not isinstance(entries, list):
            entries = []
        result.entries.extend(entries)

        if not entries:
            break
        if result.total and page * spec.size >= min(result.total, MAX_RESULTS):
            break
        if len(entries) < spec.size:
            break
        page += 1

    result.finished_at = iso_now()
    if result.live_requests and result.credits_after is None:
        try:
            result.credits_after = get_status().get("search_credits")
        except DeHashedError:
            pass
    return result


def _result_payload(result: SearchResult) -> dict[str, Any]:
    spec = result.spec
    return {
        "meta": {
            "generated_at": result.finished_at or iso_now(),
            "started_at": result.started_at,
            "query": spec.query,
            "wildcard": spec.wildcard,
            "regex": spec.regex,
            "de_dupe": spec.de_dupe,
            "size": spec.size,
            "start_page": spec.page,
            "total": result.total,
            "fetched": len(result.entries),
            "pages_fetched": result.pages_fetched,
            "live_requests": result.live_requests,
            "cached_pages": result.cached_pages,
            "credits_before": result.credits_before,
            "credits_after": result.credits_after,
            "budget_stopped": result.budget_stopped,
            "took": result.took,
            "api": API,
        },
        "entries": result.entries,
    }


# ---------------------------------------------------------------------- output
def _flatten(entry: dict[str, Any]) -> dict[str, str]:
    row: dict[str, str] = {}
    for key in COLUMNS:
        value = entry.get(key)
        if isinstance(value, (list, tuple, set)):
            row[key] = "; ".join(str(v) for v in value)
        elif isinstance(value, dict):
            row[key] = json.dumps(value, ensure_ascii=False)
        elif value is None:
            row[key] = ""
        else:
            row[key] = str(value)
    # Preserve any unexpected fields too.
    for key, value in entry.items():
        if key in row:
            continue
        if isinstance(value, (list, tuple, set)):
            row[key] = "; ".join(str(v) for v in value)
        elif isinstance(value, dict):
            row[key] = json.dumps(value, ensure_ascii=False)
        elif value is not None:
            row[key] = str(value)
    return row


def _write_payload(payload: dict[str, Any], path: str, fmt: str | None) -> None:
    ext = os.path.splitext(path)[1].lower() if path != "-" else ""
    fmt = fmt or (
        "csv" if ext == ".csv" else "ndjson" if ext in (".ndjson", ".jsonl") else "json"
    )

    if path == "-":
        if fmt == "ndjson":
            for entry in payload["entries"]:
                print(json.dumps(entry, ensure_ascii=False))
        elif fmt == "csv":
            rows = [_flatten(e) for e in payload["entries"]]
            fieldnames = list(COLUMNS)
            for row in rows:
                for key in row:
                    if key not in fieldnames:
                        fieldnames.append(key)
            writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        else:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if fmt == "json":
        write_private(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    elif fmt == "ndjson":
        lines = [json.dumps(entry, ensure_ascii=False) for entry in payload["entries"]]
        write_private(path, "\n".join(lines) + ("\n" if lines else ""))
    elif fmt == "csv":
        rows = [_flatten(e) for e in payload["entries"]]
        fieldnames = list(COLUMNS)
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        with private_output(path, newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    else:
        raise UsageError(f"unknown output format: {fmt}")


def _summary(result: SearchResult, *, show: int, reveal: bool, quiet: bool) -> None:
    spec = result.spec
    credits_delta = None
    if isinstance(result.credits_before, int) and isinstance(result.credits_after, int):
        credits_delta = result.credits_before - result.credits_after

    if quiet:
        print(
            f"[=] {len(result.entries)} entries | total {fmt_int(result.total)} | "
            f"live {result.live_requests} | cached {result.cached_pages} | "
            f"credits {result.credits_before} -> {result.credits_after}"
        )
        return

    print(f"[=] query      : {spec.query}")
    flags = []
    if spec.wildcard:
        flags.append("wildcard")
    if spec.regex:
        flags.append("regex")
    if spec.de_dupe:
        flags.append("de_dupe")
    print(f"[=] flags      : {', '.join(flags) if flags else 'none'}")
    print(f"[=] total      : {fmt_int(result.total)}")
    print(
        f"[=] fetched    : {fmt_int(len(result.entries))} entries "
        f"({result.pages_fetched} page(s) x {spec.size})"
    )
    print(
        f"[=] credits    : {result.credits_before} -> {result.credits_after} "
        f"({result.live_requests} live, {result.cached_pages} cached"
        + (f", {credits_delta} spent" if credits_delta is not None else "")
        + ")"
    )
    if result.took:
        print(f"[=] api took   : {result.took}")
    if result.budget_stopped:
        print("[!] stopped early: credit budget reached")

    entries = result.entries
    if not entries:
        print("\n[=] no entries returned. Absence of a hit is not proof of no exposure.")
        return

    db_counts: Counter[str] = Counter()
    emails: set[str] = set()
    domains: set[str] = set()
    usernames: set[str] = set()
    ips: set[str] = set()
    names: set[str] = set()
    phones: set[str] = set()
    plaintext: Counter[str] = Counter()
    plain_entries = 0
    hashed_entries = 0
    neither = 0

    for entry in entries:
        db_counts[str(entry.get("database_name") or "(unknown)")] += 1
        for email in as_list(entry.get("email")):
            email = email.lower()
            emails.add(email)
            if "@" in email:
                domains.add(email.rsplit("@", 1)[1])
        for key, bucket in (
            ("username", usernames), ("ip_address", ips),
            ("name", names), ("phone", phones),
        ):
            bucket.update(as_list(entry.get(key)))
        pws = as_list(entry.get("password"))
        hashes = as_list(entry.get("hashed_password"))
        if pws:
            plain_entries += 1
            plaintext.update(pws)
        elif hashes:
            hashed_entries += 1
        else:
            neither += 1

    print("\n[*] top databases")
    for name, count in db_counts.most_common(10):
        print(f"  {count:>7,}  {shorten(name, 60)}")

    print(
        f"\n[*] unique     : {len(emails):,} emails, {len(domains):,} domains, "
        f"{len(usernames):,} usernames, {len(ips):,} IPs, "
        f"{len(names):,} names, {len(phones):,} phones"
    )
    print(
        f"[*] credentials: {plain_entries:,} with plaintext, {hashed_entries:,} hash-only, "
        f"{neither:,} with neither"
    )
    if plaintext:
        if reveal:
            print("[*] top plaintext passwords (handle as evidence)")
            for password, count in plaintext.most_common(10):
                print(f"  {count:>7,}  {shorten(password, 40)}")
        else:
            print(
                f"[*] passwords  : {len(plaintext):,} unique plaintext values "
                "(masked; use --reveal to show)"
            )

    if show > 0:
        print(f"\n[*] sample (first {min(show, len(entries))} of {fmt_int(len(entries))})")
        header = f"  {'EMAIL':<34} {'USERNAME':<20} {'PASSWORD':<14} {'DATABASE':<28}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for entry in entries[:show]:
            email = as_list(entry.get("email"))
            username = as_list(entry.get("username"))
            pws = as_list(entry.get("password"))
            hashes = as_list(entry.get("hashed_password"))
            if pws:
                pw_cell = mask(pws[0], reveal)
            elif hashes:
                pw_cell = "[hash]"
            else:
                pw_cell = "-"
            print(
                f"  {shorten(email[0] if email else '-', 34):<34} "
                f"{shorten(username[0] if username else '-', 20):<20} "
                f"{pw_cell:<14} "
                f"{shorten(entry.get('database_name') or '-', 28):<28}"
            )
        if len(entries) > show:
            print(f"  ... {fmt_int(len(entries) - show)} more in the export")


def cmd_search(args: argparse.Namespace) -> int:
    raw_query = args.query
    query, web_wildcard, web_regex = _strip_web_suffixes(raw_query)
    wildcard = bool(getattr(args, "wildcard", False) or web_wildcard)
    regex = bool(getattr(args, "regex", False) or web_regex)
    if wildcard and regex:
        raise UsageError("wildcard and regex are mutually exclusive")
    if not query:
        raise UsageError("empty query")
    if "&data=" in query:
        raise UsageError(
            "the &data=<origin> filter is part of the web UI syntax and returns "
            "400 through the v2 API. Filter on database_name in the results instead."
        )

    spec = SearchSpec(
        query=query,
        size=args.size,
        page=args.page,
        pages=args.pages,
        all_pages=args.all,
        wildcard=wildcard,
        regex=regex,
        de_dupe=bool(args.dedupe),
        max_credits=args.max_credits,
        refresh=args.refresh,
    )
    _validate_spec(spec)

    if args.dry_run:
        status = get_status()
        print(f"[=] query      : {query}")
        print(f"[=] body       : {json.dumps({'query': query, 'page': spec.page, 'size': spec.size, 'wildcard': wildcard, 'regex': regex, 'de_dupe': spec.de_dupe})}")
        print(f"[=] pages      : {'all' if spec.all_pages else spec.pages}")
        print(f"[=] max credits: {spec.max_credits}")
        print(f"[=] entitlement: search_access={status.get('search_access')} "
              f"search_credits={status.get('search_credits')} "
              f"whois_credits={status.get('whois_credits')}")
        return 0

    result = run_search(spec)
    payload = _result_payload(result)

    if args.print_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        if args.out:
            _write_payload(payload, args.out, args.format)
        return 0

    _summary(result, show=args.show, reveal=args.reveal, quiet=args.quiet)
    if args.out:
        _write_payload(payload, args.out, args.format)
        print(f"[+] wrote {len(result.entries):,} entries -> {args.out}")
    return 0


def cmd_lookup(args: argparse.Namespace, kind: str, value: str) -> int:
    query, wildcard, regex = build_query(
        kind,
        value,
        domain=getattr(args, "domain", None),
        wildcard=bool(getattr(args, "wildcard", False)),
        regex=bool(getattr(args, "regex", False)),
    )
    args.query = query
    args.wildcard = wildcard
    args.regex = regex
    return cmd_search(args)


def cmd_auto(args: argparse.Namespace) -> int:
    kind, value = detect_kind(args.value)
    if not args.quiet:
        eprint(f"[auto] detected {kind}: {value}")
    if kind == "raw":
        args.query = value
        args.wildcard = False
        args.regex = False
        return cmd_search(args)
    return cmd_lookup(args, kind, value)


# ------------------------------------------------------------- password checks
def pw_check(password: str, *, refresh: bool = False) -> tuple[dict[str, Any], bool]:
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    body = {"sha256_hashed_password": digest}
    cached = None if refresh else _cache_read("pw", body)
    if cached is not None:
        return cached["response"], True
    status, data = request("POST", f"{API}/v2/search-password", body)
    if status != 200 or not isinstance(data, dict):
        raise ApiError(status, api_error_hint(status, data), data)
    _cache_write("pw", body, data)
    return data, False


def cmd_pw(args: argparse.Namespace) -> int:
    data, cached = pw_check(args.password, refresh=args.refresh)
    count = data.get("results_found", data)
    print(f"[{'cache' if cached else 'live'}] {args.password!r} -> results_found={count}")
    if args.out:
        write_private(
            args.out,
            json.dumps(
                {"password": args.password, "results_found": count, "cached": cached},
                indent=2,
            )
            + "\n",
        )
        print(f"[+] wrote {args.out}")
    return 0


def cmd_pw_batch(args: argparse.Namespace) -> int:
    try:
        with open(args.file, encoding="utf-8") as fh:
            candidates = [
                line.rstrip("\n") for line in fh
                if line.strip() and not line.lstrip().startswith("#")
            ]
    except OSError as exc:
        raise UsageError(f"cannot read {args.file}: {exc}") from exc
    if not candidates:
        raise UsageError(f"no candidates in {args.file}")
    print(f"[*] {len(candidates)} candidate(s); /v2/search-password is free\n")
    rows = []
    for password in candidates:
        data, cached = pw_check(password, refresh=args.refresh)
        count = data.get("results_found", data)
        rows.append({"password": password, "results_found": count, "cached": cached})
        print(f"  {'cache' if cached else 'live ':<5} {password:<32} {count}")
    if args.out:
        write_private(args.out, json.dumps(rows, indent=2) + "\n")
        print(f"\n[+] wrote {args.out}")
    return 0


# ------------------------------------------------------------------ data wells
def _load_wells_cache() -> dict[str, Any] | None:
    if not os.path.exists(WELLS_CACHE):
        return None
    try:
        with open(WELLS_CACHE, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return {"fetched_at": None, "total": len(data), "data_wells": data}
        if isinstance(data, dict) and "data_wells" in data:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def cmd_wells(args: argparse.Namespace) -> int:
    if args.max_pages < 0:
        raise UsageError("--max-pages must be >= 0")
    cached = None if args.refresh else _load_wells_cache()
    if cached is not None and cached.get("complete", True):
        wells = cached.get("data_wells", [])
        print(f"[cache] {len(wells):,} data wells from {WELLS_CACHE} "
              f"(fetched {cached.get('fetched_at') or 'unknown'})")
        return 0

    all_wells: list[dict[str, Any]] = []
    page = 1
    total = None
    complete = True
    while True:
        status, data = request(
            "GET", f"{API}/data-wells?count=50&page={page}&sort=added-DESC"
        )
        if status != 200 or not isinstance(data, dict):
            raise ApiError(status, api_error_hint(status, data), data)
        if total is None:
            total = data.get("total")
            print(f"[*] {fmt_int(total)} data wells reported; sweeping (free)")
        batch = data.get("data_wells") or []
        all_wells.extend(batch)
        if not data.get("next_page") or not batch:
            break
        page += 1
        if args.max_pages and page > args.max_pages:
            print(f"[!] stopped at --max-pages {args.max_pages}")
            complete = False
            break
        if page % 50 == 0:
            print(f"    ... {len(all_wells):,} fetched")

    ensure_private_dir(CACHE_DIR)
    wrapper = {
        "fetched_at": iso_now(),
        "total": total,
        "count": len(all_wells),
        "complete": complete,
        "data_wells": all_wells,
    }
    write_private(WELLS_CACHE, json.dumps(wrapper, indent=1))
    print(f"[+] cached {len(all_wells):,} data wells -> {WELLS_CACHE}")
    return 0


def cmd_wells_grep(args: argparse.Namespace) -> int:
    cached = _load_wells_cache()
    if cached is None:
        raise UsageError("No cached data-well sweep. Run: dehashed.py wells")
    keywords = [k.lower() for k in args.keywords if k.strip()]
    if not keywords:
        raise UsageError("no keywords given")
    if not cached.get("complete", True):
        eprint("[!] cached data-well sweep is partial; results may be incomplete")
    wells = cached.get("data_wells", [])
    hits = []
    seen: set[str] = set()
    for well in wells:
        fingerprint = json.dumps(well, sort_keys=True, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        fields = {
            "name": str(well.get("name") or "").lower(),
            "desc": str(well.get("description") or "").lower(),
            "data": str(well.get("data") or "").lower(),
        }
        if args.name_only:
            fields = {"name": fields["name"]}
        matched = []
        for keyword in keywords:
            for location, blob in fields.items():
                if keyword in blob:
                    matched.append(f"{keyword}:{location}")
                    break
        if matched:
            hits.append((matched, well))
    print(f"[*] {len(wells):,} cached wells ({len(seen):,} unique); "
          f"{len(hits)} match(es) for {', '.join(keywords)}"
          + (" (name only)" if args.name_only else ""))
    for matched, well in hits:
        print(
            f"  [{','.join(matched)}] {well.get('name')} | {well.get('date')} | "
            f"{fmt_int(well.get('records'))} records | "
            f"sensitive={well.get('is_sensitive')}"
        )
    if args.out:
        write_private(
            args.out,
            json.dumps([{"keywords": m, "well": w} for m, w in hits], indent=2) + "\n",
        )
        print(f"[+] wrote {args.out}")
    return 0


# ----------------------------------------------------------------------- WHOIS
def cmd_whois(args: argparse.Namespace) -> int:
    search_type = args.whois_type
    cost = WHOIS_COSTS[search_type]

    status = get_status()
    credits = status.get("whois_credits")
    if not isinstance(credits, int):
        credits = get_whois_credits()
    if isinstance(credits, int) and credits < cost:
        raise EntitlementError(
            f"WHOIS operation '{search_type}' costs {cost} credit(s), "
            f"but whois_credits={credits}. Top up WHOIS credits before retrying."
        )
    if cost > args.max_credits:
        raise BudgetError(
            f"'{search_type}' costs {cost} credit(s), above --max-credits "
            f"{args.max_credits}. Re-run with --max-credits {cost}."
        )
    if cost > 1 and not args.yes:
        raise UsageError(
            f"'{search_type}' costs {cost} credits. Re-run with --yes to confirm."
        )

    body: dict[str, Any] = {"search_type": search_type}
    if search_type == "reverse-whois":
        include = args.include or []
        exclude = args.exclude or []
        if not include and not exclude:
            raise UsageError("reverse-whois needs at least one --include or --exclude term")
        if len(include) > 4 or len(exclude) > 4:
            raise UsageError("reverse-whois accepts at most 4 include and 4 exclude terms")
        body.update(
            {
                "include": include,
                "exclude": exclude,
                "reverse_type": args.reverse_type,
            }
        )
    else:
        body["domain"] = args.domain
        if not args.domain:
            raise UsageError("this WHOIS operation needs a domain/IP/host value")

    detail = getattr(args, "domain", None)
    if not detail:
        detail = ",".join(
            getattr(args, "include", []) or getattr(args, "exclude", []) or []
        )
    activity = f"whois {search_type}: {detail}"
    event_id = budget_reserve(cost, shorten(activity, 120))
    http_status, data = request(
        "POST", f"{API}/v2/whois/search", body, retries=PAID_RETRIES
    )
    budget_settle(event_id, "ok" if http_status == 200 else f"http_{http_status}")
    if http_status != 200:
        raise ApiError(http_status, api_error_hint(http_status, data), data)

    print(json.dumps(data, indent=2, ensure_ascii=False))
    if args.out:
        write_private(args.out, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"[+] wrote {args.out}")
    remaining = get_whois_credits()
    if remaining is not None:
        print(f"[=] whois_credits remaining: {remaining}", file=sys.stderr)
    return 0


# ------------------------------------------------------------------ monitoring
def cmd_monitor(args: argparse.Namespace) -> int:
    method = "POST"
    path = ""
    body: dict[str, Any] = {}

    if args.monitor_cmd == "tasks":
        path, body = "/v2/monitoring/get-tasks", {"page": args.page}
    elif args.monitor_cmd == "task":
        path, body = "/v2/monitoring/get-task", {"id": args.id}
    elif args.monitor_cmd == "create":
        path, body = "/v2/monitoring/create-task", {"type": args.type, "value": args.value}
    elif args.monitor_cmd == "update":
        path = "/v2/monitoring/update-task"
        body = {"id": args.id}
        if args.type:
            body["type"] = args.type
        if args.value:
            body["value"] = args.value
        if args.active is not None:
            body["active"] = args.active
        if len(body) == 1:
            raise UsageError("update needs --type, --value and/or --active")
    elif args.monitor_cmd == "delete":
        path, body = "/v2/monitoring/delete-task", {"id": args.id}
    elif args.monitor_cmd == "reports":
        path, body = "/v2/monitoring/get-reports", {"page": args.page}
    elif args.monitor_cmd == "report":
        path, body = "/v2/monitoring/get-report", {"id": args.id}
    elif args.monitor_cmd == "channels":
        path, body = "/v2/monitoring/get-channels", {}
    elif args.monitor_cmd == "set-channel":
        path, body = "/v2/monitoring/update-channel", {"type": args.type, "value": args.value}
    elif args.monitor_cmd == "delete-channel":
        path, body = "/v2/monitoring/delete-channel", {"channel": args.channel}
    elif args.monitor_cmd == "domains":
        method, path = "GET", "/v2/monitoring/get-domains"
    elif args.monitor_cmd == "update-domain":
        path, body = "/v2/monitoring/update-domain", {"id": args.id, "domain": args.domain}
    elif args.monitor_cmd == "clear-domain":
        path, body = "/v2/monitoring/clear-domain", {"id": args.id}
    else:
        raise UsageError(f"unknown monitor command: {args.monitor_cmd}")

    mutating = args.monitor_cmd in {
        "create", "update", "delete", "set-channel", "delete-channel",
        "update-domain", "clear-domain",
    }
    if mutating and not args.yes:
        raise UsageError(
            f"monitor {args.monitor_cmd} changes account state. Re-run with --yes."
        )

    http_status, data = request(method, f"{API}{path}", body if method != "GET" else None)
    if http_status != 200:
        raise ApiError(http_status, api_error_hint(http_status, data), data)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    if args.out:
        write_private(args.out, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"[+] wrote {args.out}")
    return 0


# ----------------------------------------------------------------------- cache
def cmd_cache(args: argparse.Namespace) -> int:
    if not os.path.isdir(CACHE_DIR):
        print(f"cache dir : {CACHE_DIR}")
        print("entries   : 0")
        return 0
    files = [
        os.path.join(CACHE_DIR, name)
        for name in os.listdir(CACHE_DIR)
        if os.path.isfile(os.path.join(CACHE_DIR, name))
    ]
    if args.clear:
        for path in files:
            try:
                os.remove(path)
            except OSError:
                pass
        print(f"[+] removed {len(files)} cache file(s) from {CACHE_DIR}")
        return 0
    if args.prune is not None:
        cutoff = time.time() - args.prune * 86400
        removed = 0
        for path in files:
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
        print(f"[+] pruned {removed} cache file(s) older than {args.prune} day(s)")
        files = [p for p in files if os.path.exists(p)]
    total = sum(os.path.getsize(p) for p in files)
    print(f"cache dir : {CACHE_DIR}")
    print(f"entries   : {len(files)}")
    print(f"size      : {total / 1024:.1f} KiB")
    if files:
        newest = max(files, key=os.path.getmtime)
        print(f"newest    : {os.path.basename(newest)} "
              f"({datetime.fromtimestamp(os.path.getmtime(newest)).isoformat(timespec='seconds')})")
    return 0


# ------------------------------------------------------------------------ init
def cmd_init(args: argparse.Namespace) -> int:
    check_private_path(KEY_FILE)
    if os.path.exists(KEY_FILE) and not args.force:
        print(f"[=] {KEY_FILE} already exists; not overwriting (use --force to replace)")
        return 0
    if args.from_env:
        key = os.environ.get("DEHASHED_API_KEY", "").strip()
        if not key:
            raise UsageError("--from-env set but $DEHASHED_API_KEY is empty")
    else:
        key = getpass.getpass("DeHashed API key: ").strip()
    key = validate_key(key)
    ensure_private_dir(CONFIG_DIR)
    write_private(KEY_FILE, key + "\n")
    print(f"[+] wrote {KEY_FILE} (mode 600)")
    print("[!] If this key was ever pasted into a chat, ticket or commit, rotate it at DeHashed.")
    return 0


# ------------------------------------------------------------------------ status
def cmd_status(args: argparse.Namespace) -> int:
    data = get_status()
    remaining, spent = budget_remaining()
    if args.json:
        data["_local_budget"] = {
            "daily_cap": DAILY_MAX_CREDITS,
            "reserved_today": spent,
            "remaining_today": remaining,
            "default_per_run": DEFAULT_MAX_CREDITS,
        }
        print(json.dumps(data, indent=2))
        return 0
    access = data.get("search_access")
    search_credits = data.get("search_credits")
    whois_credits = data.get("whois_credits")
    print(f"[=] search_access : {access}")
    print(f"[=] search_credits: {search_credits}")
    print(f"[=] whois_credits : {whois_credits}")
    print(f"[=] daily guard   : {spent}/{DAILY_MAX_CREDITS} credits reserved today "
          f"({remaining} left; local guard, vendor balance above)")
    if os.path.exists(PAUSE_FILE):
        print(f"[=] paid state   : PAUSED ({PAUSE_FILE})")
    elif DEFAULT_MAX_CREDITS == 0:
        print("[=] paid default  : disabled (pass --max-credits N to authorise a spend)")
    else:
        print(f"[=] paid default  : {DEFAULT_MAX_CREDITS} credit(s) per run")
    if not access:
        print("[!] search_access=false: /v2/search will return 401 regardless of credits.")
    if whois_credits == 0:
        print("[!] whois_credits=0: all /v2/whois/* lookups will fail.")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    ensure_private_dir(CONFIG_DIR)
    write_private(PAUSE_FILE, f"paused {iso_now()}\n")
    print(f"[+] all paid calls are paused for every session ({PAUSE_FILE})")
    print("    Free endpoints (status, pw, wells, wells-grep, budget) still work.")
    print("    Resume with: dehashed.py resume")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    if os.path.exists(PAUSE_FILE):
        os.remove(PAUSE_FILE)
        print("[+] paid calls resumed")
        print(f"    per-run default: {DEFAULT_MAX_CREDITS}; "
              f"daily guard: {DAILY_MAX_CREDITS}")
    else:
        print("[=] paid calls were not paused")
    return 0


def cmd_budget(args: argparse.Namespace) -> int:
    if args.last < 0:
        raise UsageError("--last must be >= 0")
    ledger = _ledger_load()
    spent = int(ledger.get("spent", 0))
    remaining = max(0, DAILY_MAX_CREDITS - spent)
    if args.json:
        print(json.dumps(
            {
                "date": ledger.get("date"),
                "daily_cap": DAILY_MAX_CREDITS,
                "reserved": spent,
                "remaining": remaining,
                "default_per_run": DEFAULT_MAX_CREDITS,
                "events": ledger.get("events", [])[-args.last:],
            },
            indent=2,
        ))
        return 0
    print(f"[=] date      : {ledger.get('date')}")
    print(f"[=] daily cap : {DAILY_MAX_CREDITS}")
    print(f"[=] reserved  : {spent} (local reservations only)")
    print(f"[=] remaining : {remaining}")
    print("    The vendor balance in `status` is authoritative.")
    events = ledger.get("events", [])[-args.last:]
    if events:
        print("\n[*] recent paid attempts")
        for event in events:
            print(
                f"  {event.get('at')}  {event.get('credits'):>2}  "
                f"{event.get('status'):<10} {shorten(event.get('activity'), 70)}"
            )
    return 0


# ------------------------------------------------------------------------ parser
def add_search_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--size", type=int, default=100,
                   help="results per page (1-10000; default 100)")
    p.add_argument("--page", type=int, default=1, help="start page (default 1)")
    p.add_argument("--pages", type=int, default=1,
                   help="number of pages to fetch (default 1)")
    p.add_argument("--all", action="store_true",
                   help="fetch sequential pages until total/50k/budget is reached")
    p.add_argument("--max-credits", type=int, default=DEFAULT_MAX_CREDITS,
                   help=f"paid search-page budget for this invocation "
                        f"(default {DEFAULT_MAX_CREDITS}; 0 disables paid calls)")
    p.add_argument("--dedupe", action="store_true",
                   help="de-duplicate across sources (faster to read, but hides which other breaches matched)")
    p.add_argument("--refresh", action="store_true", help="ignore the cache and spend credits")
    p.add_argument("--out", metavar="FILE",
                   help="write full results (json/csv/ndjson inferred from extension; - for stdout)")
    p.add_argument("--format", choices=["json", "csv", "ndjson"], help="force export format")
    p.add_argument("--print-json", action="store_true",
                   help="print the full JSON payload to stdout instead of the summary")
    p.add_argument("--show", type=int, default=20,
                   help="summary table rows (default 20; 0 disables)")
    p.add_argument("--reveal", action="store_true",
                   help="show plaintext passwords in the summary (default masked)")
    p.add_argument("--dry-run", action="store_true",
                   help="validate and print the request without spending credits")
    p.add_argument("--quiet", action="store_true", help="one-line output")


def add_wildcard_options(p: argparse.ArgumentParser) -> None:
    group = p.add_mutually_exclusive_group()
    group.add_argument("--wildcard", action="store_true", help="enable wildcard matching")
    group.add_argument("--regex", action="store_true", help="enable regex matching")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dehashed.py",
        description="DeHashed v2 API client: cached, budgeted, free-first breach lookups.",
        epilog=(
            "Examples:\n"
            "  dehashed.py status\n"
            "  dehashed.py auto alice@example.com --size 100\n"
            "  dehashed.py domain example.com --all --size 1000 --max-credits 5\n"
            "  dehashed.py email-part john --domain example.com --size 100\n"
            "  dehashed.py raw 'email:test*&domain:example.com' --wildcard --size 100\n"
            "  dehashed.py pw '<candidate-password>'\n"
            "  dehashed.py wells-grep example\n"
            "  dehashed.py whois example.com\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="entitlement + credit balance (free)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("budget", help="show today's local spend guard (free)")
    s.add_argument("--json", action="store_true")
    s.add_argument("--last", type=int, default=20, help="recent attempts to show")
    s.set_defaults(func=cmd_budget)

    s = sub.add_parser("pause", help="pause all paid calls for every session (free)")
    s.set_defaults(func=cmd_pause)

    s = sub.add_parser("resume", help="resume paid calls (free)")
    s.set_defaults(func=cmd_resume)

    s = sub.add_parser("init", help="store the API key in ~/.config/dehashed/api_key")
    s.add_argument("--from-env", action="store_true", help="read $DEHASHED_API_KEY")
    s.add_argument("--force", action="store_true", help="overwrite an existing key file")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("auto", help="detect email/domain/IP/phone and look it up")
    s.add_argument("value")
    add_search_options(s)
    s.set_defaults(func=cmd_auto)

    PASSWORD_HELP = 'plaintext password (paid; use pw for the free corpus count)'
    lookup_help = {
        "email": "exact email address (quoted automatically)",
        "email-part": "email local-part prefix or pattern (e.g. john, john*, joh?n)",
        "domain": "all records for a domain",
        "username": "username",
        "password": PASSWORD_HELP,
        "hash": "hashed password",
        "name": "full name",
        "phone": "phone number",
        "ip": "IP address",
        "address": "physical address",
        "company": "company name",
        "vin": "vehicle identification number",
    }
    for name, helptext in lookup_help.items():
        s = sub.add_parser(name, help=helptext)
        s.add_argument("value")
        add_search_options(s)
        if name in ("email-part", "username"):
            s.add_argument("--domain", help="AND the query with domain:<value>")
        if name in ("email-part", "domain", "username", "password", "name",
                    "address", "company", "vin"):
            add_wildcard_options(s)
        s.set_defaults(func=None, lookup_name=name)

    s = sub.add_parser("raw", help="pass a full DeHashed query through")
    s.add_argument("query")
    add_search_options(s)
    add_wildcard_options(s)
    s.add_argument("--domain", help="AND the query with domain:<value>")
    s.set_defaults(func=cmd_search, query_direct=True)

    s = sub.add_parser("pw", help="free SHA-256 password exposure count")
    s.add_argument("password")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--out")
    s.set_defaults(func=cmd_pw)

    s = sub.add_parser("pw-batch", help="free bulk password exposure check")
    s.add_argument("file")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--out")
    s.set_defaults(func=cmd_pw_batch)

    s = sub.add_parser("wells", help="sweep data wells (free, cached)")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--max-pages", type=int, default=0, help="stop early (testing)")
    s.set_defaults(func=cmd_wells)

    s = sub.add_parser("wells-grep", help="offline grep of the cached data-well sweep")
    s.add_argument("keywords", nargs="+")
    s.add_argument("--name-only", action="store_true",
                   help="match only the breach name, not descriptions/columns")
    s.add_argument("--out")
    s.set_defaults(func=cmd_wells_grep)

    s = sub.add_parser("whois", help="WHOIS lookup for a domain (1 credit)")
    s.add_argument("domain")
    add_whois_common(s)
    s.set_defaults(func=cmd_whois, whois_type="whois")

    s = sub.add_parser("whois-history", help="WHOIS history (25 credits)")
    s.add_argument("domain")
    add_whois_common(s)
    s.set_defaults(func=cmd_whois, whois_type="whois-history")

    s = sub.add_parser("whois-ip", help="reverse WHOIS for an IP")
    s.add_argument("domain")
    add_whois_common(s)
    s.set_defaults(func=cmd_whois, whois_type="reverse-ip")

    s = sub.add_parser("whois-mx", help="domains using an MX host")
    s.add_argument("domain")
    add_whois_common(s)
    s.set_defaults(func=cmd_whois, whois_type="reverse-mx")

    s = sub.add_parser("whois-ns", help="domains using a nameserver")
    s.add_argument("domain")
    add_whois_common(s)
    s.set_defaults(func=cmd_whois, whois_type="reverse-ns")

    s = sub.add_parser("whois-subdomains", help="subdomain scan via WHOIS")
    s.add_argument("domain")
    add_whois_common(s)
    s.set_defaults(func=cmd_whois, whois_type="subdomain-scan")

    s = sub.add_parser("whois-reverse", help="reverse WHOIS by include/exclude terms")
    s.add_argument("--include", action="append", default=[], help="term to include (max 4)")
    s.add_argument("--exclude", action="append", default=[], help="term to exclude (max 4)")
    s.add_argument("--reverse-type", choices=["current", "historic"], default="current")
    s.add_argument("--max-credits", type=int, default=DEFAULT_MAX_CREDITS)
    s.add_argument("--yes", action="store_true")
    s.add_argument("--out")
    s.set_defaults(func=cmd_whois, whois_type="reverse-whois", domain=None)

    m = sub.add_parser("monitor", help="monitoring tasks, reports, channels, domains")
    msub = m.add_subparsers(dest="monitor_cmd", required=True)

    mm = msub.add_parser("tasks", help="list monitoring tasks")
    mm.add_argument("--page", type=int, default=1)
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    mm = msub.add_parser("task", help="get one monitoring task")
    mm.add_argument("--id", required=True)
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    mm = msub.add_parser("create", help="create a monitoring task (needs --yes)")
    mm.add_argument("--type", required=True, choices=["email", "username", "phone", "name"])
    mm.add_argument("--value", required=True)
    mm.add_argument("--yes", action="store_true")
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    mm = msub.add_parser("update", help="update a monitoring task (needs --yes)")
    mm.add_argument("--id", required=True)
    mm.add_argument("--type", choices=["email", "username", "phone", "name"])
    mm.add_argument("--value")
    mm.add_argument("--active", type=lambda x: x.lower() in ("1", "true", "yes", "on"))
    mm.add_argument("--yes", action="store_true")
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    mm = msub.add_parser("delete", help="delete a monitoring task (needs --yes)")
    mm.add_argument("--id", required=True)
    mm.add_argument("--yes", action="store_true")
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    mm = msub.add_parser("reports", help="list reports")
    mm.add_argument("--page", type=int, default=1)
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    mm = msub.add_parser("report", help="get one report")
    mm.add_argument("--id", required=True)
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    mm = msub.add_parser("channels", help="list notification channels")
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    mm = msub.add_parser("set-channel", help="set a webhook/email channel (needs --yes)")
    mm.add_argument("--type", required=True, choices=["webhook", "email"])
    mm.add_argument("--value", required=True)
    mm.add_argument("--yes", action="store_true")
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    mm = msub.add_parser("delete-channel", help="delete a channel (needs --yes)")
    mm.add_argument("--channel", required=True, choices=["webhook", "email"])
    mm.add_argument("--yes", action="store_true")
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    mm = msub.add_parser("domains", help="list monitoring domains")
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    mm = msub.add_parser("update-domain", help="update a monitoring domain (needs --yes)")
    mm.add_argument("--id", required=True)
    mm.add_argument("--domain", required=True)
    mm.add_argument("--yes", action="store_true")
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    mm = msub.add_parser("clear-domain", help="reset a domain task (needs --yes)")
    mm.add_argument("--id", required=True)
    mm.add_argument("--yes", action="store_true")
    mm.add_argument("--out")
    mm.set_defaults(func=cmd_monitor)

    c = sub.add_parser("cache", help="inspect, prune or clear the local cache")
    c.add_argument("--clear", action="store_true")
    c.add_argument("--prune", type=int, metavar="DAYS")
    c.set_defaults(func=cmd_cache)

    return p


def add_whois_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--max-credits", type=int, default=DEFAULT_MAX_CREDITS)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--out")


# ------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        # Reject unsafe destinations before authentication, queries, or spending.
        for location in (CONFIG_DIR, KEY_FILE, CACHE_DIR):
            check_private_path(location)
        output = getattr(args, "out", None)
        if output and output != "-":
            check_private_path(output)
        if getattr(args, "lookup_name", None):
            kind = LOOKUP_KINDS[args.lookup_name]
            return cmd_lookup(args, kind, args.value)
        if getattr(args, "query_direct", False):
            if getattr(args, "domain", None):
                args.query = _append_domain(args.query, args.domain)
            return cmd_search(args)
        return args.func(args)
    except BrokenPipeError:
        return 1
    except DeHashedError as exc:
        eprint(f"[!] {exc}")
        return exc.exit_code
    except OSError as exc:
        eprint(f"[!] filesystem error: {exc}")
        return 3
    except KeyboardInterrupt:
        eprint("\n[!] interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
