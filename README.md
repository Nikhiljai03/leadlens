# LeadLens: lead cleaning and ICP scoring

Live demo: https://leadlens-xknc.onrender.com

Built for the Caprae Capital AI-Readiness challenge (about 5 hours). Approach: **quality first**.
SaaSquatch finds leads; the real cost for a searcher is the hours spent sorting a messy list. LeadLens takes
any lead list and answers one question: *who should I call first, and why?*

## Why it is built around a buy-box
Caprae's customers are search-fund buyers hunting for a small business to acquire. They do not need "more leads"; they need to know which owner-operated companies fit their **buy-box** (industry, revenue band, region) and who to call first. LeadLens ranks targets that way: owner/founder level 30, industry fit 25, estimated revenue inside the buy-box 20, email quality 15, completeness 10. Every score carries its reason.

## What I learned from SaaSquatch
- **Strengths:** one credit unlocks a full profile, leads are cross-checked from several sources, and users enrich only the leads they choose.
- **Gap I targeted:** a searcher still has to decide *which* leads deserve a credit. SaaSquatch lists AI scoring and revenue estimates, but a sorted, explained shortlist is the missing step.
- **My two features:** (1) ICP scoring with reasons plus an "Enrich first" shortlist (score, then estimated revenue); (2) polite public-website enrichment with email-domain (MX) checks.

## Features
- **Column mapping**: accepts messy CSV headers ("Job Title", "E-mail", "Headcount").
- **Deduplication**: exact email match, plus same domain with fuzzy name match (difflib, ratio > 0.88). Duplicates are merged and blank fields are filled in.
- **Email validation**: syntax, disposable-domain list, free vs corporate. (MX/SMTP checks are the next step.)
- **ICP scoring (0-100)** with a reason on every lead: owner/decision-maker level 30, industry fit 25, estimated revenue fit 20, email quality 15, completeness 10. Scores are computed on read, so changing the ICP re-ranks instantly without re-uploading.
- **Enrich first**: top corporate-email leads by score and estimated revenue (employees x industry revenue-per-employee, a rough heuristic).
- **Website enrichment**: reads the company's public homepage title and description. It checks robots.txt, uses a 5-second timeout, caches per domain, and refuses private network addresses. It never touches LinkedIn or login-gated pages.
- **Outreach opener**: one editable line per lead, built from the website description when available.
- **Ranked CSV export** that respects the current filters, ready for a CRM or dialer.

## Stack and architecture
| Layer | Choice |
|---|---|
| API | Python 3.12, FastAPI, Uvicorn |
| Storage | SQLite (file DB; single-user demo). Swap to PostgreSQL by changing `conn()` |
| Cache | In-process `lru_cache` for email checks. Redis is the next step for multi-instance |
| UI | One static HTML page (vanilla JS), served by FastAPI. No build step |
| Cloud provider | Render (managed web service) |
| Hosting | Single container on Render or Railway (any provider works). Not serverless, because SQLite needs a disk |
| Deployment | `uvicorn main:app --host 0.0.0.0 --port $PORT` |

## Run it
```bash
pip install -r requirements.txt
uvicorn main:app --reload
# open http://localhost:8000 and click "Load sample leads"
```

## Design choices
- Scoring at read time keeps the weights transparent and lets the salesperson tune the ICP live.
- **Ethical data use**: the tool processes lists the user already has. It does not scrape sites that forbid it, and it stores no data beyond the uploaded file.
- Limits: no live scraping, no CAPTCHA handling, no auth. Next steps: Postgres, Redis, MX checks, a CRM export (HubSpot), and a LLM-written one-line outreach opener per lead.

## UX choices
- One screen, four numbers on top (total, average score, hot leads, ready to enrich), then the table. Every score shows a label (Hot / Warm / Cold) and the reason, so colour is never the only signal.
- Filters re-rank instantly. Empty and error states say what to do next.
- Light and dark themes, keyboard focus visible, works on mobile widths.
