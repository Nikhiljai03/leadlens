"""LeadLens - lead cleaning, dedupe, validation and ICP scoring API."""
import csv, io, os, re, sqlite3
from difflib import SequenceMatcher
from functools import lru_cache
from fastapi import FastAPI, File, UploadFile
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
                 email, industry, employees INTEGER, location, domain, email_status)""")
    return c


@lru_cache(maxsize=4096)  # in-process cache: email checks repeat across uploads
def email_status(email: str) -> str:
    if not email: return "missing"
    if not EMAIL_RE.match(email): return "invalid"
    d = email.split("@")[1]
    return "disposable" if d in DISPOSABLE else "free" if d in FREE else "corporate"


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
    pts += s; why.append(f"decision-maker +{s}" if s >= 20 else "junior/unclear title +0" if not s else f"manager +{s}")
    if industries:
        hit = any(i in (l["industry"] or "").lower() for i in industries)
        pts += 25 if hit else 0; why.append("industry fit +25" if hit else "off-target industry")
    else: pts += 12
    n = l["employees"]
    if lo <= n <= hi: pts += 20; why.append("size in range +20")
    elif n: why.append("size out of range")
    q = {"corporate": 15, "free": 6}.get(l["email_status"], 0)
    pts += q; why.append(f"email {l['email_status']} +{q}")
    pts += 10 if all(l[f] for f in FIELDS) else 5 if l["company"] and l["name"] else 0
    return min(pts, 100), "; ".join(why)


def query(industries="", min_emp=10, max_emp=250, min_score=0, q=""):
    inds = [i.strip().lower() for i in industries.split(",") if i.strip()]
    out = []
    for r in conn().execute("SELECT * FROM leads"):
        l = dict(r)
        l["score"], l["reasons"] = score(l, inds, min_emp, max_emp)
        hay = " ".join(str(v) for v in l.values()).lower()
        if l["score"] >= min_score and q.lower() in hay: out.append(l)
    return sorted(out, key=lambda x: -x["score"])


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
def leads(industries: str = "", min_emp: int = 10, max_emp: int = 250, min_score: int = 0, q: str = ""):
    return query(industries, min_emp, max_emp, min_score, q)


@app.get("/api/export")
def export(industries: str = "", min_emp: int = 10, max_emp: int = 250, min_score: int = 0, q: str = ""):
    buf = io.StringIO()
    w = csv.DictWriter(buf, FIELDS + ["score", "reasons", "email_status"], extrasaction="ignore")
    w.writeheader(); w.writerows(query(industries, min_emp, max_emp, min_score, q))
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=leads_ranked.csv"})


@app.delete("/api/leads")
def clear():
    c = conn(); c.execute("DELETE FROM leads"); c.commit(); return {"ok": True}
