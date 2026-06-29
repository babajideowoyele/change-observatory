"""
Change.org scraper.

Strategy (in order of preference):
  1. Extract __NEXT_DATA__ JSON from HTML — gives pre-rendered petition data
     with no JS execution required.
  2. Call the internal JSON API discovered from __NEXT_DATA__ for pagination.
  3. Fall back to Playwright for pages that require JS execution.
"""
import json
import time
import logging
from datetime import datetime, timezone
from typing import Iterator, Optional
from urllib.parse import urljoin, urlparse, quote

import requests
from bs4 import BeautifulSoup

from .models import Topic, Petition

log = logging.getLogger(__name__)

BASE_URL = "https://www.change.org"
TOPIC_DIR_URL = f"{BASE_URL}/topic"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Polite delay between requests (seconds)
REQUEST_DELAY = 1.5


def _get(url: str, session: requests.Session, params: dict = None) -> requests.Response:
    time.sleep(REQUEST_DELAY)
    resp = session.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp


def _next_data(html: str) -> Optional[dict]:
    """
    Extract structured petition data from Change.org pages.
    Merges three sources into a single normalised petition dict:
      1. JSON-LD (<script type="application/ld+json">) — title, description, dates, author, image
      2. changeTargetingData JS var — signature counts, tags, creator photo
      3. Standard __NEXT_DATA__ (Next.js) if present
    Returns the data wrapped in {"props": {"pageProps": {"petition": {...}}}} for
    compatibility with the rest of the scraper.
    """
    soup = BeautifulSoup(html, "lxml")

    # 1. Standard Next.js hydration blob
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except json.JSONDecodeError:
            pass

    merged: dict = {}

    # 2. JSON-LD — title, description, creator name, image, dates
    ld_tag = soup.find("script", type="application/ld+json")
    if ld_tag and ld_tag.string:
        try:
            ld = json.loads(ld_tag.string)
            graph = ld.get("@graph", [ld])
            types = {item.get("@type"): item for item in graph if isinstance(item, dict)}

            article = types.get("Article", {})
            person = types.get("Person", {})
            image_obj = types.get("ImageObject", {})

            merged["title"] = article.get("name") or article.get("headline")
            merged["description"] = article.get("description")
            merged["created_at"] = article.get("datePublished")
            merged["updated_at"] = article.get("dateModified")
            if person:
                merged.setdefault("user", {})["displayName"] = person.get("name")
                merged.setdefault("user", {})["url"] = person.get("url")
            if image_obj:
                merged["hero_image_url"] = image_obj.get("contentUrl") or image_obj.get("url")
        except (json.JSONDecodeError, AttributeError):
            pass

    # 3. changeTargetingData — signature count, goal, tags, creator photo
    decoder = json.JSONDecoder()
    for s in soup.find_all("script"):
        txt = s.string or ""
        idx = txt.find("changeTargetingData=")
        if idx < 0:
            continue
        start = idx + len("changeTargetingData=")
        cleaned = txt[start:].replace(":undefined", ":null").replace(",undefined", ",null")
        try:
            data, _ = decoder.raw_decode(cleaned)
            ctd_petition = data.get("petition", {})
            merged["id"] = ctd_petition.get("id")

            sig = ctd_petition.get("signatureCount") or {}
            if isinstance(sig, dict):
                merged["totalSignatureCount"] = sig.get("total")
                merged["goal"] = sig.get("goal")
            else:
                merged["totalSignatureCount"] = sig

            merged["tags"] = ctd_petition.get("tags", [])
            merged["weeklySignatureCount"] = ctd_petition.get("weeklySignatureCount")

            ctd_user = ctd_petition.get("user", {})
            if isinstance(ctd_user, dict):
                merged.setdefault("user", {}).update(ctd_user)
        except (json.JSONDecodeError, ValueError):
            pass
        break  # only one changeTargetingData per page

    if merged:
        return {"props": {"pageProps": {"petition": merged}}}

    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Topic directory
# ---------------------------------------------------------------------------

