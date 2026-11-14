"""Resumable, serial Google research for battery models without a pinout.

Research only: pip install playwright, then use the installed Google Chrome.
An isolated browser profile and SQLite queue live in build/battery-pinout-search.
Search results and AI summaries are leads, never automatic wiring assignments.
"""
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import sys
import time
from urllib.parse import parse_qs, urlencode, urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "build/battery-pinout-search"
DEFAULT_CATALOG = ROOT / "app/assets/battery_catalog.json"
UNKNOWN_BRANDS = {"", "unknown", "unspecified", "generic"}
TECHNICAL = re.compile(r"pin\s*[- ]?out|pin\s*assignment|connector\s*(?:diagram|layout)|"
                       r"schematic|распинов|schaltplan|belegung|pinagem|brochage|"
                       r"\bsda\b|\bscl\b|\bsmbus\b", re.I)
RETAIL = re.compile(r"\b(?:ebay|amazon|aliexpress|shopee|ubuy)\.", re.I)


def normalized(value):
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def utc_text(stamp=None):
    return datetime.fromtimestamp(time.time() if stamp is None else stamp, timezone.utc).isoformat(timespec="seconds")


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    temporary.replace(path)


def query_for(brand, model):
    return f'{brand} "{model}" battery pinout'


def identity_key(brand, model):
    return hashlib.sha256((normalized(brand) + "|" + normalized(model)).encode()).hexdigest()[:20]


def eligible_models(entries, first=()):
    """Balance brands, prefer named/current models, and omit unidentified brands."""
    requested = {normalized(value): index for index, value in enumerate(first)}
    groups = defaultdict(list)
    seen = set()
    for entry in entries:
        if entry.get("pins") or entry["manufacturer"].strip().casefold() in UNKNOWN_BRANDS:
            continue
        key = identity_key(entry["manufacturer"], entry["model"])
        if key in seen:
            continue
        seen.add(key)
        groups[entry["manufacturer"]].append(entry)
    ordered = []
    for brand in groups:
        groups[brand] = deque(sorted(groups[brand], key=lambda e: (
            {"forum_reference":0, "model":1, "part_number":2, "supplier_reference":3}.get(e.get("identity_kind"), 4),
            e["model"].casefold())))
    while any(groups.values()):
        for brand in sorted(groups, key=str.casefold):
            if groups[brand]:
                ordered.append(groups[brand].popleft())
    ordered.sort(key=lambda e: requested.get(normalized(e["model"]), len(requested)))
    return ordered


def google_host(host):
    host = (host or "").casefold()
    return host.endswith(".google.com") or host.removeprefix("www.") in {
        "google.com", "google.ro", "google.co.uk", "google.de", "google.fr", "google.it", "google.es"}


