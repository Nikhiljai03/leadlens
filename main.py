"""LeadLens - lead cleaning, dedupe, validation and ICP scoring API."""
import csv, io, ipaddress, os, re, socket, sqlite3, urllib.request, urllib.robotparser
from difflib import SequenceMatcher
from functools import lru_cache
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

DB = os.getenv("DB_PATH", "leads.db")
HERE = os.path.dirname(__file__)
app = FastAPI(title="LeadLens")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")

FIELDS = ["name", "title", "company", "email", "industry", "employees", "location"]
ALIASES = {"name": ["name", "full name", "contact"], "title": ["title", "job title", "role"],
           "company": ["company", "organization", "business"], "email": ["email", "e-mail", "email address"],
           "industry": ["industry", "sector"], "employees": ["employees", "size", "headcount"],
           "location": ["location", "city", "region"]}
DISPOSABLE = {"mailinator.com", "10minutemail.com", "guerrillamail.com", "yopmail.com", "tempmail.com"}
FREE = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"}
EMAIL_RE = re.compile(r"^[^@\s]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
SENIORITY = [(r"founder|owner|ceo|president|chairman", 30),
             (r"cfo|coo|cto|chief|managing|partner|principal", 26),
             (r"\bvp\b|vice president|head of|director", 20), (r"manager", 12)]


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY, name, title, company,
                 email, industry, employees INTEGER, location, domain, email_status,
                 web_title, web_desc, enriched INTEGER DEFAULT 0)""")
    for col in ("web_title", "web_desc", "enriched INTEGER DEFAULT 0"):  # upgrade older DB files
        try: c.execute(f"ALTER TABLE leads ADD COLUMN {col}")
        except sqlite3.OperationalError: pass
    return c


@lru_cache(maxsize=4096)  # in-process cache: email checks repeat across uploads
def email_status(email: str) -> str:
    if not email: return "missing"
    if not EMAIL_RE.match(email): return "invalid"
    d = email.split("@")[1]
    return "disposable" if d in DISPOSABLE else "free" if d in FREE else "corporate"


REV_PER_EMP = {"hvac": 140000, "plumbing": 130000, "roofing": 150000, "logistics": 180000, "healthcare": 160000,
               "software": 220000, "manufacturing": 200000, "accounting": 120000, "automotive": 170000, "landscaping": 90000}


def est_revenue(l):  # rough revenue-per-employee heuristic, used only to rank who to enrich first
    return l["employees"] * REV_PER_EMP.get((l["industry"] or "").lower(), 150000)


def opener(l):
    first = (l["name"] or "there").split()[0]
    ctx = re.split(r"[.|-]", l.get("web_desc") or "")[0].strip()[:90]
    hook = f" ({ctx})" if ctx else f" and noticed it serves the {l['industry']} space" if l["industry"] else ""
    return f"Hi {first}, I came across {l['company']}{hook}. Open to a quick 10-minute call about [your offer]?"


def safe_host(d):  # block private/loopback targets so enrichment cannot be pointed at internal services
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(d))
        return not (ip.is_private or ip.is_loopback or ip.is_link_local)
    except Exception: return False


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "LeadLensBot/1.0"})
    return urllib.request.urlopen(req, timeout=5).read(200_000).decode("utf-8", "ignore")


@lru_cache(maxsize=1024)
def has_mx(domain):
    try:
        import dns.resolver
        dns.resolver.resolve(domain, "MX", lifetime=3); return True
    except ImportError: return True
    except Exception: return False


@lru_cache(maxsize=1024)  # one fetch per domain, politely: robots.txt first, 5s timeout, public homepage only
def fetch_site(domain):
    if not safe_host(domain): return {"error": "Website not reachable"}
    base, rp = f"https://{domain}", urllib.robotparser.RobotFileParser()
    try: rp.parse(_get(base + "/robots.txt").splitlines())
    except Exception: pass
    if not rp.can_fetch("LeadLensBot", base): return {"error": "Site blocks automated access (robots.txt)"}
    try: html = _get(base)
    except Exception: return {"error": "Website not reachable"}
    t = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    d = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html, re.I | re.S)
    clean = lambda m: re.sub(r"\s+", " ", m.group(1)).strip()[:200] if m else ""
    return {"title": clean(t), "desc": clean(d)}


def norm(s): return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def parse(rows):
    for r in rows:
        low = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
        lead = {f: next((low[a] for a in ALIASES[f] if a in low), "") for f in FIELDS}
        lead["email"] = lead["email"].lower()
        lead["employees"] = int(re.sub(r"\D", "", lead["employees"]) or 0)
        yield lead


def ingest(rows):
    c, stats = conn(), {"received": 0, "added": 0, "duplicates": 0, "bad_emails": 0}
    known = c.execute("SELECT * FROM leads").fetchall()
    for lead in parse(rows):
        stats["received"] += 1
        lead["email_status"] = email_status(lead["email"])
        lead["domain"] = lead["email"].split("@")[1] if "@" in lead["email"] else ""
        if lead["email_status"] in ("invalid", "disposable", "missing"): stats["bad_emails"] += 1
        dup = next((k for k in known if (lead["email"] and k["email"] == lead["email"]) or
                    (lead["domain"] and k["domain"] == lead["domain"] and
                     SequenceMatcher(None, norm(k["name"]), norm(lead["name"])).ratio() > 0.88)), None)
        if dup:  # merge: fill blanks on the existing record instead of keeping two rows
            for f in FIELDS:
                if not dup[f] and lead[f]: c.execute(f"UPDATE leads SET {f}=? WHERE id=?", (lead[f], dup["id"]))
            stats["duplicates"] += 1
            continue
        c.execute("INSERT INTO leads(name,title,company,email,industry,employees,location,domain,email_status)"
                  " VALUES(?,?,?,?,?,?,?,?,?)", [lead[f] for f in FIELDS] + [lead["domain"], lead["email_status"]])
        known = c.execute("SELECT * FROM leads").fetchall()
        stats["added"] += 1
    c.commit()
    return stats


def score(l, industries, lo, hi):
    pts, why = 0, []
    t = (l["title"] or "").lower()
    s = next((p for rx, p in SENIORITY if re.search(rx, t)), 0)
    pts += s; why.append(f"{'owner/founder' if s == 30 else 'decision-maker'} +{s}" if s >= 20 else "junior/unclear title +0" if not s else f"manager +{s}")
    if industries:
        hit = any(i in (l["industry"] or "").lower() for i in industries)
        pts += 25 if hit else 0; why.append("industry fit +25" if hit else "off-target industry")
    else: pts += 12
    r = est_revenue(l) / 1e6
    if lo <= r <= hi: pts += 20; why.append(f"est. revenue ${r:.1f}M inside buy-box +20")
    elif r: why.append(f"est. revenue ${r:.1f}M outside buy-box")
    q = {"corporate": 15, "free": 6}.get(l["email_status"], 0)
    pts += q; why.append(f"email {l['email_status']} +{q}")
    pts += 10 if all(l[f] for f in FIELDS) else 5 if l["company"] and l["name"] else 0
    return min(pts, 100), "; ".join(why)


def query(industries="", min_rev=1.0, max_rev=10.0, min_score=0, q="", ids=None, region=""):
    inds = [i.strip().lower() for i in industries.split(",") if i.strip()]
    out = []
    for r in conn().execute("SELECT * FROM leads"):
        l = dict(r)
        if region and region.lower() not in (l["location"] or "").lower(): continue
        l["score"], l["reasons"] = score(l, inds, min_rev, max_rev)
        l["est_revenue"], l["opener"], l["enrich_first"] = est_revenue(l), opener(l), False
        hay = " ".join(str(v) for v in l.values()).lower()
        if l["score"] >= min_score and q.lower() in hay: out.append(l)
    out.sort(key=lambda x: (-x["score"], -x["est_revenue"]))
    todo = [x for x in out if not x["enriched"] and x["email_status"] == "corporate" and x["score"] >= 60][:5]
    for x in todo: x["enrich_first"] = True  # spend enrichment credits on these first
    return out


@app.get("/")
def home(): return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    text = (await file.read()).decode("utf-8-sig", errors="ignore")
    return ingest(csv.DictReader(io.StringIO(text)))


@app.post("/api/sample")
def sample():
    with open(os.path.join(HERE, "sample_leads.csv"), encoding="utf-8") as f: return ingest(csv.DictReader(f))


@app.get("/api/leads")
def leads(industries: str = "", min_rev: float = 1, max_rev: float = 10, region: str = "", min_score: int = 0, q: str = ""):
    return query(industries, min_rev, max_rev, min_score, q, region=region)


@app.get("/api/export")
def export(industries: str = "", min_rev: float = 1, max_rev: float = 10, region: str = "", min_score: int = 0, q: str = ""):
    buf = io.StringIO()
    w = csv.DictWriter(buf, FIELDS + ["score", "est_revenue", "reasons", "email_status", "web_title", "web_desc", "opener"], extrasaction="ignore")
    w.writeheader(); w.writerows(query(industries, min_rev, max_rev, min_score, q, region=region))
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=leads_ranked.csv"})


@app.post("/api/enrich/{lead_id}")
def enrich(lead_id: int):
    c = conn()
    row = c.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not row: raise HTTPException(404, "Lead not found")
    if not row["domain"] or row["domain"] in FREE | DISPOSABLE:
        raise HTTPException(400, "Needs a company email domain to enrich")
    site = fetch_site(row["domain"])
    status = row["email_status"] if has_mx(row["domain"]) else "no_mx"
    if "error" in site:
        c.execute("UPDATE leads SET email_status=? WHERE id=?", (status, lead_id)); c.commit()
        raise HTTPException(422, site["error"])
    c.execute("UPDATE leads SET web_title=?, web_desc=?, enriched=1, email_status=? WHERE id=?",
              (site["title"], site["desc"], status, lead_id)); c.commit()
    return next(x for x in query() if x["id"] == lead_id)


@app.delete("/api/leads")
def clear():
    c = conn(); c.execute("DELETE FROM leads"); c.commit(); return {"ok": True}