def scrape_topic_directory(session: requests.Session = None) -> list[Topic]:
    """Scrape all topics from the Change.org topic directory."""
    if session is None:
        session = requests.Session()

    log.info("Fetching topic directory …")
    resp = _get(TOPIC_DIR_URL, session)
    soup = BeautifulSoup(resp.text, "lxml")
    now = _now()

    # Try __NEXT_DATA__ first
    nd = _next_data(resp.text)
    if nd:
        topics = _topics_from_next_data(nd, now)
        if topics:
            log.info(f"Extracted {len(topics)} topics via __NEXT_DATA__")
            return topics

    # HTML fallback: anchor tags linking to /topic/...
    topics = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if "/topic/" not in href:
            continue
        slug = href.split("/topic/")[-1].split("?")[0].strip("/")
        if not slug or slug == "topic":
            continue
        if slug in seen:
            continue
        seen.add(slug)

        # Prefer aria-label for clean name; fall back to first bold child text
        name = a.get("aria-label") or ""
        if not name:
            bold = a.find(lambda t: t.name in ("b", "strong") or
                          (t.name == "div" and "font-bold" in (t.get("class") or [])))
            name = bold.get_text(strip=True) if bold else a.get_text(strip=True)

        # Signature count in data-qa="topic-signatures-count" child
        sig_tag = a.find(attrs={"data-qa": "topic-signatures-count"})
        sig_count = None
        if sig_tag:
            import re as _re
            num_tag = sig_tag.find("b") or sig_tag.find("strong")
            raw_num = (num_tag.get_text(strip=True) if num_tag
                       else _re.search(r"[\d.,]+", sig_tag.get_text()).group())
            # Handle both . and , as thousands separators
            cleaned = raw_num.replace(".", "").replace(",", "")
            try:
                sig_count = int(cleaned)
            except ValueError:
                pass

        clean_url = urljoin(BASE_URL, f"/topic/{slug}")
        topics.append(Topic(slug=slug, name=name, signature_count=sig_count,
                            url=clean_url, scraped_at=now))

    log.info(f"Extracted {len(topics)} topics via HTML fallback")
    return topics


def _topics_from_next_data(nd: dict, now: str) -> list[Topic]:
    topics = []
    try:
        page_props = nd["props"]["pageProps"]
        raw = page_props.get("topics") or page_props.get("allTopics") or []
        for t in raw:
            topics.append(Topic(
                slug=t.get("slug", ""),
                name=t.get("name", "") or t.get("title", ""),
                signature_count=t.get("total_signature_count") or t.get("signatureCount"),
                language=t.get("language_code") or t.get("language"),
                url=urljoin(BASE_URL, f"/topic/{t.get('slug', '')}"),
                scraped_at=now,
            ))
    except (KeyError, TypeError):
        pass
    return topics


# ---------------------------------------------------------------------------
# Petitions per topic
# ---------------------------------------------------------------------------

def scrape_topic_petitions(
    topic_slug: str,
    session: requests.Session = None,
    max_pages: int = 50,
) -> Iterator[Petition]:
    """
    Yield Petition objects for a given topic slug.

    Tries API-based pagination first; falls back to Playwright if needed.
    """
    if session is None:
        session = requests.Session()

    log.info(f"Scraping petitions for topic: {topic_slug}")

    # Page 1 — fetch HTML to discover pagination strategy
    url = f"{BASE_URL}/topic/{topic_slug}"
    resp = _get(url, session)
    now = _now()

    nd = _next_data(resp.text)
    if nd:
        yield from _petitions_from_next_data(nd, topic_slug, now)
        api_url = _discover_pagination_api(nd)
        if api_url:
            yield from _paginate_api(api_url, topic_slug, session, max_pages)
            return

    # HTML fallback for page 1
    yield from _petitions_from_html(resp.text, topic_slug, now)

    # Try query-param pagination (?page=N)
    for page in range(2, max_pages + 1):
        try:
            r = _get(url, session, params={"page": page})
            petitions = list(_petitions_from_html(r.text, topic_slug, _now()))
            if not petitions:
                break
            yield from petitions
        except requests.HTTPError:
            break


def _petitions_from_next_data(nd: dict, topic_slug: str, now: str) -> list[Petition]:
    petitions = []
    try:
        page_props = nd["props"]["pageProps"]
        raw = (
            page_props.get("petitions")
            or page_props.get("initialPetitions")
            or page_props.get("petitionList", {}).get("petitions", [])
            or []
        )
        for p in raw:
            petitions.append(_petition_from_raw(p, topic_slug, now))
    except (KeyError, TypeError):
        pass
    return petitions