def unpack_result_url(url):
    """Keep opaque Google redirects as unresolved, rather than calling them sources."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ""
    if not google_host(parsed.hostname):
        return url
    if parsed.path == "/url":
        values = parse_qs(parsed.query)
        target = values.get("q", values.get("url", [""]))[0]
        external = urlparse(target)
        if external.scheme in ("http", "https") and not google_host(external.hostname):
            return target
    return ""


def classify_result(result, model):
    text = result.get("title", "") + " " + result.get("snippet", "")
    exact_model = normalized(model) in normalized(text)
    technical = bool(TECHNICAL.search(text))
    host = urlparse(result.get("url", "")).hostname or result.get("display_url", "")
    retail = bool(RETAIL.search(host))
    path_parts = [part for part in urlparse(result.get("url", "")).path.split("/") if part]
    forum_index = host.endswith("laptopu.ro") and len(path_parts) <= 2 and path_parts[:1] == ["community"]
    lead = technical and not retail and not forum_index
    return {**result, "exact_model_mentioned":exact_model, "technical_lead":lead,
            "source_kind":"forum_index" if forum_index else "retail" if retail else "page",
            "review_state":"unreviewed" if lead else "no_pinout_evidence"}


def ai_mapping_hint(text):
    return bool(re.search(r"\b(?:pin|contact)\s*[#:]?\s*\d+|\b[CD]\d+\b", text, re.I))


def classify_page(snapshot, expected_query, http_status=200):
    url = urlparse(snapshot.get("url", ""))
    text = snapshot.get("text", "")
    lower = text.casefold()
    if http_status == 429:
        return "rate_limited"
    if url.path.startswith("/sorry") or "our systems have detected unusual traffic" in lower or snapshot.get("captcha"):
        return "needs_verification"
    if (url.hostname or "").startswith("consent.google.") or "before you continue to google" in lower:
        return "needs_consent"
    if http_status and http_status >= 400:
        return "http_error"
    if not google_host(url.hostname) or url.path != "/search" or parse_qs(url.query).get("q", [""])[0] != expected_query:
        return "unexpected_page"
    if snapshot.get("results"):
        return "searched"
    if any(marker in lower for marker in ("did not match any documents", "no results found for", "nu a găsit niciun document")):
        return "searched"
    # Missing DOM results are not proof that a battery has no public pinout.
    return "unparsed_page"


def make_result(snapshot, job, captured_at=None):
    links = []
    seen = set()
    for raw in snapshot.get("results", []):
        raw_url = raw.get("url", "")
        title = raw.get("title", "").strip()
        if not title or raw_url in seen:
            continue
        seen.add(raw_url)
        url = unpack_result_url(raw_url)
        links.append(classify_result({"title":title, "url":url, "redirect_url":raw_url if not url else "",
            "display_url":raw.get("display_url", ""), "snippet":raw.get("snippet", "")[:1800]}, job["model"]))
    text = re.sub(r"IP address:[^\n]*", "IP address: [redacted]", snapshot.get("text", ""))
    overview = ""
    marker = re.search(r"AI Overview|Prezentare generală generată de AI", text, re.I)
    if marker:
        overview = re.split(r"\n(?:Web results|Rezultate web)\n", text[marker.end():], maxsplit=1)[0][:10000]
    citations = []
    for raw in snapshot.get("citations", []):
        url = unpack_result_url(raw.get("url", ""))
        if not url and not (google_host(urlparse(raw.get("url", "")).hostname)
                            and urlparse(raw.get("url", "")).path in ("/goto", "/url")):
            continue
        citations.append({"title":raw.get("title", "")[:300], "url":url,
            "redirect_url":raw.get("url", "") if not url else "", "verified_source":False})
    hint = ai_mapping_hint(overview)
    return {"provider":"google", "state":"searched", "query":job["query"], "brand":job["brand"],
        "model":job["model"], "catalog_id":job["catalog_id"], "captured_at":utc_text(captured_at),
        "search_url":"https://www.google.com/search?" + urlencode({"q":job["query"], "hl":"en"}),
        "results":links, "ai_overview_hint":overview, "ai_mapping_hint":hint, "ai_citations":citations,
        "technical_leads":sum(link["technical_lead"] for link in links),
        "verified_pinout":False, "review_state":"unreviewed" if any(x["technical_lead"] for x in links)
        else "ai_hint_unverified" if hint else "no_pinout_evidence"}


class Queue:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / "queue.sqlite", timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, catalog_id TEXT, brand TEXT, model TEXT, query TEXT,
              priority INTEGER, active INTEGER DEFAULT 1, state TEXT DEFAULT 'pending',
              attempts INTEGER DEFAULT 0, last_attempt REAL, completed_at REAL,
              result_file TEXT, technical_leads INTEGER DEFAULT 0, review_state TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, job_id TEXT, stamp REAL, outcome TEXT);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))
        self.db.commit()

    def initialize(self, entries, first=()):
        targets = eligible_models(entries, first)
        self.db.execute("UPDATE jobs SET active=0")
        for priority, entry in enumerate(targets):
            key = identity_key(entry["manufacturer"], entry["model"])
            self.db.execute("""INSERT INTO jobs(id,catalog_id,brand,model,query,priority,active)
                VALUES (?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET active=1,
                catalog_id=excluded.catalog_id,priority=excluded.priority""",
                (key, entry["id"], entry["manufacturer"], entry["model"],
                 query_for(entry["manufacturer"], entry["model"]), priority))
        self.db.commit()
        return len(targets)

    def next_job(self):
        row = self.db.execute("SELECT * FROM jobs WHERE active=1 AND state='pending' ORDER BY priority LIMIT 1").fetchone()
        return dict(row) if row else None

    def find_job(self, brand, model):
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (identity_key(brand, model),)).fetchone()
        return dict(row) if row else None

    def begin(self, job, now):
        self.db.execute("UPDATE jobs SET state='working',attempts=attempts+1,last_attempt=?,error=NULL WHERE id=?", (now, job["id"]))
        self.db.execute("INSERT INTO requests(job_id,stamp,outcome) VALUES (?,?,'started')", (job["id"], now))
        self.db.commit()

    def finish(self, job, result, now):
        result["research_schema"] = 1
        result["results"] = [classify_result(link, job["model"]) for link in result["results"]]
        result["technical_leads"] = sum(link["technical_lead"] for link in result["results"])
        result["ai_mapping_hint"] = ai_mapping_hint(result.get("ai_overview_hint", ""))
        if result.get("review_state") != "approved_imported":
            result["review_state"] = ("unreviewed" if result["technical_leads"] else
                                      "ai_hint_unverified" if result["ai_mapping_hint"] else "no_pinout_evidence")
        filename = "results/" + job["id"] + ".json"
        save_json(self.directory / filename, result)
        self.db.execute("""UPDATE jobs SET state='searched',completed_at=?,result_file=?,technical_leads=?,
            review_state=?,error=NULL WHERE id=?""", (now, filename, result["technical_leads"], result["review_state"], job["id"]))
        self.db.execute("UPDATE requests SET outcome='searched' WHERE id=(SELECT MAX(id) FROM requests WHERE job_id=?)", (job["id"],))
        self.db.commit()

    def fail(self, job, state, error, snapshot=None, retry_search=True):
        if retry_search:
            self.db.execute("UPDATE jobs SET state='pending',error=? WHERE id=?", (error, job["id"]))
            self.db.execute("UPDATE requests SET outcome=? WHERE id=(SELECT MAX(id) FROM requests WHERE job_id=?)", (state, job["id"]))
        else:
            self.db.execute("UPDATE jobs SET error=? WHERE id=?", (error, job["id"]))
        self.db.commit()
        self.set("paused", {"reason":state, "job_id":job["id"], "error":error,
                            "url":(snapshot or {}).get("url", ""),
                            "result_index":(snapshot or {}).get("result_index"),
                            "scope":"search" if retry_search else "source_link", "at":utc_text()})
        if state == "rate_limited":
            self.set("next_request_at", max(self.get("next_request_at", 0) or 0, time.time() + 3600))

    def recover(self):
        self.db.execute("UPDATE jobs SET state='pending' WHERE state='working'")
        self.db.commit()
        for job in self.db.execute("SELECT * FROM jobs WHERE state='pending'").fetchall():
            path = self.directory / "results" / (job["id"] + ".json")
            if not path.exists():
                continue
            result = json.loads(path.read_text(encoding="utf8"))
            if result.get("state") == "searched" and result.get("query") == job["query"]:
                self.finish(dict(job), result, path.stat().st_mtime)
        for job in self.db.execute("SELECT * FROM jobs WHERE state='searched'").fetchall():
            path = self.directory / job["result_file"]
            result = json.loads(path.read_text(encoding="utf8"))
            if result.get("research_schema") != 1:
                self.finish(dict(job), result, job["completed_at"])

    def request_times(self, now):
        return [row[0] for row in self.db.execute("SELECT stamp FROM requests WHERE stamp>? ORDER BY stamp", (now - 86400,))]

    def snapshot(self):
        counts = dict(self.db.execute("SELECT state,COUNT(*) FROM jobs WHERE active=1 GROUP BY state").fetchall())
        leads = self.db.execute("SELECT COALESCE(SUM(technical_leads),0) FROM jobs WHERE active=1 AND review_state='unreviewed'").fetchone()[0]
        result = {"updated_at":utc_text(), "total":sum(counts.values()), "states":counts,
            "searches_completed":self.db.execute("SELECT COUNT(*) FROM jobs WHERE state='searched'").fetchone()[0],
            "technical_leads_awaiting_review":leads,
            "ai_hints_awaiting_source_review":self.db.execute("SELECT COUNT(*) FROM jobs WHERE active=1 AND review_state='ai_hint_unverified'").fetchone()[0],
            "verified_pinouts_imported":self.db.execute("SELECT COUNT(*) FROM jobs WHERE review_state='approved_imported'").fetchone()[0],
            "worker_pid":self.get("worker_pid"), "worker_state":self.get("worker_state", "idle"),
            "paused":self.get("paused"), "stop_requested":self.get("stop_requested", False),
            "current_job":self.get("current_job"), "next_request_at":self.get("next_request_at"),
            "requests_last_24h":len(self.request_times(time.time())), "settings":self.get("settings")}
        save_json(self.directory / "status.json", result)
        return result


@contextmanager
def worker_lock(directory):
    lock = open(Path(directory) / "worker.lock", "a+b")
    lock.seek(0, 2)
    if lock.tell() == 0:
        lock.write(b"0");lock.flush()
    lock.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise RuntimeError("A search worker or verification window already owns this queue") from None
    try:
        yield
    finally:
        lock.seek(0)
        if os.name == "nt":
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


class GoogleBrowser:
    def __init__(self, directory, headless=False, interactive=False):
        self.directory, self.headless, self.interactive = Path(directory), headless, interactive

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        try:
            self.context = self.playwright.chromium.launch_persistent_context(
                str(self.directory / "browser-profile"), channel="chrome", headless=self.headless,
                viewport={"width":1280, "height":900})
        except Exception:
            self.playwright.stop()
            raise
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        if not self.headless and not self.interactive:
            self.show(False)
        return self

    def show(self, visible):
        if self.headless:
            return
        # Ordinary window visibility, without changing Chrome's identity or policy.
        session = self.context.new_cdp_session(self.page)
        try:
            window = session.send("Browser.getWindowForTarget")
            session.send("Browser.setWindowBounds", {"windowId":window["windowId"],
                "bounds":{"windowState":"normal" if visible else "minimized"}})
            if visible:
                self.page.bring_to_front()
        finally:
            session.detach()

    def __exit__(self, *args):
        try:
            self.context.close()
        finally:
            self.playwright.stop()

    def snapshot(self):
        return self.page.evaluate("""() => ({url:location.href,title:document.title,
            text:(document.body?.innerText || '').slice(0,30000),
            captcha:!!document.querySelector('form#captcha-form'),
            results:Array.from(document.querySelectorAll('a:has(h3)')).slice(0,20).map(a=>{
              const block=a.closest('div.MjjYud') || a.parentElement?.parentElement;
              return {title:a.querySelector('h3').innerText,url:a.href,
                display_url:block?.querySelector('cite')?.innerText || '',
                snippet:(block?.innerText || '').slice(0,1800)};
            }),
            citations:Array.from(document.querySelectorAll('a[href]')).filter(a=>!a.querySelector('h3') &&
                /^https?:/.test(a.href) && a.innerText.trim()).slice(0,160).map(a=>({
                    title:a.innerText.trim().slice(0,300),url:a.href
                }))})""")

    def search(self, job):
        url = "https://www.google.com/search?" + urlencode({"q":job["query"], "hl":"en", "num":10})
        response = self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self.page.wait_for_timeout(3000)
        snapshot = self.snapshot()
        status = response.status if response else None
        return classify_page(snapshot, job["query"], status), snapshot

    def resolve_leads(self, result, limit=2):
        """Resolve only promising opaque Google redirects, without crawling stores."""
        count = 0
        for index, link in enumerate(result["results"]):
            if count >= limit:
                break
            if link["url"] or not link["technical_lead"] or not link["exact_model_mentioned"] or not link["redirect_url"]:
                continue
            count += 1
            self.page.wait_for_timeout(3000)
            response = self.context.request.get(link["redirect_url"], max_redirects=0, timeout=15000)
            location = response.headers.get("location", "")
            if response.status == 429:
                return "rate_limited", {"url":link["redirect_url"]}
            if response.status >= 400:
                return "source_http_error", {"url":link["redirect_url"]}
            if "/sorry/" in location and google_host(urlparse(location).hostname):
                return "needs_verification", {"url":location, "result_index":index}
            if response.status == 200 and "our systems have detected unusual traffic" in response.text().lower():
                return "needs_verification", {"url":link["redirect_url"], "result_index":index}
            candidate = unpack_result_url(location)
            if candidate:
                link["url"] = candidate
                link["redirect_url"] = ""
            else:
                link["resolution_note"] = "Redirect requires source review; no destination was guessed"
        return None

    def verify(self, job, url, seconds=1800, source_link=False, navigate=True, cancelled=lambda:False):
        self.show(True)
        if navigate:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self.page.is_closed() and not cancelled():
            snapshot = self.snapshot()
            if classify_page(snapshot, job["query"]) == "searched":
                return snapshot
            if source_link:
                parsed = urlparse(snapshot["url"])
                if parsed.scheme in ("http", "https") and not google_host(parsed.hostname):
                    return snapshot
            # Only inspect the existing DOM; never repeatedly submit the search.
            self.page.wait_for_timeout(2000)
        return None


def wait_until(queue, target):
    while time.time() < target:
        if queue.get("stop_requested", False):
            return False
        time.sleep(min(1, max(0, target - time.time())))
    return not queue.get("stop_requested", False)


def due_time(queue, now, daily_limit):
    due = max(now, queue.get("next_request_at", 0) or 0)
    times = queue.request_times(now)
    if len(times) >= daily_limit:
        due = max(due, times[-daily_limit] + 86400 + 1)
    return due


def manual_verification(queue, browser, job, args, source_link=False, navigate=False):
    if args.headless or args.verification_timeout <= 0:
        return None
    queue.set("worker_state", "waiting_for_user")
    queue.snapshot()
    snapshot = browser.verify(job, queue.get("paused")["url"], seconds=args.verification_timeout,
        source_link=source_link, navigate=navigate, cancelled=lambda:queue.get("stop_requested", False))
    if snapshot:
        queue.set("paused", None)
        queue.set("next_request_at", max(queue.get("next_request_at", 0), time.time() + args.min_interval))
        queue.set("worker_state", "running")
        browser.show(False)
    return snapshot


def run(queue, args, resume=False):
    if args.min_interval < 60 or args.max_interval < args.min_interval or args.daily_limit < 1:
        raise ValueError("Use an interval of at least 60 seconds, max >= min, and a positive daily limit")
    if args.batch_size < 1 or args.batch_pause < 60:
        raise ValueError("Batch size must be positive and the batch pause at least 60 seconds")
    if args.max_jobs is not None and args.max_jobs < 1:
        raise ValueError("max-jobs must be positive")
    with worker_lock(queue.directory):
        queue.recover()
        if resume:
            queue.set("paused", None)
        if queue.get("paused"):
            print(json.dumps(queue.snapshot(), ensure_ascii=True))
            return 3
        queue.set("stop_requested", False)
        queue.set("worker_pid", os.getpid())
        queue.set("worker_state", "running")
        queue.set("settings", {"provider":"google", "min_interval_seconds":args.min_interval,
            "max_interval_seconds":args.max_interval, "daily_limit":args.daily_limit,
            "batch_size":args.batch_size, "batch_pause_seconds":args.batch_pause,
            "profile":"isolated", "automatic_pinout_import":False})
        session_count = 0
        try:
            with GoogleBrowser(queue.directory, headless=args.headless) as browser:
                while not queue.get("stop_requested", False):
                    job = queue.next_job()
                    if not job:
                        queue.set("worker_state", "all_models_searched")
                        break
                    target = due_time(queue, time.time(), args.daily_limit)
                    queue.set("next_request_at", target)
                    queue.set("worker_state", "waiting" if target > time.time() else "searching")
                    queue.snapshot()
                    if not wait_until(queue, target):
                        break
                    now = time.time()
                    queue.begin(job, now)
                    # Reserve the next slot before doing network I/O, so a crash/restart cannot bypass it.
                    queue.set("next_request_at", now + random.uniform(args.min_interval, args.max_interval))
                    queue.set("worker_state", "searching")
                    queue.set("current_job", {"brand":job["brand"], "model":job["model"]})
                    queue.snapshot()
                    print(utc_text(), "Google:", job["brand"], job["model"], flush=True)
                    try:
                        state, snapshot = browser.search(job)
                    except Exception as exc:
                        queue.fail(job, "browser_error", str(exc)[:1500])
                        queue.set("worker_state", "paused")
                        return 4
                    if state != "searched":
                        queue.fail(job, state, "Google requires attention; no further searches were sent", snapshot)
                        queue.set("worker_state", "paused")
                        try:
                            browser.page.screenshot(path=str(queue.directory / "paused-google.png"))
                        except Exception:
                            pass
                        verified = (manual_verification(queue, browser, job, args)
                                    if state in ("needs_verification", "needs_consent") else None)
                        if not verified:
                            queue.set("worker_state", "paused")
                            return 3
                        snapshot = verified
                    result = make_result(snapshot, job)
                    queue.finish(job, result, time.time())
                    try:
                        attention = browser.resolve_leads(result)
                        queue.finish(job, result, time.time())
                    except Exception as exc:
                        result["source_resolution_note"] = str(exc)[:1000]
                        queue.finish(job, result, time.time())
                        attention = None
                    if attention:
                        queue.fail(job, attention[0], "Source-link resolution requires attention", attention[1], retry_search=False)
                        queue.set("worker_state", "paused")
                        verified = (manual_verification(queue, browser, job, args, source_link=True, navigate=True)
                                    if attention[0] == "needs_verification" else None)
                        if not verified:
                            queue.set("worker_state", "paused")
                            return 3
                        index = attention[1].get("result_index")
                        if index is not None and not google_host(urlparse(verified["url"]).hostname):
                            result["results"][index].update(url=verified["url"], redirect_url="")
                            queue.finish(job, result, time.time())
                    queue.set("current_job", None)
                    session_count += 1
                    if session_count % args.batch_size == 0:
                        queue.set("next_request_at", max(queue.get("next_request_at", 0), time.time() + args.batch_pause))
                    queue.snapshot()
                    if args.max_jobs and session_count >= args.max_jobs:
                        queue.set("worker_state", "batch_complete")
                        break
        except Exception:
            queue.set("worker_state", "worker_error")
            raise
        finally:
            if queue.get("stop_requested", False):
                queue.set("worker_state", "stopped")
            queue.set("worker_pid", None)
            queue.snapshot()
    return 0


def resolve(queue, args):
    with worker_lock(queue.directory):
        paused = queue.get("paused")
        if not paused or paused["reason"] not in ("needs_verification", "needs_consent"):
            raise ValueError("No Google verification/consent page is pending")
        queue.set("stop_requested", False)
        row = queue.db.execute("SELECT * FROM jobs WHERE id=?", (paused["job_id"],)).fetchone()
        job = dict(row)
        queue.set("worker_pid", os.getpid())
        queue.set("worker_state", "waiting_for_user")
        queue.snapshot()
        try:
            with GoogleBrowser(queue.directory, interactive=True) as browser:
                snapshot = browser.verify(job, paused["url"], seconds=args.verification_timeout,
                    source_link=paused.get("scope") == "source_link", cancelled=lambda:queue.get("stop_requested", False))
                if not snapshot:
                    queue.set("worker_state", "paused")
                    return 3
                if job["state"] != "searched":
                    queue.finish(job, make_result(snapshot, job), time.time())
                elif paused.get("result_index") is not None and not google_host(urlparse(snapshot["url"]).hostname):
                    result = json.loads((queue.directory / job["result_file"]).read_text(encoding="utf8"))
                    result["results"][paused["result_index"]].update(url=snapshot["url"], redirect_url="")
                    queue.finish(job, result, time.time())
                queue.set("paused", None)
                queue.set("next_request_at", time.time() + args.min_interval)
                queue.set("worker_state", "ready")
                queue.set("current_job", None)
        finally:
            queue.set("worker_pid", None)
            queue.snapshot()
    return run(queue, args) if args.continue_after else 0


def import_existing(queue, path):
    data = json.loads(Path(path).read_text(encoding="utf8"))
    job = queue.find_job(data["brand"], data["model"])
    if not job or data["query"] != job["query"] or data.get("provider") != "google":
        raise ValueError("Saved search does not match a queued Google model query")
    if job["state"] == "searched":
        return
    snapshot = {"url":data.get("page_url", ""), "text":data.get("text", ""), "results":data.get("results", [])}
    if classify_page(snapshot, job["query"]) != "searched":
        raise ValueError("Only a completed search page can be reused")
    now = time.time()
    queue.begin(job, now)
    queue.finish(job, make_result(snapshot, job), now)
    queue.set("next_request_at", now + 120)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "status", "run", "stop", "resolve", "resume", "import-search"))
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--first", action="append", default=[])
    parser.add_argument("--saved-search", type=Path)
    parser.add_argument("--min-interval", type=float, default=90)
    parser.add_argument("--max-interval", type=float, default=150)
    parser.add_argument("--daily-limit", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--batch-pause", type=float, default=600)
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--verification-timeout", type=int, default=1800,
                        help="Wait for manual verification in the visible Chrome window; 0 pauses immediately")
    parser.add_argument("--continue-after", action="store_true")
    args = parser.parse_args()
    queue = Queue(args.state_dir)
    try:
        if args.command == "init":
            entries = json.loads(args.catalog.read_text(encoding="utf8"))["entries"]
            queue.initialize(entries, args.first)
        elif args.command == "run":
            return run(queue, args)
        elif args.command == "resolve":
            return resolve(queue, args)
        elif args.command == "resume":
            paused = queue.get("paused")
            if paused and paused["reason"] in ("needs_verification", "needs_consent"):
                args.continue_after = True
                return resolve(queue, args)
            return run(queue, args, resume=True)
        elif args.command == "stop":
            queue.set("stop_requested", True)
        elif args.command == "import-search":
            if not args.saved_search:
                parser.error("import-search requires --saved-search")
            with worker_lock(queue.directory):
                import_existing(queue, args.saved_search)
        print(json.dumps(queue.snapshot(), ensure_ascii=True, indent=2))
    finally:
        queue.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
