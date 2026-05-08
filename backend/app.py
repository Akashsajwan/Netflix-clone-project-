from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import os
import re
import sqlite3
import time
import uuid
from functools import wraps
from flask import Flask, jsonify, request, render_template, send_from_directory
from flask import redirect, session, url_for
import requests
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "backend" / "users.db"
load_dotenv(BASE_DIR / ".env")

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "").strip()
key_lower = RAPIDAPI_KEY.lower()
if key_lower in {"", "your_rapidapi_key_here", "replace_me", "paste_your_real_key_here"} or key_lower.startswith(("your_", "paste_")):
    RAPIDAPI_KEY = ""
RAPIDAPI_MOVIES_HOST = os.environ.get("RAPIDAPI_MOVIES_HOST", "moviesdatabase.p.rapidapi.com").strip()
RAPIDAPI_TRAILER_HOST = os.environ.get(
    "RAPIDAPI_TRAILER_HOST",
    "streaming-availability.p.rapidapi.com",
).strip()

CATALOG_PAGES = 24
CATALOG_PAGE_LIMIT = 50

CACHE_TTL_SECONDS = 15 * 60

LEGAL_FULL_MOVIE_DEMO_STREAMS = [
    {
        "title": "His Girl Friday (1940)",
        "url": "https://archive.org/download/his_girl_friday/his_girl_friday.mp4",
        "quality": "HD",
        "source_type": "video",
    },
    {
        "title": "Meet John Doe (1941)",
        "url": "https://archive.org/download/meet_john_doe/meet_john_doe.mp4",
        "quality": "HD",
        "source_type": "video",
    },
    {
        "title": "Scarlet Street (1945)",
        "url": "https://archive.org/download/scarlet_street_ipod/Scarlet_Street.mp4",
        "quality": "HD",
        "source_type": "video",
    },
    {
        "title": "The Phantom Planet (1961)",
        "url": "https://archive.org/download/phantom_planet_ipod/The_Phantom_Planet.mp4",
        "quality": "HD",
        "source_type": "video",
    },
    {
        "title": "House on Haunted Hill (1959)",
        "url": "https://archive.org/download/house_on_haunted_hill/house_on_haunted_hill.mp4",
        "quality": "HD",
        "source_type": "video",
    },
]

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
    static_url_path="",
)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
catalog_cache: dict = {"data": [], "fetched_at": 0.0, "error": None}


def normalize_title_for_match(value: str) -> str:
    cleaned = re.sub(r"\([^)]*\)", "", str(value or ""))
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", cleaned).strip().lower()
    return " ".join(cleaned.split())


def demo_stream_index_by_title(title: str, year: str | None = None) -> int | None:
    """
    Returns a demo stream index only when the incoming title matches one of our
    explicitly listed legal demo titles. No automatic/fake mapping.
    """
    incoming = normalize_title_for_match(title)
    incoming_year = str(year or "").strip()[:4] or None
    for idx, item in enumerate(LEGAL_FULL_MOVIE_DEMO_STREAMS):
        demo_title = str(item.get("title") or "")
        demo_year_match = re.search(r"\((\d{4})\)", demo_title)
        demo_year = demo_year_match.group(1) if demo_year_match else None
        demo_base = normalize_title_for_match(demo_title)
        if incoming != demo_base:
            continue
        if incoming_year and demo_year and incoming_year != demo_year:
            continue
        return idx
    return None