def _discover_pagination_api(nd: dict) -> Optional[str]:
    """Look for an API endpoint URL in __NEXT_DATA__ for pagination."""
    try:
        props = nd["props"]["pageProps"]
        return props.get("paginationApiUrl") or props.get("nextPageUrl")
    except (KeyError, TypeError):
        return None


def _paginate_api(
    api_url: str,
    topic_slug: str,
    session: requests.Session,
    max_pages: int,
) -> Iterator[Petition]:
    url = api_url
    page = 2
    while url and page <= max_pages:
        try:
            time.sleep(REQUEST_DELAY)
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning(f"API pagination error on page {page}: {e}")
            break

        now = _now()
        raw_petitions = (
            data.get("petitions")
            or data.get("items")
            or data.get("results")
            or []
        )
        if not raw_petitions:
            break
        for p in raw_petitions:
            yield _petition_from_raw(p, topic_slug, now)

        url = data.get("nextPageUrl") or data.get("next")
        page += 1


def _petitions_from_html(html: str, topic_slug: str, now: str) -> list[Petition]:
    soup = BeautifulSoup(html, "lxml")
    petitions = []

    # Change.org petition cards are typically anchor tags pointing to /p/...
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if href.startswith("/p/") or "/p/" in href:
            slug = href.split("/p/")[-1].split("?")[0].strip("/")
            if not slug:
                continue
            title = a.get_text(strip=True)
            if not title or len(title) < 5:
                # Look for title in child elements
                h = a.find(["h2", "h3", "h4", "span", "p"])
                title = h.get_text(strip=True) if h else slug

            # Signature count — look for sibling or nearby text matching digits
            sig = None
            parent = a.parent
            if parent:
                text = parent.get_text(" ", strip=True)
                import re
                m = re.search(r"([\d,]+)\s*(signatures?|unterzeichner|signataires?)", text, re.I)
                if m:
                    sig = int(m.group(1).replace(",", ""))

            petitions.append(Petition(
                slug=slug,
                title=title,
                topic_slug=topic_slug,
                signature_count=sig,
                url=urljoin(BASE_URL, f"/p/{slug}"),
                scraped_at=now,
            ))

    # Deduplicate by slug
    seen = set()
    unique = []
    for p in petitions:
        if p.slug not in seen:
            seen.add(p.slug)
            unique.append(p)
    return unique


def _petition_from_raw(raw: dict, topic_slug: str, now: str) -> Petition:
    slug = (raw.get("slug") or raw.get("url", "").split("/p/")[-1].strip("/") or "")
    return Petition(
        slug=slug,
        title=raw.get("title", "") or raw.get("name", ""),
        topic_slug=topic_slug,
        creator=_creator_name(raw),
        creator_photo_url=_creator_photo(raw),
        target=raw.get("targeting_description") or raw.get("targetingDescription") or raw.get("target"),
        location=_location(raw),
        description=raw.get("description") or raw.get("description_excerpt") or raw.get("descriptionExcerpt"),
        signature_count=(
            raw.get("total_signature_count")
            or raw.get("totalSignatureCount")
            or raw.get("signatureCount")
        ),
        signature_goal=raw.get("goal") or raw.get("signatureGoal"),
        tags=[t.get("slug") for t in raw.get("tags", []) if isinstance(t, dict)],
        hero_image_url=_hero_image(raw),
        media_urls=_media_urls(raw),
        created_at=raw.get("created_at") or raw.get("createdAt"),
        updated_at=raw.get("updated_at") or raw.get("updatedAt"),
        language=raw.get("original_locale") or raw.get("originalLocale") or raw.get("language"),
        url=urljoin(BASE_URL, f"/p/{slug}"),
        scraped_at=now,
    )


def _creator_name(raw: dict) -> Optional[str]:
    u = raw.get("user") or raw.get("creator") or {}
    if isinstance(u, dict):
        return (u.get("display_name") or u.get("displayName")
                or u.get("name") or u.get("fullName"))
    return None


def _creator_photo(raw: dict) -> Optional[str]:
    u = raw.get("user") or raw.get("creator") or {}
    if isinstance(u, dict):
        photo = u.get("photo") or {}
        if isinstance(photo, dict):
            # changeTargetingData uses nested size objects
            for size_key in ("userLarge", "userMedium", "userSmall", "large", "medium", "small"):
                entry = photo.get(size_key)
                if isinstance(entry, dict):
                    return entry.get("url")
                if isinstance(entry, str):
                    return entry
        return photo if isinstance(photo, str) else None
    return None


