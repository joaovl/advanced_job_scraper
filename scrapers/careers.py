#!/usr/bin/env python3
"""
Company careers-site crawler — jobs straight from the source, across locations.

Detects which Applicant Tracking System (ATS) a company uses from its careers
page, then pulls jobs from that ATS's public API. Covers the common platforms:
Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee, Workable, Personio,
BambooHR, Workday, SuccessFactors, and Phenom People. Output is the standard job
schema (with location), written to output/careers_*.json for jobsdb.ingest.

Usage:
  python scrapers/careers.py --all -k software            # sweep the repository
  python scrapers/careers.py --company "Vertical Aerospace" --site vertical-aerospace.com
  python scrapers/careers.py --detect vertical-aerospace.com
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import requests

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"
REPO = BASE_DIR / "data" / "uk_aerospace_companies.json"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "*/*"}

SOFTWARE = re.compile(
    r"(software|firmware|embedded|avionics|flight|control|c\+\+|python|"
    r"back[- ]?end|front[- ]?end|full[- ]?stack|develop|programmer|devops|sre|"
    r"data engineer|machine learning|robotics|autonomy|gnc|systems engineer)", re.I)

# ATS host signatures -> (platform, capture groups). Order matters.
PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9]+)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board\?for=([a-z0-9]+)", re.I)),
    ("lever",      re.compile(r"jobs\.lever\.co/([a-z0-9-]+)", re.I)),
    ("ashby",      re.compile(r"jobs\.ashbyhq\.com/([a-z0-9-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9]+)", re.I)),
    ("recruitee",  re.compile(r"([a-z0-9-]+)\.recruitee\.com", re.I)),
    ("workable",   re.compile(r"apply\.workable\.com/([a-z0-9-]+)", re.I)),
    ("personio",   re.compile(r"([a-z0-9-]+)\.jobs\.personio\.com", re.I)),
    ("bamboohr",   re.compile(r"([a-z0-9-]+)\.bamboohr\.com", re.I)),
    ("workday",    re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:en-US/|wday/cxs/[a-z0-9-]+/)?([A-Za-z0-9_]+)", re.I)),
]


def _std(title, company, location, url, desc, platform):
    from jobsdb.salary import parse_salary
    s = parse_salary(desc or "") or {}
    return {"title": (title or "").strip(), "company": company, "location": location or "",
            "url": url or "", "description": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", desc or "")).strip(),
            "posted_date": "", "source": f"Careers:{platform}",
            "salary_min": s.get("min"), "salary_max": s.get("max"),
            "salary_currency": s.get("currency"), "salary_period": s.get("period", "year")}


def detect(domain):
    """Fetch likely careers pages and return (platform, token, extra) or None.

    Fails fast: a few candidate URLs, short timeout, stop at the first ATS hit.
    """
    cands = [f"https://{domain}/careers", f"https://careers.{domain}",
             f"https://jobs.{domain}", f"https://{domain}"]
    for url in cands:
        try:
            r = requests.get(url, headers=H, timeout=8, allow_redirects=True)
        except requests.RequestException:
            continue
        blob = r.url + " " + r.text
        for platform, pat in PATTERNS:
            m = pat.search(blob)
            if m:
                return (platform, m.group(1), m.groups())
    return None


# ---------------- ATS fetchers (public list APIs) ----------------
def fetch_greenhouse(token, company):
    j = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
                     headers=H, timeout=25).json()
    return [_std(x.get("title"), company, (x.get("location") or {}).get("name"),
                 x.get("absolute_url"), x.get("content"), "greenhouse")
            for x in j.get("jobs", [])]


def fetch_lever(token, company):
    j = requests.get(f"https://api.lever.co/v0/postings/{token}?mode=json",
                     headers=H, timeout=25).json()
    return [_std(x.get("text"), company, (x.get("categories") or {}).get("location"),
                 x.get("hostedUrl"), x.get("descriptionPlain"), "lever") for x in j]


def fetch_ashby(token, company):
    j = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}",
                     headers=H, timeout=25).json()
    return [_std(x.get("title"), company, x.get("location"), x.get("jobUrl"),
                 x.get("descriptionPlain") or x.get("descriptionHtml"), "ashby")
            for x in j.get("jobs", [])]


def fetch_smartrecruiters(token, company):
    out, offset = [], 0
    while True:
        j = requests.get(f"https://api.smartrecruiters.com/v1/companies/{token}/postings",
                         params={"limit": 100, "offset": offset}, headers=H, timeout=25).json()
        content = j.get("content", [])
        for x in content:
            loc = x.get("location", {})
            locs = ", ".join(filter(None, [loc.get("city"), loc.get("country")]))
            out.append(_std(x.get("name"), company, locs,
                            f"https://jobs.smartrecruiters.com/{token}/{x.get('id')}", "", "smartrecruiters"))
        if len(content) < 100:
            break
        offset += 100
    return out


def fetch_recruitee(token, company):
    j = requests.get(f"https://{token}.recruitee.com/api/offers/", headers=H, timeout=25).json()
    return [_std(x.get("title"), company, x.get("location"), x.get("careers_url"),
                 x.get("description"), "recruitee") for x in j.get("offers", [])]


def fetch_workable(token, company):
    r = requests.get(f"https://{token}.workable.com/spi/v3/jobs", headers=H, timeout=25)
    j = r.json()
    return [_std(x.get("title"), company, x.get("location", {}).get("location_str"),
                 x.get("url") or x.get("shortlink"), x.get("description"), "workable")
            for x in j.get("jobs", [])]


def fetch_personio(token, company):
    import xml.etree.ElementTree as ET
    r = requests.get(f"https://{token}.jobs.personio.com/xml", headers=H, timeout=25)
    root = ET.fromstring(r.content)
    out = []
    for pos in root.iter("position"):
        g = lambda t: (pos.findtext(t) or "")
        out.append(_std(g("name"), company, g("office"),
                        f"https://{token}.jobs.personio.com/job/{g('id')}",
                        g("jobDescriptions"), "personio"))
    return out


def fetch_bamboohr(token, company):
    j = requests.get(f"https://{token}.bamboohr.com/careers/list", headers=H, timeout=25).json()
    out = []
    for x in j.get("result", []):
        loc = x.get("location") or {}
        locs = ", ".join(filter(None, [loc.get("city"), loc.get("state"), loc.get("country")]))
        out.append(_std(x.get("jobOpeningName"), company, locs,
                        f"https://{token}.bamboohr.com/careers/{x.get('id')}", "", "bamboohr"))
    return out


def _workday_groups(token):
    """Parse an ATS-config Workday token "sub/wd/site[,site2,...]" into the
    (sub, wd, site) tuples fetch_workday expects — one per career site."""
    sub, wd, sites = token.split("/", 2)
    return [(sub, wd, s.strip()) for s in sites.split(",") if s.strip()]


def _parse_workday_token(token):
    """Explicit-config Workday token, path plus optional query:
        "sub/wd/site[,site2,...][?searchText=..&facet=Key:Id[&facet=Key2:Id2]]"
    Returns ([(sub,wd,site),...], search_text, {facetKey:[ids]}).

    The facet key varies per tenant — most use "locationCountry" but some (e.g.
    Rolls-Royce) name it "Country" — so it is spelled out in the token, not guessed.
    """
    path, _, query = token.partition("?")
    q = parse_qs(query)
    search_text = q.get("searchText", [""])[0]
    facets = {}
    for fv in q.get("facet", []):
        k, _, v = fv.partition(":")
        if k and v:
            facets.setdefault(k, []).append(v)
    return _workday_groups(path), search_text, facets


def fetch_workday(groups, company, search_text="", facets=None):
    sub, wd, site = groups[0], groups[1], groups[2]
    api = f"https://{sub}.{wd}.myworkdayjobs.com/wday/cxs/{sub}/{site}/jobs"
    base = f"https://{sub}.{wd}.myworkdayjobs.com/en-US/{site}"
    body_facets = facets or {}
    out, off, total = [], 0, None
    while off < 5000:                        # safety ceiling; real stop is `total`
        r = requests.post(api, headers={**H, "Content-Type": "application/json"},
                          json={"appliedFacets": body_facets, "limit": 20,
                                "offset": off, "searchText": search_text}, timeout=25)
        data = r.json()
        if total is None:
            total = data.get("total") or 0
        jp = data.get("jobPostings", [])
        if not jp:
            break
        for x in jp:
            out.append(_std(x.get("title"), company, x.get("locationsText"),
                            base + x.get("externalPath", ""), "", "workday"))
        off += 20
        if off >= total or len(jp) < 20:     # page through every result, not a fixed window
            break
    return out


def fetch_successfactors(token, company):
    """SAP SuccessFactors Career Site Builder (RCM) job search.

    `token` is the careers site host or base URL (e.g. "careers.qinetiq.com").
    CSB renders its job list at /search/?q=&startrow=N — 25 rows per page, each
    row carrying a jobTitle-link, a jobLocation cell and a jobDepartment cell.
    We page through startrow=1,26,51,... until a short page (or the reported
    total) is reached. Real locations come straight from the jobLocation cell.
    """
    raw = token if token.startswith("http") else f"https://{token}"
    parts = urlsplit(raw)
    base = f"https://{parts.netloc or parts.path}".rstrip("/")
    tq = parse_qs(parts.query)
    kw = tq.get("q", [""])[0]                 # keyword; "" == list everything
    locationsearch = tq.get("locationsearch", [None])[0]   # e.g. "United Kingdom"
    PAGE = 25
    out, startrow, total, seen = [], 1, None, set()
    while startrow <= (total or 100000) and startrow <= 5000:
        params = {"q": kw, "startrow": startrow}
        if locationsearch:
            params["locationsearch"] = locationsearch
        r = requests.get(f"{base}/search/", params=params, headers=H, timeout=25)
        html = r.text
        if total is None:
            m = re.search(r"of\s*<b>\s*([\d,]+)\s*</b>", html, re.I)
            total = int(m.group(1).replace(",", "")) if m else PAGE
        rows = re.findall(r'<tr[^>]*class="data-row[^"]*".*?</tr>', html, re.S)
        if not rows:
            break
        new = 0
        for row in rows:
            lm = re.search(r'class="jobTitle-link"\s+href="([^"]+)".*?>(.*?)</a>', row, re.S)
            if not lm:
                continue
            href = lm.group(1)
            if href in seen:
                continue
            seen.add(href)
            new += 1
            import html as _html
            title = _html.unescape(re.sub(r"<[^>]+>", " ", lm.group(2)))
            locm = re.search(r'class="jobLocation">(.*?)</span>', row, re.S)
            loc = _html.unescape(re.sub(r"<[^>]+>", " ", locm.group(1))) if locm else ""
            loc = re.sub(r"\s+", " ", loc).strip().strip(",")
            url = href if href.startswith("http") else base + href
            out.append(_std(title, company, loc, url, "", "successfactors"))
        if len(rows) < PAGE or new == 0:
            break
        startrow += PAGE
    return out


def _phenom_extract(html):
    """Pull the `eagerLoadRefineSearch` object embedded in a Phenom search page.

    Phenom People (jobs.baesystems.com, careers.rtx.com, ...) server-renders its
    first page of results as a JSON blob assigned to `phApp.ddo`. We grab the
    `eagerLoadRefineSearch` value with a string-aware brace matcher (so literal
    braces inside description text don't throw the balance off) and parse it.
    Returns the decoded dict (with .totalHits and .data.jobs) or None.
    """
    key = 'eagerLoadRefineSearch":'
    i = html.find(key)
    if i < 0:
        return None
    depth, in_str, esc, out = 0, False, False, []
    for ch in html[i + len(key):]:
        out.append(ch)
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                break
    try:
        return json.loads("".join(out))
    except json.JSONDecodeError:
        return None


def fetch_phenom(token, company):
    """Phenom People career-site search (e.g. BAE Systems, RTX / Collins Aerospace).

    `token` is the Phenom host, optionally with query params to steer the search:
      "jobs.baesystems.com"
      "careers.rtx.com?country=United Kingdom&locale=global/en&max=1600"
    Supported params: locale (default "global/en"), keywords (default "software"),
    country (client-side filter on the job's country facet), max (row cap).

    Phenom renders results into the search page's `eagerLoadRefineSearch` blob;
    we page through it with `&from=N` (20 rows/page), pulling real titles and
    "City, State, Country" locations straight from the source.
    """
    raw = token if token.startswith("http") else "https://" + token
    parts = urlsplit(raw)
    host = parts.netloc or parts.path
    q = parse_qs(parts.query)
    locale = q.get("locale", ["global/en"])[0].strip("/")
    keyword = q.get("keywords", ["software"])[0]
    country = q.get("country", [None])[0]
    max_rows = int(q.get("max", ["600"])[0])
    base = f"https://{host}/{locale}/search-results"
    headers = {**H, "Accept": "text/html,application/xhtml+xml",
               "Accept-Language": "en-GB,en;q=0.9",
               "Referer": f"https://{host}/{locale}/home"}
    out, seen, frm, PAGE = [], set(), 0, 20
    while frm < max_rows:
        try:
            r = requests.get(base, params={"keywords": keyword, "from": frm},
                             headers=headers, timeout=25)
            obj = _phenom_extract(r.text)
        except requests.RequestException:
            break
        if not obj:
            break
        jobs = obj.get("data", {}).get("jobs", [])
        total = obj.get("totalHits") or 0
        if not jobs:
            break
        for j in jobs:
            jid = j.get("jobId") or j.get("jobSeqNo") or j.get("reqId")
            if jid in seen:
                continue
            seen.add(jid)
            if country and (j.get("country") or "").strip().lower() != country.strip().lower():
                continue
            loc = j.get("cityStateCountry") or j.get("location") or ""
            url = j.get("applyUrl") or (
                f"https://{host}/{locale}/job/{j.get('jobSeqNo')}" if j.get("jobSeqNo") else "")
            out.append(_std(j.get("title"), company, loc, url,
                            j.get("descriptionTeaser") or "", "phenom"))
        frm += PAGE
        if frm >= total:
            break
        time.sleep(0.3)
    return out


def fetch_algolia(token, company):
    """Algolia-backed careers search (e.g. MBDA / mbdacareers.co.uk).

    Some careers sites are a thin front end over an Algolia index. `token` packs
    the public search credentials as "appId:apiKey:indexName" — the App ID and a
    search-only API key are exposed in the site's JS bundle. We POST to the
    Algolia query API (https://{app}-dsn.algolia.net/1/indexes/{index}/query) and
    page through hitsPerPage=100. Locations come from display_location, which may
    be a list for multi-site roles.
    """
    app, key, index = token.split(":", 2)
    url = f"https://{app}-dsn.algolia.net/1/indexes/{index}/query"
    hdr = {**H, "X-Algolia-Application-Id": app, "X-Algolia-API-Key": key,
           "Content-Type": "application/json"}
    out, page = [], 0
    while page < 50:
        r = requests.post(url, headers=hdr,
                          json={"query": "", "hitsPerPage": 100, "page": page}, timeout=25)
        d = r.json()
        hits = d.get("hits") or []
        for x in hits:
            loc = x.get("display_location") or x.get("location") or x.get("city")
            if isinstance(loc, list):
                loc = ", ".join(str(v) for v in loc if v)
            out.append(_std(x.get("title"), company, loc,
                            x.get("jd_url") or x.get("apply_url"),
                            x.get("description"), "algolia"))
        if not hits or page + 1 >= (d.get("nbPages") or 1):
            break
        page += 1
    return out


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
            "smartrecruiters": fetch_smartrecruiters, "recruitee": fetch_recruitee,
            "workable": fetch_workable, "personio": fetch_personio, "bamboohr": fetch_bamboohr,
            "successfactors": fetch_successfactors, "phenom": fetch_phenom,
            "algolia": fetch_algolia}


def scrape_company(name, domain, keyword=None, ats=None, token=None):
    """Scrape one company's careers site.

    If an explicit `ats` (+ optional `token`) is supplied — e.g. from a repo
    entry {"ats": "successfactors", "token": "careers.qinetiq.com"} — we use it
    directly and skip auto-detection. Otherwise fall back to detect().
    """
    if ats:
        platform, groups = ats, None
        token = token or domain
    else:
        det = detect(domain)
        if not det:
            return None, []
        platform, token, groups = det
    try:
        if platform == "workday":
            if groups is None:
                # ATS-config form: token = "sub/wd/site[,site2,...][?searchText=..&facet=Key:Id]"
                # (e.g. "rollsroyce/wd3/professional?searchText=software&facet=Country:29247e57...").
                # Rolls-Royce/Leonardo front their Workday tenant with a JS marketing
                # page, so detect() never sees the myworkdayjobs URL — pin it explicitly.
                gl, search_text, facets = _parse_workday_token(token)
                jobs = []
                for g in gl:
                    jobs += fetch_workday(g, name, search_text, facets)
            else:
                jobs = fetch_workday(groups, name)
        else:
            jobs = FETCHERS[platform](token, name)
    except Exception as e:
        return platform, []
    if keyword:
        kw = keyword.lower()
        jobs = [j for j in jobs if SOFTWARE.search(j["title"]) or kw in j["title"].lower()]
    else:
        jobs = [j for j in jobs if SOFTWARE.search(j["title"])]
    return platform, jobs


def load_repo():
    # (name, site, ats, token) — ats/token are None unless the entry pins an ATS.
    d = json.load(open(REPO, encoding="utf-8"))
    return [(c["name"], c.get("site", ""), c.get("ats"), c.get("token"))
            for c in d.get("companies", []) if c.get("site") or c.get("ats")]


def main():
    p = argparse.ArgumentParser(description="Company careers-site crawler (multi-ATS).")
    p.add_argument("--all", action="store_true", help="Sweep the company repository")
    p.add_argument("--company", help="Company name")
    p.add_argument("--site", help="Company domain (with --company)")
    p.add_argument("--detect", help="Just detect the ATS for a domain")
    p.add_argument("--ats", help="Force an ATS (e.g. successfactors), skipping detection")
    p.add_argument("--token", help="ATS token/base URL (with --ats), e.g. careers.qinetiq.com")
    p.add_argument("-k", "--keyword", default=None, help="Extra keyword filter (default: software titles)")
    p.add_argument("--limit", type=int, help="First N companies (with --all)")
    args = p.parse_args()

    sys.path.insert(0, str(BASE_DIR))

    if args.detect:
        print(detect(args.detect) or "no known ATS detected")
        return

    targets = []
    if args.all:
        targets = load_repo()
        if args.limit:
            targets = targets[:args.limit]
    elif args.company and args.site:
        targets = [(args.company, args.site, args.ats, args.token)]
    else:
        p.error("use --all, or --company NAME --site DOMAIN, or --detect DOMAIN")

    OUTPUT_DIR.mkdir(exist_ok=True)
    all_jobs, summary = [], {}
    for i, (name, site, ats, token) in enumerate(targets, 1):
        print(f"  [{i}/{len(targets)}] {name} ({site}) …", end=" ", flush=True)
        platform, jobs = scrape_company(name, site, args.keyword, ats=ats, token=token)
        summary[name] = (platform, len(jobs))
        all_jobs += jobs
        print(f"{platform or 'no ATS'}: {len(jobs)} software roles")

    slug = re.sub(r"[^a-z0-9]+", "_", (args.company or "all").lower()).strip("_")
    out = OUTPUT_DIR / f"careers_{slug}_{datetime.now():%Y%m%d}.json"
    json.dump(all_jobs, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    hiring = {k: v for k, v in summary.items() if v[1] > 0}
    print(f"\n{len(hiring)}/{len(targets)} companies with software roles; {len(all_jobs)} total -> {out}")
    print("Ingest with:  python -m jobsdb.ingest")


if __name__ == "__main__":
    main()
