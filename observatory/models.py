from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Topic:
    slug: str
    name: str
    signature_count: Optional[int] = None
    language: Optional[str] = None
    url: Optional[str] = None
    scraped_at: Optional[str] = None


@dataclass
class Petition:
    slug: str
    title: str
    topic_slug: Optional[str] = None
    creator: Optional[str] = None
    creator_photo_url: Optional[str] = None
    target: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    signature_count: Optional[int] = None
    signature_goal: Optional[int] = None
    tags: list = field(default_factory=list)
    hero_image_url: Optional[str] = None       # main petition header image
    media_urls: list = field(default_factory=list)  # additional embedded images/videos
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    language: Optional[str] = None
    url: Optional[str] = None
    scraped_at: Optional[str] = None


@dataclass
class PetitionSnapshot:
    petition_slug: str
    signature_count: int
    scraped_at: str


@dataclass
class Run:
    started_at: str
    completed_at: Optional[str] = None
    topics_scraped: int = 0
    petitions_scraped: int = 0
    snapshots_taken: int = 0
    status: str = "running"
    notes: Optional[str] = None
