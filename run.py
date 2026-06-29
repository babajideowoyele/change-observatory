#!/usr/bin/env python
"""
Change.org Observatory — CLI entry point.

Usage examples:
  python run.py topics                         scrape topic directory
  python run.py petitions --topic politik      petitions for one topic
  python run.py collect                        full run (all topics)
  python run.py collect --limit 50             first 50 topics (dev mode)
  python run.py schedule --interval daily      run on schedule
  python run.py export --format both           export to CSV + JSON
  python run.py status                         show DB stats
"""
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.logging import RichHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)],
)

console = Console()

DB_PATH = Path("data") / "observatory.db"
EXPORT_DIR = Path("exports")


@click.group()
def cli():
    """Change.org Observatory — cartography of online petitions."""


@cli.command()
@click.option("--db", default=str(DB_PATH), show_default=True)
def topics(db):
    """Scrape and store the full topic directory."""
    from observatory.scraper import scrape_topic_directory
    from observatory.store import Store
    import requests

    store = Store(db)
    session = requests.Session()
    t = scrape_topic_directory(session)
    store.upsert_topics(t)
    console.print(f"[green]OK[/green] Stored [bold]{len(t)}[/bold] topics -> {db}")
    store.close()


@cli.command()
@click.option("--topic", required=True, help="Topic slug, e.g. politik")
@click.option("--max-pages", default=20, show_default=True)
@click.option("--db", default=str(DB_PATH), show_default=True)
@click.option("--playwright", is_flag=True, help="Force Playwright (JS rendering)")
def petitions(topic, max_pages, db, playwright):
    """Scrape petitions for a single topic."""
    from observatory.store import Store
    from observatory.models import PetitionSnapshot
    from datetime import datetime, timezone
    import requests

    store = Store(db)

    if playwright:
        from observatory.scraper import scrape_topic_petitions_playwright
        results = scrape_topic_petitions_playwright(topic, max_clicks=max_pages)
    else:
        from observatory.scraper import scrape_topic_petitions
        session = requests.Session()
        results = list(scrape_topic_petitions(topic, session, max_pages=max_pages))

    store.upsert_petitions(results)
    now = datetime.now(timezone.utc).isoformat()
    snaps = [
        PetitionSnapshot(p.slug, p.signature_count or 0, now)
        for p in results if p.signature_count is not None
    ]
    store.record_snapshots(snaps)
    console.print(f"[green]OK[/green] [bold]{len(results)}[/bold] petitions, [bold]{len(snaps)}[/bold] snapshots -> {db}")
    store.close()


@cli.command()
@click.option("--limit", default=None, type=int, help="Max topics (omit for all)")
@click.option("--petitions-per-topic", default=200, show_default=True)
@click.option("--db", default=str(DB_PATH), show_default=True)
def collect(limit, petitions_per_topic, db):
    """Full collection run: topic directory -> all petitions -> snapshots."""
    from observatory.scheduler import run_once
    run_once(db_path=db, topics_limit=limit, petitions_per_topic=petitions_per_topic)


@cli.command()
@click.option("--months", default=1, show_default=True, help="How many recent months of sitemaps to ingest")
@click.option("--locale", default="en-us", show_default=True, help="Topic locale filter (e.g. en-us, de-de, or 'all')")
@click.option("--db", default=str(DB_PATH), show_default=True)
def ingest(months, locale, db):
    """
    Ingest topics + petitions directly from Change.org sitemaps.

    This is the recommended full-corpus collection method.
    Topics come from sitemap-topics_N.xml (all 27k+).
    Petitions come from monthly sitemaps (14k+ per month).

    Example (last 3 months, English topics only):
      python run.py ingest --months 3 --locale en-us
    """
    from observatory.sitemap import iter_topic_urls, iter_petition_urls, slug_from_url
    from observatory.scraper import scrape_petition
    from observatory.store import Store
    from observatory.models import Topic, PetitionSnapshot
    from datetime import datetime, timezone
    import requests

    store = Store(db)
    session = requests.Session()
    run_id = store.start_run()
    topics_n = petitions_n = snapshots_n = 0
    now = datetime.now(timezone.utc).isoformat()

    # 1. Topics from sitemaps
    console.print("[bold]Phase 1:[/bold] Ingesting topic index from sitemaps ...")
    locale_filter = None if locale == "all" else locale
    for topic_url, lastmod in iter_topic_urls(session, locale=locale_filter):
        slug = slug_from_url(topic_url)
        name = slug.rsplit(f"-{locale_filter}", 1)[0] if locale_filter else slug
        store.upsert_topic(Topic(
            slug=slug, name=name, url=topic_url, scraped_at=lastmod or now
        ))
        topics_n += 1
        if topics_n % 10000 == 0:
            console.print(f"  ... {topics_n} topics ingested")
    console.print(f"[green]OK[/green] {topics_n} topics stored")

    # 2. Petitions from monthly sitemaps
    console.print(f"[bold]Phase 2:[/bold] Ingesting petitions from last {months} month(s) of sitemaps ...")
    for petition_url, lastmod in iter_petition_urls(session, months=months):
        slug = slug_from_url(petition_url)
        p = scrape_petition(slug, session)
        if p:
            store.upsert_petition(p)
            petitions_n += 1
            if p.signature_count is not None:
                store.record_snapshot(PetitionSnapshot(
                    petition_slug=slug,
                    signature_count=p.signature_count,
                    scraped_at=lastmod or now,
                ))
                snapshots_n += 1
        if petitions_n % 500 == 0:
            console.print(f"  ... {petitions_n} petitions scraped")

    store.finish_run(run_id, topics_n, petitions_n, snapshots_n)
    console.print(f"[green]OK[/green] Ingest complete: {topics_n} topics, {petitions_n} petitions, {snapshots_n} snapshots")
    store.close()


@cli.command()
@click.option("--interval", default="daily", type=click.Choice(["hourly", "daily", "weekly"]))
@click.option("--limit", default=None, type=int)
@click.option("--db", default=str(DB_PATH), show_default=True)
def schedule(interval, limit, db):
    """Run the observatory on a recurring schedule."""
    from observatory.scheduler import start_scheduler
    start_scheduler(db_path=db, interval=interval, topics_limit=limit)


@cli.command()
@click.option("--format", "fmt", default="both", type=click.Choice(["csv", "json", "both"]))
@click.option("--db", default=str(DB_PATH), show_default=True)
@click.option("--out", default=str(EXPORT_DIR), show_default=True)
def export(fmt, db, out):
    """Export all data to CSV and/or JSON."""
    from observatory.store import Store
    store = Store(db)
    store.export(out, fmt=fmt)
    console.print(f"[green]OK[/green] Exported -> {out}/")
    store.close()


@cli.command()
@click.option("--db", default=str(DB_PATH), show_default=True)
def status(db):
    """Show database statistics."""
    from observatory.store import Store
    store = Store(db)
    s = store.summary()
    store.close()

    table = Table(title="Observatory Status", show_header=True)
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Topics", str(s["topics"]))
    table.add_row("Petitions", str(s["petitions"]))
    table.add_row("Signature snapshots", str(s["snapshots"]))
    table.add_row("Completed runs", str(s["runs"]))
    console.print(table)


if __name__ == "__main__":
    cli()
