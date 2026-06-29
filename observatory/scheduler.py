"""Periodic observatory runs using the `schedule` library."""
import logging
import time
from pathlib import Path

import schedule

from .scraper import scrape_topic_directory, scrape_topic_petitions
from .store import Store
from .models import PetitionSnapshot

log = logging.getLogger(__name__)


def run_once(db_path: str, topics_limit: int = None, petitions_per_topic: int = 200):
    """Single observatory run: topics -> petitions -> snapshots."""
    store = Store(db_path)
    run_id = store.start_run()
    topics_n = petitions_n = snapshots_n = 0

    try:
        import requests
        session = requests.Session()

        log.info("=== Observatory run started ===")

        # 1. Topic directory
        topics = scrape_topic_directory(session)
        if topics_limit:
            topics = topics[:topics_limit]
        store.upsert_topics(topics)
        topics_n = len(topics)
        log.info(f"Stored {topics_n} topics")

        # 2. Petitions per topic
        for topic in topics:
            max_pages = max(1, petitions_per_topic // 10)
            petitions = list(scrape_topic_petitions(topic.slug, session, max_pages=max_pages))
            if petitions:
                store.upsert_petitions(petitions)
                petitions_n += len(petitions)

                # Record signature snapshots for time-series tracking
                now_ts = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
                snaps = [
                    PetitionSnapshot(
                        petition_slug=p.slug,
                        signature_count=p.signature_count or 0,
                        scraped_at=now_ts,
                    )
                    for p in petitions if p.signature_count is not None
                ]
                if snaps:
                    store.record_snapshots(snaps)
                    snapshots_n += len(snaps)

            log.info(f"  {topic.slug}: {len(petitions)} petitions")

        store.finish_run(run_id, topics_n, petitions_n, snapshots_n)
        log.info(f"=== Run complete — {topics_n} topics, {petitions_n} petitions, {snapshots_n} snapshots ===")

    except Exception as e:
        store._conn.execute(
            "UPDATE runs SET status='failed', notes=? WHERE id=?", (str(e), run_id)
        )
        store._conn.commit()
        log.error(f"Run failed: {e}", exc_info=True)
    finally:
        store.close()


def start_scheduler(db_path: str, interval: str = "daily", **kwargs):
    """
    Start the observatory on a recurring schedule.
    interval: 'hourly' | 'daily' | 'weekly'
    """
    job = lambda: run_once(db_path, **kwargs)

    if interval == "hourly":
        schedule.every().hour.do(job)
    elif interval == "daily":
        schedule.every().day.at("03:00").do(job)
    elif interval == "weekly":
        schedule.every().monday.at("03:00").do(job)
    else:
        raise ValueError(f"Unknown interval: {interval}. Use hourly|daily|weekly")

    log.info(f"Scheduler started — interval={interval}. Running first collection now …")
    job()

    while True:
        schedule.run_pending()
        time.sleep(60)
