"""SQLite persistence layer + CSV/JSON export."""
import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from .models import Topic, Petition, PetitionSnapshot, Run

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    slug            TEXT PRIMARY KEY,
    name            TEXT,
    signature_count INTEGER,
    language        TEXT,
    url             TEXT,
    scraped_at      TEXT
);

CREATE TABLE IF NOT EXISTS petitions (
    slug              TEXT PRIMARY KEY,
    title             TEXT,
    topic_slug        TEXT,
    creator           TEXT,
    creator_photo_url TEXT,
    target            TEXT,
    location          TEXT,
    description       TEXT,
    signature_count   INTEGER,
    signature_goal    INTEGER,
    tags              TEXT,
    hero_image_url    TEXT,
    media_urls        TEXT,
    created_at        TEXT,
    updated_at        TEXT,
    language          TEXT,
    url               TEXT,
    scraped_at        TEXT,
    FOREIGN KEY (topic_slug) REFERENCES topics(slug)
);

CREATE TABLE IF NOT EXISTS petition_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    petition_slug   TEXT,
    signature_count INTEGER,
    scraped_at      TEXT,
    FOREIGN KEY (petition_slug) REFERENCES petitions(slug)
);

CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT,
    completed_at    TEXT,
    topics_scraped  INTEGER DEFAULT 0,
    petitions_scraped INTEGER DEFAULT 0,
    snapshots_taken INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'running',
    notes           TEXT
);
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        log.info(f"Store opened at {self.db_path}")

    def close(self):
        self._conn.close()

    # ------------------------------------------------------------------
    # Topics
    # ------------------------------------------------------------------

    def upsert_topic(self, t: Topic):
        self._conn.execute("""
            INSERT INTO topics (slug, name, signature_count, language, url, scraped_at)
            VALUES (:slug, :name, :signature_count, :language, :url, :scraped_at)
            ON CONFLICT(slug) DO UPDATE SET
                name=excluded.name,
                signature_count=excluded.signature_count,
                scraped_at=excluded.scraped_at
        """, t.__dict__)
        self._conn.commit()

    def upsert_topics(self, topics: list[Topic]):
        self._conn.executemany("""
            INSERT INTO topics (slug, name, signature_count, language, url, scraped_at)
            VALUES (:slug, :name, :signature_count, :language, :url, :scraped_at)
            ON CONFLICT(slug) DO UPDATE SET
                name=excluded.name,
                signature_count=excluded.signature_count,
                scraped_at=excluded.scraped_at
        """, [t.__dict__ for t in topics])
        self._conn.commit()

    def count_topics(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]

    def all_topic_slugs(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT slug FROM topics ORDER BY slug")]

    # ------------------------------------------------------------------
    # Petitions
    # ------------------------------------------------------------------

    def upsert_petition(self, p: Petition):
        d = p.__dict__.copy()
        d["tags"] = json.dumps(d.get("tags") or [])
        d["media_urls"] = json.dumps(d.get("media_urls") or [])
        self._conn.execute("""
            INSERT INTO petitions
                (slug, title, topic_slug, creator, creator_photo_url, target, location,
                 description, signature_count, signature_goal, tags, hero_image_url,
                 media_urls, created_at, updated_at, language, url, scraped_at)
            VALUES
                (:slug, :title, :topic_slug, :creator, :creator_photo_url, :target, :location,
                 :description, :signature_count, :signature_goal, :tags, :hero_image_url,
                 :media_urls, :created_at, :updated_at, :language, :url, :scraped_at)
            ON CONFLICT(slug) DO UPDATE SET
                title=excluded.title,
                signature_count=excluded.signature_count,
                description=COALESCE(excluded.description, petitions.description),
                hero_image_url=COALESCE(excluded.hero_image_url, petitions.hero_image_url),
                media_urls=COALESCE(excluded.media_urls, petitions.media_urls),
                updated_at=excluded.updated_at,
                scraped_at=excluded.scraped_at
        """, d)
        self._conn.commit()

    def upsert_petitions(self, petitions: list[Petition]):
        rows = []
        for p in petitions:
            d = p.__dict__.copy()
            d["tags"] = json.dumps(d.get("tags") or [])
            d["media_urls"] = json.dumps(d.get("media_urls") or [])
            rows.append(d)
        self._conn.executemany("""
            INSERT INTO petitions
                (slug, title, topic_slug, creator, creator_photo_url, target, location,
                 description, signature_count, signature_goal, tags, hero_image_url,
                 media_urls, created_at, updated_at, language, url, scraped_at)
            VALUES
                (:slug, :title, :topic_slug, :creator, :creator_photo_url, :target, :location,
                 :description, :signature_count, :signature_goal, :tags, :hero_image_url,
                 :media_urls, :created_at, :updated_at, :language, :url, :scraped_at)
            ON CONFLICT(slug) DO UPDATE SET
                title=excluded.title,
                signature_count=excluded.signature_count,
                description=COALESCE(excluded.description, petitions.description),
                hero_image_url=COALESCE(excluded.hero_image_url, petitions.hero_image_url),
                media_urls=COALESCE(excluded.media_urls, petitions.media_urls),
                updated_at=excluded.updated_at,
                scraped_at=excluded.scraped_at
        """, rows)
        self._conn.commit()

    def count_petitions(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM petitions").fetchone()[0]

    def all_petition_slugs(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT slug FROM petitions ORDER BY slug")]

    # ------------------------------------------------------------------
    # Snapshots (signature time-series)
    # ------------------------------------------------------------------

    def record_snapshot(self, s: PetitionSnapshot):
        self._conn.execute("""
            INSERT INTO petition_snapshots (petition_slug, signature_count, scraped_at)
            VALUES (:petition_slug, :signature_count, :scraped_at)
        """, s.__dict__)
        self._conn.commit()

    def record_snapshots(self, snapshots: list[PetitionSnapshot]):
        self._conn.executemany("""
            INSERT INTO petition_snapshots (petition_slug, signature_count, scraped_at)
            VALUES (:petition_slug, :signature_count, :scraped_at)
        """, [s.__dict__ for s in snapshots])
        self._conn.commit()

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def start_run(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')", (now,)
        )
        self._conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, topics: int, petitions: int, snapshots: int, notes: str = None):
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute("""
            UPDATE runs SET
                completed_at=?, topics_scraped=?, petitions_scraped=?,
                snapshots_taken=?, status='completed', notes=?
            WHERE id=?
        """, (now, topics, petitions, snapshots, notes, run_id))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------

    def export(self, export_dir: str | Path, fmt: str = "csv"):
        export_dir = Path(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        tables = ["topics", "petitions", "petition_snapshots", "runs"]
        for table in tables:
            df = pd.read_sql_query(f"SELECT * FROM {table}", self._conn)
            if fmt == "csv":
                path = export_dir / f"{table}.csv"
                df.to_csv(path, index=False)
            elif fmt == "json":
                path = export_dir / f"{table}.json"
                df.to_json(path, orient="records", indent=2, force_ascii=False)
            elif fmt == "both":
                df.to_csv(export_dir / f"{table}.csv", index=False)
                df.to_json(export_dir / f"{table}.json", orient="records", indent=2, force_ascii=False)
            log.info(f"Exported {table} -> {path}")

    def summary(self) -> dict:
        return {
            "topics": self.count_topics(),
            "petitions": self.count_petitions(),
            "snapshots": self._conn.execute("SELECT COUNT(*) FROM petition_snapshots").fetchone()[0],
            "runs": self._conn.execute("SELECT COUNT(*) FROM runs WHERE status='completed'").fetchone()[0],
        }
