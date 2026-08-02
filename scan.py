#!/usr/bin/env python3
"""
scan.py - JobRadar scanner engine.

Reads companies.json (the registry) and config.yaml (your filters), fetches every
company's live job board straight from its ATS, keeps only postings that match your
role/field filters, diffs against what it saw last run, PUSHES new matches to your
phone via ntfy, and writes data/jobs.json for the dashboard.

Run:  python scan.py
Env:  NTFY_TOPIC can override config.ntfy_topic (handy for GitHub Secrets).
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys

import requests
import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "jobradar/1.0 (+https://github.com/)"}


# ---------------------------------------------------------------- config/state
def load_config():
    with open(os.path.join(ROOT, "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    cfg["ntfy_topic"] = os.environ.get("NTFY_TOPIC") or cfg.get("ntfy_topic", "")
    cfg.setdefault("ntfy_server", "https://ntfy.sh")
    cfg.setdefault("request_timeout", 20)
    cfg.setdefault("max_new_notifications", 20)
    cfg.setdefault("concurrency", 24)
    cfg.setdefault("github_sources", [])
    for k in ("role_keywords", "field_keywords", "exclude_keywords", "locations"):
        cfg[k] = [str(x).lower() for x in (cfg.get(k) or [])]
    return cfg


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------- ATS fetchers
# Each returns a list of normalized dicts:
#   {id, key, company, title, location, url, ats, posted}
def _coerce_posted(posted):
    """Normalize a posted-date to an ISO string (repos use epoch ints)."""
    if isinstance(posted, (int, float)):
        try:
            return dt.datetime.fromtimestamp(posted, dt.timezone.utc).isoformat()
        except Exception:
            return ""
    return str(posted or "")


def _norm(id_, company, title, location, url, ats, posted):
    company = (company or "").strip()
    title = (title or "").strip()
    # Stable identity across sources: same company+title => same job, so a role
    # found on both its ATS and a GitHub list is de-duped and alerted once.
    key = company.lower() + "|" + re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return {
        "id": f"{ats}:{company}:{id_}",
        "key": key,
        "company": company,
        "title": title,
        "location": (location or "").strip(),
        "url": url,
        "ats": ats,
        "posted": _coerce_posted(posted),
    }


def fetch_greenhouse(s, r, timeout):
    tok = r["token"]
    u = f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs?content=false"
    d = s.get(u, timeout=timeout, headers=UA).json()
    out = []
    for j in d.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append(_norm(j.get("id"), r["company"], j.get("title"), loc,
                         j.get("absolute_url"), "greenhouse", j.get("updated_at")))
    return out


def fetch_lever(s, r, timeout):
    tok = r["token"]
    u = f"https://api.lever.co/v0/postings/{tok}?mode=json"
    d = s.get(u, timeout=timeout, headers=UA).json()
    out = []
    for j in d if isinstance(d, list) else []:
        cats = j.get("categories") or {}
        posted = ""
        if j.get("createdAt"):
            try:
                posted = dt.datetime.fromtimestamp(
                    j["createdAt"] / 1000, dt.timezone.utc).isoformat()
            except Exception:
                posted = ""
        out.append(_norm(j.get("id"), r["company"], j.get("text"),
                         cats.get("location"), j.get("hostedUrl"), "lever", posted))
    return out


def fetch_ashby(s, r, timeout):
    tok = r["token"]
    u = f"https://api.ashbyhq.com/posting-api/job-board/{tok}?includeCompensation=false"
    d = s.get(u, timeout=timeout, headers=UA).json()
    out = []
    for j in d.get("jobs", []):
        url = j.get("jobUrl") or j.get("applyUrl") or ""
        out.append(_norm(j.get("id"), r["company"], j.get("title"),
                         j.get("location"), url, "ashby", j.get("publishedAt")))
    return out


def fetch_smartrecruiters(s, r, timeout):
    tok = r["token"]
    u = f"https://api.smartrecruiters.com/v1/companies/{tok}/postings?limit=100"
    d = s.get(u, timeout=timeout, headers=UA).json()
    out = []
    for j in d.get("content", []):
        loc = j.get("location") or {}
        loc_s = ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
        jid = j.get("id")
        url = f"https://jobs.smartrecruiters.com/{tok}/{jid}"
        out.append(_norm(jid, r["company"], j.get("name"), loc_s, url,
                         "smartrecruiters", j.get("releasedDate")))
    return out


def fetch_workable(s, r, timeout):
    tok = r["token"]
    u = f"https://apply.workable.com/api/v1/widget/accounts/{tok}?details=false"
    d = s.get(u, timeout=timeout, headers=UA).json()
    out = []
    for j in d.get("jobs", []):
        loc = ", ".join(x for x in (j.get("city"), j.get("country")) if x)
        url = j.get("url") or j.get("shortlink") or ""
        out.append(_norm(j.get("shortcode") or j.get("id"), r["company"],
                         j.get("title"), loc, url, "workable", j.get("published_on")))
    return out


def fetch_workday(s, r, timeout):
    tenant, wd, site = r["token"], r.get("wd", "wd1"), r.get("site", "")
    if not site:
        return []
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    u = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
    d = s.post(u, json=body, timeout=timeout,
               headers={**UA, "Accept": "application/json"}).json()
    out = []
    for j in d.get("jobPostings", []):
        path = j.get("externalPath", "")
        url = f"{base}/en-US/{site}{path}" if path else base
        jid = path or (j.get("bulletFields") or [""])[0]
        out.append(_norm(jid, r["company"], j.get("title"),
                         j.get("locationsText"), url, "workday", j.get("postedOn")))
    return out


def fetch_github_source(s, url, timeout):
    """Pull a community listings.json (SimplifyJobs/vanshb03-style) as postings.

    These catch companies that aren't on a scrapable ATS (custom career sites).
    """
    d = s.get(url, timeout=timeout, headers=UA).json()
    out = []
    for p in d if isinstance(d, list) else []:
        if p.get("active") is False or p.get("is_visible") is False:
            continue
        locs = p.get("locations") or []
        loc = ", ".join(locs) if isinstance(locs, list) else str(locs)
        link = p.get("url") or p.get("company_url") or ""
        pid = p.get("id") or link
        out.append(_norm(pid, p.get("company_name"), p.get("title"), loc, link,
                         "github", p.get("date_posted") or p.get("date_updated")))
    return out


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "workable": fetch_workable,
    "workday": fetch_workday,
}


def fetch_board(r, timeout):
    """Fetch one board; never raise. Returns (jobs, ok)."""
    fn = FETCHERS.get(r["ats"])
    if not fn:
        return [], False
    try:
        s = requests.Session()
        return fn(s, r, timeout), True
    except Exception:
        return [], False


# ------------------------------------------------------------------- matching
def matches(title, cfg):
    t = title.lower()
    if not t:
        return False
    if any(x in t for x in cfg["exclude_keywords"]):
        return False
    if cfg["role_keywords"] and not any(x in t for x in cfg["role_keywords"]):
        return False
    if cfg["field_keywords"] and not any(x in t for x in cfg["field_keywords"]):
        return False
    return True


def location_ok(loc, cfg):
    if not cfg["locations"]:
        return True
    l = loc.lower()
    return any(x in l for x in cfg["locations"])


# --------------------------------------------------------------- notifications
def _hdr(s):
    # HTTP header values must be latin-1, so strip anything that can't encode
    # (e.g. emoji, non-Western scripts). Accented European chars survive.
    return (s or "").encode("latin-1", "ignore").decode("latin-1")


def notify(cfg, title, body, url):
    topic = cfg["ntfy_topic"]
    if not topic or "CHANGE-ME" in topic:
        return
    try:
        requests.post(
            f"{cfg['ntfy_server']}/{topic}",
            data=body.encode("utf-8"),          # body is UTF-8, emoji OK here
            headers={
                "Title": _hdr(title)[:200],
                "Click": _hdr(url),
                "Tags": "briefcase",
                "Priority": "default",
            },
            timeout=15,
        )
    except Exception as e:
        print(f"  ! ntfy failed: {e}", file=sys.stderr)


# -------------------------------------------------------------------- main run
def main():
    cfg = load_config()
    registry = load_json(os.path.join(ROOT, "companies.json"), [])
    state_path = os.path.join(ROOT, "seen.json")
    state = load_json(state_path, {})
    seen = set(state.get("seen", []))
    first_run = not seen

    print(f"Scanning {len(registry)} boards "
          f"(concurrency={cfg['concurrency']}, first_run={first_run})")

    matched = []       # jobs passing the filter this run
    ok = fail = 0
    timeout = cfg["request_timeout"]

    def keep(jobs):
        for j in jobs:
            if matches(j["title"], cfg) and location_ok(j["location"], cfg):
                matched.append(j)

    with cf.ThreadPoolExecutor(max_workers=cfg["concurrency"]) as ex:
        futs = {ex.submit(fetch_board, r, timeout): r for r in registry}
        for fut in cf.as_completed(futs):
            jobs, good = fut.result()
            ok += good
            fail += (not good)
            keep(jobs)

    # Extra source: popular community GitHub job lists (individual postings).
    # Catches companies that aren't on a scrapable ATS (custom career sites).
    gh_ok = gh_fail = 0
    for url in cfg["github_sources"]:
        try:
            keep(fetch_github_source(requests.Session(), url, timeout))
            gh_ok += 1
        except Exception:
            gh_fail += 1

    # De-dupe by stable key, preferring a direct ATS link over a GitHub-list
    # entry for the same role; newest first.
    best = {}
    for j in matched:
        k = j["key"]
        if k not in best or (best[k]["ats"] == "github" and j["ats"] != "github"):
            best[k] = j
    matched = sorted(best.values(), key=lambda j: j["posted"], reverse=True)
    current_keys = set(best.keys())
    new_jobs = [j for j in matched if j["key"] not in seen]

    print(f"Boards ok={ok} fail={fail} | GitHub sources ok={gh_ok} fail={gh_fail} "
          f"| matched={len(matched)} | new={len(new_jobs)}")

    now = dt.datetime.now(dt.timezone.utc).isoformat()

    # ---- notify ---------------------------------------------------------
    if first_run:
        notify(cfg, "JobRadar is armed",
               f"\U0001F6F0️ Tracking {len(registry)} companies. "
               f"{len(matched)} matching roles are open now. "
               f"You'll get a ping the moment a NEW one is posted.", "")
        print("First run: primed state silently (no per-job spam).")
    elif new_jobs:
        cap = cfg["max_new_notifications"]
        for j in new_jobs[:cap]:
            loc = f" — {j['location']}" if j["location"] else ""
            notify(cfg, f"{j['company']}: {j['title']}",
                   f"New posting{loc}\nApply: {j['url']}", j["url"])
        if len(new_jobs) > cap:
            notify(cfg, f"+{len(new_jobs) - cap} more new postings",
                   "Open the JobRadar dashboard to see them all.", "")

    # ---- persist state --------------------------------------------------
    save_json(state_path, {"seen": sorted(current_keys), "updated": now})

    # mark which jobs are new for the dashboard, then write feed (cap 600)
    new_keys = {j["key"] for j in new_jobs}
    feed = []
    for j in matched[:600]:
        jj = dict(j)
        jj["is_new"] = j["key"] in new_keys
        feed.append(jj)
    save_json(os.path.join(ROOT, "docs", "data", "jobs.json"), {
        "generated": now,
        "companies_tracked": len(registry),
        "boards_ok": ok,
        "boards_fail": fail,
        "total_matches": len(matched),
        "new_this_run": len(new_jobs),
        "jobs": feed,
    })
    print(f"Wrote docs/data/jobs.json ({len(feed)} shown).")


if __name__ == "__main__":
    main()