def is_full_movie_available(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if (item.get("type") or "").lower() != "movie":
        return False
    return demo_stream_index_by_title(item.get("title") or "", item.get("year")) is not None


def annotate_availability(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        full = is_full_movie_available(item)
        item = {**item, "full_movie_available": full, "playback_label": ("Full Movie Available" if full else "Trailer Only")}
        out.append(item)
    return out


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def rapidapi_headers(host: str) -> dict:
    return {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": host,
    }


def split_genres(genre_field: list[str] | str | None) -> list[str]:
    if genre_field is None:
        return ["General"]
    if isinstance(genre_field, list):
        cleaned = [str(g).strip() for g in genre_field if str(g).strip()]
        return cleaned or ["General"]
    cleaned = [g.strip() for g in str(genre_field).split(",") if g.strip()]
    return cleaned or ["General"]


def parse_moviesdb_title(raw: dict, rank_seed: int) -> dict | None:
    title = str(((raw.get("titleText") or {}).get("text") or "")).strip()
    source_id = str(raw.get("id") or "").strip()
    if not title or not source_id:
        return None

    title_type = (((raw.get("titleType") or {}).get("text") or "")).lower()
    media_type = "tv" if "tv" in title_type or "series" in title_type else "movie"

    primary_image = raw.get("primaryImage") or {}
    poster = str(primary_image.get("url") or "").strip() or None
    year = str((raw.get("releaseYear") or {}).get("year") or "").strip() or None

    genre_items = ((raw.get("genres") or {}).get("genres") or [])
    genres = split_genres([g.get("text") for g in genre_items if isinstance(g, dict)])

    ratings = raw.get("ratingsSummary") or {}
    try:
        rating = float(ratings.get("aggregateRating")) if ratings.get("aggregateRating") is not None else None
    except (TypeError, ValueError):
        rating = None

    is_premium = bool(rating is not None and rating >= 7.4) or (rank_seed % 4 == 0)
    return {
        "id": source_id,
        "source_id": source_id,
        "title": title,
        "year": year,
        "poster": poster,
        "genres": genres,
        "rating": rating,
        "summary": str((raw.get("plot") or {}).get("plotText", {}).get("plainText") or "")[:500],
        "type": media_type,
        "watch_url": None,
        "is_premium": is_premium,
        "provider": "RapidAPI/MoviesDatabase",
        "rank": rank_seed,
    }


def parse_tvmaze_show(raw: dict, rank_seed: int) -> dict | None:
    source_id = str(raw.get("id") or "").strip()
    title = str(raw.get("name") or "").strip()
    if not source_id or not title:
        return None
    image = raw.get("image") or {}
    rating_obj = raw.get("rating") or {}
    external_url = str(raw.get("url") or "").strip() or None
    genres = split_genres(raw.get("genres") or [])
    try:
        rating = float(rating_obj.get("average")) if rating_obj.get("average") is not None else None
    except (TypeError, ValueError):
        rating = None
    is_premium = bool(rating is not None and rating >= 7.5) or (rank_seed % 4 == 0)
    return {
        "id": f"tvmaze-{source_id}",
        "source_id": source_id,
        "title": title,
        "year": None,
        "poster": str(image.get("original") or image.get("medium") or "").strip() or None,
        "genres": genres,
        "rating": rating,
        "summary": str(raw.get("summary") or "")[:500],
        "type": "tv",
        "watch_url": None,
        "external_url": external_url,
        "is_premium": is_premium,
        "provider": "TVMaze (fallback)",
        "rank": rank_seed,
    }


def fetch_moviesdb_page(page: int) -> list[dict]:
    if not RAPIDAPI_KEY:
        return []
    url = f"https://{RAPIDAPI_MOVIES_HOST}/titles"
    params = {"page": page, "limit": CATALOG_PAGE_LIMIT, "list": "most_pop_movies"}
    try:
        response = requests.get(
            url,
            headers=rapidapi_headers(RAPIDAPI_MOVIES_HOST),
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("results") or []
    except Exception:
        return []


def fetch_tvmaze_page(page: int) -> list[dict]:
    url = f"https://api.tvmaze.com/shows?page={page}"
    try:
        response = requests.get(url, timeout=16)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def parse_itunes_item(raw: dict, rank_seed: int) -> dict | None:
    title = str(raw.get("trackName") or raw.get("collectionName") or "").strip()
    source_id = str(raw.get("trackId") or raw.get("collectionId") or "").strip()
    if not title or not source_id:
        return None
    genres = split_genres(raw.get("primaryGenreName"))
    release_date = str(raw.get("releaseDate") or "")
    year = release_date[:4] if len(release_date) >= 4 else None
    poster = str(raw.get("artworkUrl100") or "").strip() or None
    if poster:
        poster = poster.replace("100x100bb", "600x600bb")
    kind = str(raw.get("kind") or raw.get("wrapperType") or "").lower()
    media_type = "tv" if "tv" in kind else "movie"
    external_url = str(raw.get("trackViewUrl") or raw.get("collectionViewUrl") or "").strip() or None
    return {
        "id": f"itunes-{source_id}",
        "source_id": source_id,
        "title": title,
        "year": year,
        "poster": poster,
        "genres": genres,
        "rating": None,
        "summary": "",
        "type": media_type,
        "watch_url": None,
        "external_url": external_url,
        "is_premium": (rank_seed % 5 == 0),
        "provider": "iTunes (fallback)",
        "rank": rank_seed,
    }


def curated_indian_titles(rank_seed_start: int) -> list[dict]:
    curated = [
        ("3 Idiots", "movie", "Comedy, Drama, Bollywood"),
        ("Dangal", "movie", "Drama, Sports, Bollywood"),
        ("Sholay", "movie", "Action, Adventure, Bollywood"),
        ("Zindagi Na Milegi Dobara", "movie", "Adventure, Drama, Bollywood"),
        ("Gully Boy", "movie", "Drama, Music, Bollywood"),
        ("Lagaan", "movie", "Drama, Sports, Bollywood"),
        ("Queen", "movie", "Comedy, Drama, Bollywood"),
        ("Taare Zameen Par", "movie", "Drama, Family, Bollywood"),
        ("Kantara", "movie", "Thriller, Mystery, Indian"),
        ("RRR", "movie", "Action, Drama, Indian"),
        ("Bahubali: The Beginning", "movie", "Action, Fantasy, Indian"),
        ("Sacred Games", "tv", "Crime, Thriller, Indian Series"),
        ("Mirzapur", "tv", "Crime, Drama, Indian Series"),
        ("The Family Man", "tv", "Action, Thriller, Indian Series"),
        ("Scam 1992", "tv", "Drama, Biography, Indian Series"),
    ]
    out: list[dict] = []
    for idx, (title, media_type, genre_str) in enumerate(curated, start=rank_seed_start):
        out.append(
            {
                "id": f"curated-india-{idx}",
                "source_id": f"curated-india-{idx}",
                "title": title,
                "year": None,
                "poster": None,
                "genres": split_genres(genre_str),
                "rating": None,
                "summary": "",
                "type": media_type,
                "watch_url": None,
                "external_url": None,
                "is_premium": False,
                "provider": "Curated Indian Picks",
                "rank": idx,
            }
        )
    return out


def curated_spanish_titles(rank_seed_start: int) -> list[dict]:
    curated = [
        ("Money Heist", "tv", "Crime, Thriller, Spanish"),
        ("Elite", "tv", "Drama, Thriller, Spanish"),
        ("Cable Girls", "tv", "Drama, Romance, Spanish"),
        ("Berlin", "tv", "Crime, Thriller, Spanish"),
        ("Locked Up", "tv", "Crime, Drama, Spanish"),
        ("The Platform", "movie", "Sci-Fi, Thriller, Spanish"),
        ("Pan's Labyrinth", "movie", "Fantasy, Drama, Spanish"),
        ("The Invisible Guest", "movie", "Mystery, Thriller, Spanish"),
        ("Wild Tales", "movie", "Comedy, Thriller, Spanish"),
        ("Roma", "movie", "Drama, Spanish"),
    ]
    out: list[dict] = []
    for idx, (title, media_type, genre_str) in enumerate(curated, start=rank_seed_start):
        out.append(
            {
                "id": f"curated-spanish-{idx}",
                "source_id": f"curated-spanish-{idx}",
                "title": title,
                "year": None,
                "poster": None,
                "genres": split_genres(genre_str),
                "rating": None,
                "summary": "",
                "type": media_type,
                "watch_url": None,
                "external_url": None,
                "is_premium": False,
                "provider": "Curated Spanish Picks",
                "rank": idx,
            }
        )
    return out


def fetch_itunes_term(term: str, media: str = "movie", limit: int = 200) -> list[dict]:
    url = "https://itunes.apple.com/search"
    try:
        response = requests.get(
            url,
            params={"term": term, "media": media, "limit": min(limit, 200)},
            timeout=18,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results") or []
        return results if isinstance(results, list) else []
    except Exception:
        return []


def search_tvmaze(query: str) -> list[dict]:
    url = "https://api.tvmaze.com/search/shows"
    try:
        response = requests.get(url, params={"q": query.strip()}, timeout=16)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    out: list[dict] = []
    for idx, row in enumerate(payload, start=1):
        show = row.get("show") if isinstance(row, dict) else None
        if not isinstance(show, dict):
            continue
        parsed = parse_tvmaze_show(show, idx)
        if parsed:
            parsed["rank"] = idx
            out.append(parsed)
    return out


def tvmaze_show_id_from_catalog_id(catalog_id: str) -> str | None:
    cid = str(catalog_id or "").strip()
    if cid.startswith("tvmaze-"):
        return cid.split("tvmaze-", 1)[1] or None
    return None


def fetch_tvmaze_episodes(show_id: str) -> list[dict]:
    url = f"https://api.tvmaze.com/shows/{show_id}/episodes"
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    out: list[dict] = []
    for ep in payload:
        if not isinstance(ep, dict):
            continue
        season = ep.get("season")
        number = ep.get("number")
        name = str(ep.get("name") or "").strip()
        if season is None or number is None or not name:
            continue
        out.append(
            {
                "id": str(ep.get("id") or f"{show_id}-s{season}-e{number}"),
                "season": int(season),
                "episode": int(number),
                "title": name,
                "airdate": str(ep.get("airdate") or "").strip() or None,
                "runtime": ep.get("runtime"),
                "summary": str(ep.get("summary") or "")[:500],
                "external_url": str(ep.get("url") or "").strip() or None,
            }
        )
    return out


def build_rapidapi_catalog() -> tuple[list[dict], str | None]:
    items_raw: list[dict] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(fetch_moviesdb_page, p): p for p in range(1, CATALOG_PAGES + 1)}
        for fut in as_completed(futures):
            items_raw.extend(fut.result())

    out: list[dict] = []
    seen: set[str] = set()
    for idx, raw in enumerate(items_raw, start=1):
        norm = parse_moviesdb_title(raw, idx)
        if not norm:
            continue
        if norm["id"] in seen:
            continue
        seen.add(norm["id"])
        out.append(norm)

    err = None
    if not RAPIDAPI_KEY:
        err = "RAPIDAPI_KEY is missing. Add it in your environment."
    elif not out:
        err = "RapidAPI returned no titles. Check key/host or network."
    return out, err


def build_fallback_catalog() -> tuple[list[dict], str | None]:
    # TVMaze + iTunes are keyless sources for emergency fallback mode.
    items_raw: list[dict] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch_tvmaze_page, p): p for p in range(0, 12)}
        for fut in as_completed(futures):
            items_raw.extend(fut.result())

    itunes_terms = [
        "action", "drama", "comedy", "thriller", "romance", "adventure",
        "crime", "horror", "animation", "sci fi", "fantasy", "history",
        "bollywood", "hindi movie", "indian cinema", "tollywood", "kollywood",
        "web series", "k drama", "anime",
    ]
    itunes_raw: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        itunes_futs = [pool.submit(fetch_itunes_term, term, "movie", 200) for term in itunes_terms]
        for fut in as_completed(itunes_futs):
            itunes_raw.extend(fut.result())

    out: list[dict] = []
    seen: set[str] = set()
    for idx, raw in enumerate(items_raw, start=1):
        norm = parse_tvmaze_show(raw, idx)
        if not norm:
            continue
        if norm["id"] in seen:
            continue
        seen.add(norm["id"])
        out.append(norm)
    seed = len(out) + 1
    for i, raw in enumerate(itunes_raw, start=seed):
        norm = parse_itunes_item(raw, i)
        if not norm:
            continue
        if norm["id"] in seen:
            continue
        seen.add(norm["id"])
        out.append(norm)
    for item in curated_indian_titles(len(out) + 1):
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        out.append(item)
    for item in curated_spanish_titles(len(out) + 1):
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        out.append(item)
    if not out:
        return [], "Fallback catalog provider returned no titles."
    return out, "RapidAPI key missing: using TVMaze fallback catalog."


def get_catalog(force_refresh: bool = False) -> tuple[list[dict], str | None]:
    now = time.time()
    if not force_refresh and catalog_cache["data"] and now - catalog_cache["fetched_at"] < CACHE_TTL_SECONDS:
        return catalog_cache["data"], catalog_cache.get("error")

    if RAPIDAPI_KEY:
        data, err = build_rapidapi_catalog()
    else:
        data, err = build_fallback_catalog()
    catalog_cache["data"] = data
    catalog_cache["fetched_at"] = now
    catalog_cache["error"] = err
    return data, err


def collect_genres(items: list[dict]) -> list[str]:
    found: set[str] = set()
    for m in items:
        for g in m.get("genres") or []:
            if g:
                found.add(g)
    return sorted(found)


def fetch_watch_link(title: str) -> str | None:
    if not RAPIDAPI_KEY or not title.strip():
        return None
    url = f"https://{RAPIDAPI_TRAILER_HOST}/shows/search/title"
    params = {"title": title.strip(), "country": "us", "output_language": "en"}
    try:
        response = requests.get(
            url,
            headers=rapidapi_headers(RAPIDAPI_TRAILER_HOST),
            params=params,
            timeout=18,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    results = payload if isinstance(payload, list) else payload.get("result", [])
    if not isinstance(results, list) or not results:
        return None
    first = results[0] or {}
    trailer = first.get("youtubeTrailerVideoLink")
    if trailer and "youtube.com/watch?v=" in trailer:
        video_id = trailer.split("watch?v=")[-1].split("&")[0]
        return f"https://www.youtube-nocookie.com/embed/{video_id}?autoplay=1&rel=0"
    return None


def fetch_youtube_embed_from_search(query: str) -> str | None:
    cleaned = " ".join(str(query or "").split()).strip()
    if not cleaned:
        return None
    try:
        response = requests.get(
            "https://www.youtube.com/results",
            params={"search_query": cleaned},
            timeout=16,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
    except Exception:
        return None
    match = re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', response.text)
    if not match:
        return None
    return f"https://www.youtube-nocookie.com/embed/{match.group(1)}?autoplay=1&rel=0"


def build_youtube_search_embed(query: str) -> str | None:
    cleaned = " ".join(str(query or "").split()).strip()
    if not cleaned:
        return None
    # Keyless backup when exact video extraction fails.
    return f"https://www.youtube-nocookie.com/embed?listType=search&list={requests.utils.quote(cleaned)}"


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT 'free',
                password_hash TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                plan TEXT NOT NULL,
                plan_expires_at INTEGER,
                created_at INTEGER NOT NULL,
                last_seen INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    # Ignore if column already exists.
    # sqlite3.OperationalError is expected for existing DB schema.
    try:
        with get_connection() as conn:
            conn.execute("ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'free'")
            conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        with get_connection() as conn:
            conn.execute("ALTER TABLE users ADD COLUMN plan_expires_at INTEGER")
            conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        with get_connection() as conn:
            conn.execute("ALTER TABLE user_sessions ADD COLUMN plan_expires_at INTEGER")
            conn.commit()
    except sqlite3.OperationalError:
        pass


def plan_label(plan: str | None) -> str:
    p = str(plan or "free").lower()
    if p == "free":
        return "Free"
    if p == "m149":
        return "₹149/month"
    if p == "m349":
        return "₹349/month"
    if p == "y5000":
        return "₹5000/year"
    if p == "premium":
        return "Premium"
    return p


def is_paid_plan(plan: str | None) -> bool:
    return str(plan or "free").lower() in {"m149", "m349", "y5000", "premium"}


def plan_active(plan: str | None, expires_at: int | None) -> bool:
    p = str(plan or "free").lower()
    if p == "free":
        return False
    if expires_at is None:
        return True
    return int(expires_at) > int(time.time())


def plan_duration_seconds(plan: str) -> int | None:
    p = str(plan or "").lower()
    if p in {"m149", "m349"}:
        return 30 * 24 * 60 * 60
    if p == "y5000":
        return 365 * 24 * 60 * 60
    if p == "premium":
        return 365 * 24 * 60 * 60
    return None


def get_user_by_session(session_id: str) -> sqlite3.Row | None:
    sid = str(session_id or "").strip()
    if not sid:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email, u.full_name, u.plan, u.plan_expires_at
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.session_id = ?
            """,
            (sid,),
        ).fetchone()
    return row


def has_any_admin() -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone()
    return row is not None


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        admin_id = session.get("admin_id")
        if not admin_id:
            return redirect(url_for("admin_signin_page"))
        with get_connection() as conn:
            admin_row = conn.execute("SELECT id, email FROM admin_users WHERE id = ?", (admin_id,)).fetchone()
        if admin_row is None:
            session.pop("admin_id", None)
            return redirect(url_for("admin_signin_page"))
        return fn(*args, **kwargs)

    return wrapper


def active_sessions_snapshot(window_seconds: int = 15 * 60) -> dict:
    now = int(time.time())
    cutoff = now - int(window_seconds)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT session_id, user_id, email, plan, plan_expires_at, created_at, last_seen
            FROM user_sessions
            WHERE last_seen >= ?
            ORDER BY last_seen DESC
            """,
            (cutoff,),
        ).fetchall()
    sessions = [
        {
            "session_id": r["session_id"],
            "user_id": r["user_id"],
            "email": r["email"],
            "plan": r["plan"],
            "plan_expires_at": r["plan_expires_at"],
            "created_at": r["created_at"],
            "last_seen": r["last_seen"],
        }
        for r in rows
    ]
    paid = sum(1 for s in sessions if is_paid_plan(s.get("plan")) and plan_active(s.get("plan"), s.get("plan_expires_at")))
    free = len(sessions) - paid
    return {"total": len(sessions), "premium": paid, "free": free, "sessions": sessions, "cutoff": cutoff, "now": now}


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/signin")
def signin_page():
    return render_template("signin.html")


@app.get("/signup")
def signup_page():
    return render_template("signup.html")


@app.get("/browse")
def browse_page():
    return render_template("browse.html")

@app.get("/plan")
def plan_page():
    return render_template("plan.html")


@app.get("/admin")
@admin_required
def admin_dashboard_page():
    snapshot = active_sessions_snapshot()
    with get_connection() as conn:
        admins = conn.execute("SELECT id, email, created_at FROM admin_users ORDER BY id ASC").fetchall()
    return render_template(
        "admin_dashboard.html",
        active=snapshot,
        admins=[{"id": a["id"], "email": a["email"], "created_at": a["created_at"]} for a in admins],
    )


@app.get("/admin/signin")
def admin_signin_page():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard_page"))
    return render_template("admin_signin.html", first_time_setup=(not has_any_admin()))


@app.post("/admin/signin")
def admin_signin_action():
    email = str(request.form.get("email", "")).strip().lower()
    password = str(request.form.get("password", "")).strip()
    if not email or not password:
        return render_template("admin_signin.html", error="Email and password are required.", first_time_setup=(not has_any_admin())), 400
    with get_connection() as conn:
        admin_row = conn.execute("SELECT id, email, password_hash FROM admin_users WHERE email = ?", (email,)).fetchone()
    if admin_row is None or not check_password_hash(admin_row["password_hash"], password):
        return render_template("admin_signin.html", error="Invalid admin credentials.", first_time_setup=(not has_any_admin())), 401
    session["admin_id"] = admin_row["id"]
    return redirect(url_for("admin_dashboard_page"))


@app.get("/admin/setup")
def admin_setup_page():
    if has_any_admin():
        return redirect(url_for("admin_signin_page"))
    return render_template("admin_setup.html")


@app.post("/admin/setup")
def admin_setup_action():
    if has_any_admin():
        return redirect(url_for("admin_signin_page"))
    email = str(request.form.get("email", "")).strip().lower()
    password = str(request.form.get("password", "")).strip()
    if not email or len(password) < 6:
        return render_template("admin_setup.html", error="Provide an email and a password (min 6 chars)."), 400
    password_hash = generate_password_hash(password)
    try:
        with get_connection() as conn:
            conn.execute("INSERT INTO admin_users (email, password_hash) VALUES (?, ?)", (email, password_hash))
            conn.commit()
    except sqlite3.IntegrityError:
        return render_template("admin_setup.html", error="That admin email already exists."), 409
    return redirect(url_for("admin_signin_page"))


@app.post("/admin/add-admin")
@admin_required
def admin_add_admin_action():
    email = str(request.form.get("email", "")).strip().lower()
    password = str(request.form.get("password", "")).strip()
    if not email or len(password) < 6:
        return redirect(url_for("admin_dashboard_page", err="Provide an email and a password (min 6 chars)."))
    password_hash = generate_password_hash(password)
    try:
        with get_connection() as conn:
            conn.execute("INSERT INTO admin_users (email, password_hash) VALUES (?, ?)", (email, password_hash))
            conn.commit()
    except sqlite3.IntegrityError:
        return redirect(url_for("admin_dashboard_page", err="Admin email already exists."))
    return redirect(url_for("admin_dashboard_page"))


@app.post("/admin/signout")
@admin_required
def admin_signout_action():
    session.pop("admin_id", None)
    return redirect(url_for("admin_signin_page"))


@app.get("/scripts/<path:filename>")
def scripts(filename: str):
    return send_from_directory(BASE_DIR / "scripts", filename)


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/catalog")
def catalog():
    force_refresh = str(request.args.get("refresh", "")).lower() in {"1", "true", "yes"}
    plan = str(request.args.get("plan", "free")).strip().lower()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        limit = min(120, max(1, int(request.args.get("limit", 80))))
    except (TypeError, ValueError):
        limit = 80
    data, err = get_catalog(force_refresh=force_refresh)
    if err and not data:
        return jsonify({"error": err, "results": [], "count": 0}), 502

    # Plans do not affect catalog visibility; Free users can browse everything.
    visible = data
    start = (page - 1) * limit
    end = start + limit
    subset = annotate_availability(visible[start:end])
    genres = collect_genres(data)
    return jsonify(
        {
            "results": subset,
            "count": len(visible),
            "page": page,
            "limit": limit,
            "has_next": end < len(visible),
            "genres": genres,
            "rapidapi_enabled": bool(RAPIDAPI_KEY),
            "warning": err,
        }
    )


@app.get("/api/home-trending")
def home_trending():
    data, err = get_catalog()
    top = sorted(data, key=lambda x: x.get("rank", 999999))[:10]
    return jsonify({"results": annotate_availability(top), "count": len(top), "warning": err})


@app.get("/api/search")
def search_catalog():
    q = (request.args.get("q") or "").strip()
    if len(q) < 1:
        return jsonify({"results": [], "count": 0})

    data, _ = get_catalog()
    q_lower = q.lower()
    results = []
    for m in data:
        title = (m.get("title") or "").lower().strip()
        genres = " ".join((m.get("genres") or [])).lower()
        year = str(m.get("year") or "").lower()
        if q_lower in title or q_lower in genres or q_lower in year:
            results.append(m)
    if len(q) >= 2:
        seen = {r.get("id") for r in results}
        for idx, r in enumerate(search_tvmaze(q), start=1):
            rid = r.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            r["rank"] = idx
            results.append(r)
        for idx, raw in enumerate(fetch_itunes_term(q, "movie", 80), start=1):
            parsed = parse_itunes_item(raw, idx)
            if not parsed:
                continue
            rid = parsed.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            results.append(parsed)
    return jsonify({"results": annotate_availability(results), "count": len(results)})


@app.get("/api/watch-link")
def watch_link():
    title = str(request.args.get("title", "")).strip()
    year = str(request.args.get("year", "")).strip() or None
    session_id = str(request.args.get("session_id", "")).strip()
    if len(title) < 2:
        return jsonify({"watch_url": None, "error": "Title is required."}), 400

    user_row = get_user_by_session(session_id)
    if user_row is None:
        return jsonify({"watch_url": None, "error": "Please sign in again."}), 401
    current_plan = str(user_row["plan"] or "free").lower()
    expires_at = user_row["plan_expires_at"]
    if not plan_active(current_plan, expires_at):
        return jsonify({"watch_url": None, "error": "Please take a plan to start watching."}), 403

    demo_idx = demo_stream_index_by_title(title, year)
    if demo_idx is not None:
        demo = LEGAL_FULL_MOVIE_DEMO_STREAMS[demo_idx]
        return jsonify(
            {
                "watch_url": demo["url"],
                "source_type": demo.get("source_type", "video"),
                "quality": demo.get("quality", "SD"),
                "matched_title": demo.get("title"),
                "is_demo_library": True,
                "full_movie_available": True,
                "playback_kind": "full_movie",
                "note": "Playing full movie from licensed demo catalog.",
            }
        )

    # Trailer-only flow for everything else.
    link = fetch_watch_link(title)
    if not link:
        link = fetch_youtube_embed_from_search(f"{title} official trailer")
    if not link:
        link = fetch_youtube_embed_from_search(title)
    if not link:
        link = build_youtube_search_embed(title)
    return jsonify(
        {
            "watch_url": link,
            "source_type": "embed",
            "quality": "Source dependent",
            "matched_title": None,
            "is_demo_library": False,
            "full_movie_available": False,
            "playback_kind": "trailer",
            "note": "Trailer source.",
        }
    )


@app.get("/api/series-episodes")
def series_episodes():
    catalog_id = str(request.args.get("id", "")).strip()
    if not catalog_id:
        return jsonify({"seasons": [], "count": 0, "error": "Series id is required."}), 400

    show_id = tvmaze_show_id_from_catalog_id(catalog_id)
    if not show_id:
        return jsonify({"seasons": [], "count": 0, "error": "Episode list is unavailable for this provider."}), 404

    episodes = fetch_tvmaze_episodes(show_id)
    if not episodes:
        return jsonify({"seasons": [], "count": 0, "error": "No episodes found."}), 404

    seasons_map: dict[int, list[dict]] = {}
    for ep in episodes:
        seasons_map.setdefault(ep["season"], []).append(ep)
    seasons = []
    for season_num in sorted(seasons_map.keys()):
        eps = sorted(seasons_map[season_num], key=lambda x: x["episode"])
        seasons.append({"season": season_num, "episodes": eps})

    return jsonify({"seasons": seasons, "count": len(episodes)})


@app.post("/api/signup")
def signup():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", "")).strip()
    full_name = str(payload.get("full_name", "")).strip()
    plan = str(payload.get("plan", "free")).strip().lower()
    if plan not in {"free", "premium"}:
        plan = "free"

    if not email or not password or not full_name:
        return jsonify({"error": "Email, password, and full name are required."}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long."}), 400

    password_hash = generate_password_hash(password)

    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (email, full_name, plan, password_hash) VALUES (?, ?, ?, ?)",
                (email, full_name, plan, password_hash),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "An account with this email already exists."}), 409

    return jsonify({"message": "Account created successfully."}), 201


@app.post("/api/signin")
def signin():
    payload = request.get_json(silent=True) or {}
    identifier = str(payload.get("identifier", "")).strip().lower()
    password = str(payload.get("password", "")).strip()

    if not identifier or not password:
        return jsonify({"error": "Email and password are required."}), 400

    with get_connection() as conn:
        user = conn.execute("SELECT id, email, full_name, plan, plan_expires_at, password_hash FROM users WHERE email = ?", (identifier,)).fetchone()

    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password."}), 401

    session_id = uuid.uuid4().hex
    now = int(time.time())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_sessions (session_id, user_id, email, plan, plan_expires_at, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, user["id"], user["email"], user["plan"], user["plan_expires_at"], now, now),
        )
        conn.commit()

    return jsonify(
        {
            "message": "Sign in successful.",
            "session_id": session_id,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "full_name": user["full_name"],
                "plan": user["plan"],
                "plan_expires_at": user["plan_expires_at"],
            },
        }
    )


