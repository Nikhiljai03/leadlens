# 2-minute video script (about 280 words)

**0:00 - Problem (15s)**: "SaaSquatch finds leads. But a searcher gets thousands of rows and no way to know who to call first. I built LeadLens to fix that: it cleans a list and ranks it against your ideal customer."

**0:15 - Demo (50s)**: Click "Load sample leads". Point at the stats line: 14 rows in, 2 duplicates merged, 2 bad emails flagged. Type "HVAC, Plumbing, Roofing" in target industries and show the ranking change. Open a lead and read the reason: "decision-maker +30, industry fit +25, size in range +20, corporate email +15." Click Export.

**1:05 - Why it matters (20s)**: "Business use: the owner of a 40-person HVAC company ranks above a junior contact at a 12,000-person software firm. Fewer wasted calls, and every score is explained."

**1:25 - Architecture (30s)**: "FastAPI backend, SQLite storage, in-process LRU cache for email checks, a single static HTML UI, deployed as one container on Render. Scores are computed at read time, so changing the ICP re-ranks instantly. For scale I'd move to Postgres and Redis."

**1:55 - Close (5s)**: "Next: MX checks, HubSpot export and AI-written outreach openers. Thanks for watching."
