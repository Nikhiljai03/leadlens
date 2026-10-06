# LeadLens: lead cleaning and ICP scoring

Built for the Caprae Capital AI-Readiness challenge (about 5 hours). Approach: **quality first**.
SaaSquatch finds leads; the real cost for a searcher is the hours spent sorting a messy list. LeadLens takes
any lead list and answers one question: *who should I call first, and why?*

## Features
- **Column mapping**: accepts messy CSV headers ("Job Title", "E-mail", "Headcount").
- **Deduplication**: exact email match, plus same domain with fuzzy name match (difflib, ratio > 0.88). Duplicates are merged and blank fields are filled in.
- **Email validation**: syntax, disposable-domain list, free vs corporate. (MX/SMTP checks are the next step.)
- **ICP scoring (0-100)** with a reason on every lead: seniority 30, industry fit 25, company size 20, email quality 15, completeness 10. Scores are computed on read, so changing the ICP re-ranks instantly without re-uploading.
- **Ranked CSV export** that respects the current filters, ready for a CRM or dialer.

## Stack and architecture
| Layer | Choice |
|---|---|
| API | Python 3.12, FastAPI, Uvicorn |
| Storage | SQLite (file DB; single-user demo). Swap to PostgreSQL by changing `conn()` |
| Cache | In-process `lru_cache` for email checks. Redis is the next step for multi-instance |
| UI | One static HTML page (vanilla JS), served by FastAPI. No build step |
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