@app.post("/api/session/ping")
def session_ping():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400
    now = int(time.time())
    with get_connection() as conn:
        cur = conn.execute("UPDATE user_sessions SET last_seen = ? WHERE session_id = ?", (now, session_id))
        conn.commit()
    if cur.rowcount < 1:
        return jsonify({"error": "session not found"}), 404
    user_row = get_user_by_session(session_id)
    user_payload = None
    if user_row is not None:
        user_payload = {
            "id": user_row["id"],
            "email": user_row["email"],
            "full_name": user_row["full_name"],
            "plan": user_row["plan"],
            "plan_expires_at": user_row["plan_expires_at"],
        }
        with get_connection() as conn:
            conn.execute(
                "UPDATE user_sessions SET plan = ?, plan_expires_at = ? WHERE session_id = ?",
                (user_payload["plan"], user_payload["plan_expires_at"], session_id),
            )
            conn.commit()
    return jsonify({"ok": True, "last_seen": now, "user": user_payload})


@app.get("/api/plan/status")
def plan_status():
    session_id = str(request.args.get("session_id", "")).strip()
    user_row = get_user_by_session(session_id)
    if user_row is None:
        return jsonify({"error": "Please sign in again."}), 401
    plan = str(user_row["plan"] or "free").lower()
    expires_at = user_row["plan_expires_at"]
    now = int(time.time())
    remaining_days = None
    if expires_at:
        remaining_days = max(0, int((int(expires_at) - now) / 86400))
    return jsonify(
        {
            "plan": plan,
            "plan_label": plan_label(plan),
            "plan_expires_at": expires_at,
            "active": plan_active(plan, expires_at),
            "remaining_days": remaining_days,
        }
    )