def _hero_image(raw: dict) -> Optional[str]:
    # Direct key set by the JSON-LD merger
    if raw.get("hero_image_url"):
        return raw["hero_image_url"]
    photo = raw.get("photo") or raw.get("image") or {}
    if isinstance(photo, dict):
        for size_key in ("petitionLarge", "large", "original", "petitionMedium", "medium", "thumb"):
            entry = photo.get(size_key)
            if isinstance(entry, dict):
                return entry.get("url")
            if isinstance(entry, str):
                return entry
    if isinstance(photo, str):
        return photo
    return raw.get("og_image_url") or raw.get("ogImageUrl")


def _media_urls(raw: dict) -> list[str]:
    """Collect all additional media URLs from petition description or media array."""
    urls = []
    for key in ("media", "photos", "images", "attachments"):
        items = raw.get(key) or []
        for item in items:
            if isinstance(item, dict):
                url = item.get("large") or item.get("url") or item.get("src")
                if url:
                    urls.append(url)
            elif isinstance(item, str):
                urls.append(item)
    return urls


def _location(raw: dict) -> Optional[str]:
    loc = (raw.get("primary_target") or raw.get("primaryTarget")
           or raw.get("location") or {})
    if isinstance(loc, dict):
        city = loc.get("city", "") or loc.get("displayCity", "")
        country = (loc.get("country_name", "") or loc.get("countryName", "")
                   or loc.get("country", ""))
        return ", ".join(filter(None, [city, country])) or None
    return str(loc) if loc else None


# ---------------------------------------------------------------------------
# Individual petition detail
# ---------------------------------------------------------------------------

def scrape_petition(slug: str, session: requests.Session = None) -> Optional[Petition]:
    """Fetch full petition detail including description text."""
    if session is None:
        session = requests.Session()

    url = f"{BASE_URL}/p/{slug}"
    try:
        resp = _get(url, session)
    except requests.HTTPError as e:
        log.warning(f"Could not fetch petition {slug}: {e}")
        return None

    now = _now()
    nd = _next_data(resp.text)
    if nd:
        try:
            pp = nd["props"]["pageProps"]
            raw = pp.get("petition") or pp.get("petitionData") or {}
            if raw:
                p = _petition_from_raw(raw, topic_slug=None, now=now)
                return p
        except (KeyError, TypeError):
            pass

    # HTML fallback
    soup = BeautifulSoup(resp.text, "lxml")
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else slug

    desc_tag = soup.find("div", {"data-testid": "description"}) or soup.find("article")
    description = desc_tag.get_text(" ", strip=True) if desc_tag else None

    # Extract og:image as hero image
    og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    hero = og_img["content"] if og_img and og_img.get("content") else None

    # Any img tags in description body
    media = []
    if desc_tag:
        for img in desc_tag.find_all("img", src=True):
            media.append(img["src"])

    return Petition(
        slug=slug, title=title, description=description,
        hero_image_url=hero, media_urls=media,
        url=url, scraped_at=now,
    )


# ---------------------------------------------------------------------------
# Playwright fallback (lazy import — only used if requests approach fails)
# ---------------------------------------------------------------------------

def scrape_topic_petitions_playwright(topic_slug: str, max_clicks: int = 20) -> list[Petition]:
    """
    Use Playwright to scrape petitions behind a JS 'load more' button.
    Install with: playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")

    url = f"{BASE_URL}/topic/{topic_slug}"
    petitions = []
    now = _now()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
        page.goto(url, wait_until="networkidle")

        for _ in range(max_clicks):
            # Intercept JSON responses from XHR/fetch calls
            html = page.content()
            petitions.extend(_petitions_from_html(html, topic_slug, now))

            btn = page.query_selector("button[data-testid='load-more'], button:has-text('Show more'), button:has-text('Mehr anzeigen')")
            if not btn:
                break
            btn.click()
            page.wait_for_timeout(2000)

        browser.close()

    # Deduplicate
    seen = set()
    unique = []
    for p in petitions:
        if p.slug not in seen:
            seen.add(p.slug)
            unique.append(p)
    return unique
