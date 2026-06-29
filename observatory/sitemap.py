"""
Sitemap-based discovery for Change.org petitions and topics.

Change.org sitemap layout:
  /sitemap.xml                    -> index of monthly petition sitemaps + special indexes
  /sitemap-YYYY_MM_N.xml          -> monthly petitions (~14k URLs + lastmod per file)
  /sitemap-topics_index.xml       -> index of 13 topic sub-sitemaps
  /sitemap-topics_N.xml           -> 50k topic URLs each (locale variants included)
  /sitemap-decision_makers_index.xml
  /sitemap-location_pages.xml
"""
import re
import time
import logging
from typing import Iterator

import requests

log = logging.getLogger(__name__)

SITEMAP_INDEX = "https://www.change.org/sitemap.xml"
TOPICS_INDEX = "https://www.change.org/sitemap-topics_index.xml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch(url: str, session: requests.Session) -> str:
    time.sleep(0.5)
    r = session.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.text


def _extract_locs(xml: str, pattern: str = None) -> list[tuple[str, str]]:
    """Return list of (url, lastmod) pairs from a sitemap XML."""
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    mods = re.findall(r"<lastmod>([^<]+)</lastmod>", xml)
    # pad lastmod list if shorter than urls
    mods += [""] * (len(urls) - len(mods))
    pairs = list(zip(urls, mods))
    if pattern:
        pairs = [(u, m) for u, m in pairs if re.search(pattern, u)]
    return pairs


# ---------------------------------------------------------------------------
# Petition sitemaps
# ---------------------------------------------------------------------------

def list_petition_sitemaps(session: requests.Session = None) -> list[str]:
    """Return URLs of all monthly petition sitemaps, newest first."""
    if session is None:
        session = requests.Session()
    xml = _fetch(SITEMAP_INDEX, session)
    # Monthly sitemaps match pattern: sitemap-YYYY_MM_N.xml
    all_urls = [u for u, _ in _extract_locs(xml)]
    monthly = [u for u in all_urls if re.search(r"sitemap-\d{4}_\d{2}_\d+\.xml", u)]
    return monthly


def iter_petition_urls(
    session: requests.Session = None,
    months: int = None,
) -> Iterator[tuple[str, str]]:
    """
    Yield (petition_url, lastmod) from monthly sitemaps.
    months: limit to the N most recent months (None = all history).
    """
    if session is None:
        session = requests.Session()
    sitemaps = list_petition_sitemaps(session)
    if months:
        sitemaps = sitemaps[:months]
    log.info(f"Iterating {len(sitemaps)} monthly petition sitemaps")
    for sm_url in sitemaps:
        log.info(f"  Fetching {sm_url}")
        xml = _fetch(sm_url, session)
        pairs = _extract_locs(xml, pattern=r"/p/")
        log.info(f"    {len(pairs)} petitions")
        yield from pairs


# ---------------------------------------------------------------------------
# Topic sitemaps
# ---------------------------------------------------------------------------

def list_topic_sitemaps(session: requests.Session = None) -> list[str]:
    """Return URLs of all topic sub-sitemaps (sitemap-topics_N.xml)."""
    if session is None:
        session = requests.Session()
    xml = _fetch(TOPICS_INDEX, session)
    return [u for u, _ in _extract_locs(xml)]


def iter_topic_urls(
    session: requests.Session = None,
    locale: str = "en-us",
) -> Iterator[tuple[str, str]]:
    """
    Yield (topic_url, lastmod) filtered to a specific locale suffix.
    locale: 'en-us' | 'de-de' | None (all locales)
    Slugs follow the pattern: /topic/{name}-{locale}
    """
    if session is None:
        session = requests.Session()
    sub_sitemaps = list_topic_sitemaps(session)
    log.info(f"Iterating {len(sub_sitemaps)} topic sub-sitemaps (locale={locale})")
    for sm_url in sub_sitemaps:
        log.info(f"  Fetching {sm_url}")
        xml = _fetch(sm_url, session)
        pairs = _extract_locs(xml, pattern=r"/topic/")
        if locale:
            pairs = [(u, m) for u, m in pairs if u.endswith(f"-{locale}")]
        log.info(f"    {len(pairs)} topic URLs (locale={locale})")
        yield from pairs


def slug_from_url(url: str) -> str:
    """Extract slug from a Change.org /topic/ or /p/ URL."""
    return url.rstrip("/").split("/")[-1]