@app.post("/api/plan/upgrade")
def plan_upgrade():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id", "")).strip()
    desired = str(payload.get("plan", "")).strip().lower()
    if desired not in {"free", "m149", "m349", "y5000"}:
        return jsonify({"error": "Invalid plan."}), 400
    user_row = get_user_by_session(session_id)
    if user_row is None:
        return jsonify({"error": "Please sign in again."}), 401
    current_plan = str(user_row["plan"] or "free").lower()
    current_exp = user_row["plan_expires_at"]
    if plan_active(current_plan, current_exp) and current_plan != "free":
        return jsonify({"error": "Already having a plan."}), 409
    now = int(time.time())
    if desired == "free":
        new_exp = None
    else:
        dur = plan_duration_seconds(desired) or (30 * 24 * 60 * 60)
        new_exp = now + int(dur)
    with get_connection() as conn:
        conn.execute("UPDATE users SET plan = ?, plan_expires_at = ? WHERE id = ?", (desired, new_exp, user_row["id"]))
        conn.execute("UPDATE user_sessions SET plan = ?, plan_expires_at = ? WHERE user_id = ?", (desired, new_exp, user_row["id"]))
        conn.commit()
    return jsonify(
        {
            "ok": True,
            "user": {
                "id": user_row["id"],
                "email": user_row["email"],
                "full_name": user_row["full_name"],
                "plan": desired,
                "plan_expires_at": new_exp,
            },
        }
    )


@app.post("/api/signout")
def signout():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return jsonify({"ok": True})
    with get_connection() as conn:
        conn.execute("DELETE FROM user_sessions WHERE session_id = ?", (session_id,))
        conn.commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="127.0.0.1", port=5000)
