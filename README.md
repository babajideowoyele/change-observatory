# Change.org Observatory

A computational observatory for mapping the petition landscape on Change.org — topics, petition metadata, signature dynamics, and geographies over time.

Built for CCS / STS research on digital civic infrastructure.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium   # optional: only needed for JS-heavy pages
```

## Usage

```bash
# Scrape the topic directory (27,000+ topics)
python run.py topics

# Scrape petitions for one topic
python run.py petitions --topic politik

# Full collection run (all topics, ~200 petitions each)
python run.py collect

# Dev/test run (first 50 topics only)
python run.py collect --limit 50

# Run on a daily schedule
python run.py schedule --interval daily

# Export to CSV + JSON
python run.py export --format both

# Check what's in the database
python run.py status
```

## Data model

| Table | Description |
|---|---|
| `topics` | Topic directory — slugs, names, total signature counts |
| `petitions` | Petition metadata — title, creator, target, location, tags, counts |
| `petition_snapshots` | Signature count time-series — one row per petition per run |
| `runs` | Audit log of observatory runs |

Data is stored in `data/observatory.db` (SQLite). Exports go to `exports/`.

## Architecture

```
run.py                 CLI (click + rich)
observatory/
  scraper.py           HTTP + __NEXT_DATA__ parsing + Playwright fallback
  store.py             SQLite persistence + pandas exports
  scheduler.py         Recurring runs via `schedule`
  models.py            Dataclasses: Topic, Petition, PetitionSnapshot, Run
```

## Research notes

- Respects Change.org with a 1.5 s delay between requests.
- `petition_snapshots` enables longitudinal analysis of signature growth.
- Full petition text (`description`) is fetched on individual petition pages.
- Playwright fallback handles JS-rendered "load more" pagination.
