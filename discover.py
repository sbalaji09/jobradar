#!/usr/bin/env python3
"""
discover.py - Build/refresh the company registry (companies.json).

Pulls public, community-maintained internship + new-grad datasets, extracts the
underlying ATS (applicant tracking system) board tokens from each posting's apply
URL, and writes a de-duplicated registry of company boards we know how to scan.

This is how we get "thousands of companies" for free: we don't hand-maintain the
list, we harvest it from datasets that thousands of people already keep current.
Re-run any time (the GitHub Action does this weekly) to pick up new companies.

Usage:
    python discover.py            # refresh companies.json in place
    python discover.py --stats    # just print what would be found
"""
import json, re, sys, urllib.request
from collections import defaultdict

# Public datasets to harvest. Add more raw-JSON listing sources here anytime.
SOURCES = [
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json",
    "https://raw.githubusercontent.com/vanshb03/New-Grad-2025/dev/.github/scripts/listings.json",
]

# ATS URL patterns -> capture group 1 is the board token.
# Order matters: more specific patterns first. Patterns are case-insensitive;
# tokens are lowercased for ATSes whose API expects lowercase (see LOWERCASE_ATS).
ATS_PATTERNS = {
    "greenhouse": [
        r"boards\.greenhouse\.io/embed/job_app\?for=([A-Za-z0-9_-]+)",
        r"job-boards\.greenhouse\.io/([A-Za-z0-9_-]+)",
        r"boards\.greenhouse\.io/([A-Za-z0-9_-]+)",
        r"([A-Za-z0-9_-]+)\.greenhouse\.io",
    ],
    "lever":           [r"jobs\.lever\.co/([A-Za-z0-9_-]+)"],
    "ashby":           [r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)"],
    "smartrecruiters": [r"jobs\.smartrecruiters\.com/([A-Za-z0-9_-]+)",
                        r"careers\.smartrecruiters\.com/([A-Za-z0-9_-]+)"],
    "workable":        [r"apply\.workable\.com/([A-Za-z0-9_-]+)"],
    "workday":         [r"([A-Za-z0-9-]+)\.wd\d+\.myworkdayjobs\.com"],
}

# ATSes whose board token is lowercase in their API. SmartRecruiters keeps case.
LOWERCASE_ATS = {"greenhouse", "lever", "ashby", "workable", "workday"}

UA = {"User-Agent": "jobradar-discover/1.0"}


def fetch_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


# Workday needs full coordinates (tenant.wdN.myworkdayjobs.com/<locale?>/<site>)
# to build its CXS jobs endpoint, so we parse it specially.
WORKDAY_RE = re.compile(
    r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def extract(url_blob):
    """Return a registry dict for the first ATS that matches, else None."""
    wd = WORKDAY_RE.search(url_blob)
    if wd:
        tenant, wdnum, site = wd.group(1).lower(), wd.group(2).lower(), wd.group(3)
        return {"ats": "workday", "token": tenant, "wd": wdnum, "site": site}
    for ats, pats in ATS_PATTERNS.items():
        if ats == "workday":
            continue
        for pat in pats:
            m = re.search(pat, url_blob, re.IGNORECASE)
            if m:
                tok = m.group(1)
                return {"ats": ats,
                        "token": tok.lower() if ats in LOWERCASE_ATS else tok}
    return None


def build():
    # token identity is (ats, token). Keep the first human-readable company name seen.
    reg = {}          # (ats, token) -> {"company", "ats", "token"}
    seen_sources = []
    for src in SOURCES:
        try:
            data = fetch_json(src)
            seen_sources.append((src.split("/")[4], len(data)))
        except Exception as e:
            print(f"  ! skipped {src}: {e}", file=sys.stderr)
            continue
        for p in data:
            blob = f"{p.get('url','')} {p.get('company_url','')}"
            hit = extract(blob)
            if not hit:
                continue
            key = (hit["ats"], hit["token"])
            if key not in reg:
                hit["company"] = p.get("company_name", hit["token"]).strip()
                reg[key] = hit
    return reg, seen_sources


def main():
    stats_only = "--stats" in sys.argv
    reg, srcs = build()
    by_ats = defaultdict(int)
    for (ats, _tok) in reg:
        by_ats[ats] += 1

    print("Sources harvested:")
    for name, n in srcs:
        print(f"  {name}: {n} postings")
    print("\nBoards per ATS:")
    for ats, n in sorted(by_ats.items(), key=lambda x: -x[1]):
        print(f"  {ats:16} {n}")
    print(f"\nTOTAL unique company boards: {len(reg)}")

    if stats_only:
        return

    out = sorted(reg.values(), key=lambda r: (r["ats"], r["token"]))
    with open("companies.json", "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"\nWrote companies.json ({len(out)} boards)")


if __name__ == "__main__":
    main()
