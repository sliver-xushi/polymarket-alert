#!/usr/bin/env python3
import json
import math
import os
import re
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "trader.db"

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
XTRACKER_BASE = "https://xtracker.polymarket.com/api"
ORDERBOOK_FETCH_LIMIT = 320
ORDERBOOK_WORKERS = 20
ORDERBOOK_TIMEOUT = 4

CACHE = {
    "markets": None,
    "market_ts": 0,
    "last_error": None,
    "trackings": None,
    "trackings_ts": 0,
}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def parse_dt(value):
    parsed = parse_iso(value)
    if not parsed:
        return None
    try:
        return datetime.fromisoformat(parsed)
    except ValueError:
        return None


def to_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value, default=None):
    try:
        if value is None or value == "":
            return default
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


def ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return [value]
    return []


MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def parse_text_date_range(text):
    if not text:
        return None, None
    patterns = [
        r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})\s*(?:-|to)\s*(?:(january|february|march|april|may|june|july|august|september|october|november|december)\s+)?(\d{1,2}),?\s*(\d{4})",
        r"from\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})\s+to\s+(?:(january|february|march|april|may|june|july|august|september|october|november|december)\s+)?(\d{1,2}),?\s*(\d{4})",
    ]
    lower = str(text).lower()
    for pattern in patterns:
        match = re.search(pattern, lower, re.IGNORECASE)
        if not match:
            continue
        start_month_name = match.group(1).lower()
        start_day = int(match.group(2))
        end_month_name = (match.group(3) or start_month_name).lower()
        end_day = int(match.group(4))
        year = int(match.group(5))
        start = datetime(year, MONTHS[start_month_name], start_day, 16, 0, tzinfo=timezone.utc)
        end = datetime(year, MONTHS[end_month_name], end_day, 16, 0, tzinfo=timezone.utc)
        if end > start:
            return start.isoformat(), end.isoformat()
    return None, None


def http_get_json(url, timeout=1):
    req = request.Request(
        url,
        headers={
            "User-Agent": "musk-tweet-trader/0.1",
            "Accept": "application/json",
        },
    )
    with request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def unwrap_api_data(payload):
    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data")
    return payload


def init_db():
    DATA_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                market_id TEXT NOT NULL,
                market_title TEXT NOT NULL,
                strategy_type TEXT NOT NULL,
                selected_outcomes TEXT NOT NULL,
                budget REAL NOT NULL,
                shares REAL NOT NULL,
                cost REAL NOT NULL,
                cover_probability REAL NOT NULL,
                edge REAL NOT NULL,
                risk_state TEXT NOT NULL,
                notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS order_drafts (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                market_id TEXT NOT NULL,
                market_title TEXT NOT NULL,
                side TEXT NOT NULL,
                selected_outcomes TEXT NOT NULL,
                budget REAL NOT NULL,
                limit_orders TEXT NOT NULL,
                status TEXT NOT NULL,
                notes TEXT
            )
            """
        )


def db_rows(query, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def db_execute(query, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(query, params)


def parse_range(text):
    if not text:
        return None, None, None
    normalized = str(text).replace(",", "")

    patterns = [
        r"between\s+(\d+)\s+and\s+(\d+)",
        r"(\d+)\s*(?:-|to|through)\s*(\d+)",
        r"from\s+(\d+)\s+to\s+(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            low = int(match.group(1))
            high = int(match.group(2))
            return min(low, high), max(low, high), f"{min(low, high)}-{max(low, high)}"

    plus_patterns = [
        r"(\d+)\s*\+",
        r"at\s+least\s+(\d+)",
        r"(\d+)\s+or\s+more",
        r"more\s+than\s+(\d+)",
        r"over\s+(\d+)",
    ]
    for pattern in plus_patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            low = int(match.group(1))
            return low, None, f"{low}+"

    under_patterns = [
        r"under\s+(\d+)",
        r"less\s+than\s+(\d+)",
        r"fewer\s+than\s+(\d+)",
        r"below\s+(\d+)",
    ]
    for pattern in under_patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            high = int(match.group(1)) - 1
            return None, high, f"<{match.group(1)}"

    return None, None, text[:60]


def is_elon_tweet_text(text):
    lower = (text or "").lower()
    has_elon = "elon" in lower or "musk" in lower
    has_tweet = "tweet" in lower or "post" in lower or "x posts" in lower
    return has_elon and has_tweet


def extract_event_items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("events", "data", "results", "markets"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def extract_search_candidates(payload):
    candidates = []
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return candidates
    for key in ("events", "markets", "data", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(value)
    return candidates


def fetch_event_by_slug(slug):
    if not slug:
        return None
    safe_slug = parse.quote(str(slug), safe="")
    urls = [
        f"{GAMMA_BASE}/events/slug/{safe_slug}",
        f"{GAMMA_BASE}/events?slug={safe_slug}",
    ]
    last_error = None
    for url in urls:
        try:
            payload = http_get_json(url)
            if isinstance(payload, list):
                return payload[0] if payload else None
            if isinstance(payload, dict):
                return payload
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return None


def fetch_market_by_slug(slug):
    if not slug:
        return None
    safe_slug = parse.quote(str(slug), safe="")
    urls = [
        f"{GAMMA_BASE}/markets/slug/{safe_slug}",
        f"{GAMMA_BASE}/markets?slug={safe_slug}",
    ]
    last_error = None
    for url in urls:
        try:
            payload = http_get_json(url)
            if isinstance(payload, list):
                return payload[0] if payload else None
            if isinstance(payload, dict):
                return payload
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return None


def slug_from_input(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("http://") or text.startswith("https://"):
        parsed = parse.urlparse(text)
        parts = [part for part in parsed.path.split("/") if part]
        for marker in ("event", "market"):
            if marker in parts:
                idx = parts.index(marker)
                if idx + 1 < len(parts):
                    return parts[idx + 1]
        return parts[-1] if parts else None
    return text


def slug_from_url(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("http://") or text.startswith("https://"):
        parsed = parse.urlparse(text)
        parts = [part for part in parsed.path.split("/") if part]
        return parts[-1] if parts else None
    return text


def resolve_market_input(value):
    slug = slug_from_input(value)
    if not slug:
        raise RuntimeError("Missing market URL or slug")

    errors = []
    for fetcher in (fetch_event_by_slug, fetch_market_by_slug):
        try:
            payload = fetcher(slug)
            if payload:
                item = normalize_market_event(payload)
                if item:
                    return enrich_orderbooks([item], max_books=None)[0]
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError("; ".join(errors[-2:]) or f"Could not resolve {slug}")


def fetch_xtracker_trackings():
    now = time.time()
    if CACHE["trackings"] is not None and now - CACHE["trackings_ts"] < 120:
        return CACHE["trackings"]

    url = f"{XTRACKER_BASE}/users/elonmusk/trackings?" + parse.urlencode(
        {
            "platform": "X",
            "activeOnly": "false",
        }
    )
    payload = http_get_json(url, timeout=3)
    payload = unwrap_api_data(payload)
    if isinstance(payload, dict):
        items = payload.get("trackings") or payload.get("data") or payload.get("items") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    CACHE["trackings"] = items
    CACHE["trackings_ts"] = now
    return items


def tracking_slug(tracking):
    for key in ("marketLink", "marketUrl", "polymarketUrl", "url"):
        value = tracking.get(key)
        slug = slug_from_url(value)
        if slug:
            return slug
    return tracking.get("marketSlug") or tracking.get("slug")


def date_distance_seconds(a, b):
    if not a or not b:
        return None
    return abs((a - b).total_seconds())


def score_tracking_for_market(tracking, market_slug, start_dt, end_dt):
    score = 0
    t_slug = tracking_slug(tracking)
    if market_slug and t_slug and market_slug == t_slug:
        score += 100

    t_start = parse_dt(tracking.get("startDate") or tracking.get("startTime"))
    t_end = parse_dt(tracking.get("endDate") or tracking.get("endTime"))
    start_dist = date_distance_seconds(start_dt, t_start)
    end_dist = date_distance_seconds(end_dt, t_end)
    if start_dist is not None and start_dist <= 6 * 3600:
        score += 30
    if end_dist is not None and end_dist <= 6 * 3600:
        score += 30

    title_text = " ".join(
        str(tracking.get(key) or "")
        for key in ("title", "name", "description", "marketQuestion")
    ).lower()
    if "elon" in title_text or "musk" in title_text:
        score += 10
    if "tweet" in title_text or "post" in title_text:
        score += 10
    return score


def fetch_tracker_for_market(slug, start_time, end_time):
    market_slug = slug_from_url(slug)
    start_dt = parse_dt(start_time)
    end_dt = parse_dt(end_time)
    trackings = fetch_xtracker_trackings()

    best = None
    best_score = 0
    for tracking in trackings:
        if not isinstance(tracking, dict):
            continue
        score = score_tracking_for_market(tracking, market_slug, start_dt, end_dt)
        if score > best_score:
            best = tracking
            best_score = score

    if not best or best_score < 40:
        raise RuntimeError("No matching xtracker tracking found for this market")

    tracking_id = best.get("id") or best.get("_id") or best.get("trackingId")
    detail = best
    if tracking_id:
        try:
            detail = unwrap_api_data(http_get_json(
                f"{XTRACKER_BASE}/trackings/{parse.quote(str(tracking_id), safe='')}?includeStats=true",
                timeout=3,
            ))
        except Exception:
            detail = best

    stats = detail.get("stats") if isinstance(detail, dict) else {}
    stats = stats if isinstance(stats, dict) else {}
    total = (
        stats.get("total")
        or stats.get("count")
        or stats.get("totalCount")
        or stats.get("postCounter")
        or detail.get("currentCount")
        or detail.get("count")
        or detail.get("postCount")
        or detail.get("total")
    )
    if total is None:
        numeric_stats = [
            value
            for key, value in stats.items()
            if isinstance(value, (int, float)) and key.lower() not in ("dayselapsed", "daysremaining")
        ]
        if numeric_stats:
            total = max(numeric_stats)
    total = to_int(total)
    if total is None:
        raise RuntimeError("Matched xtracker tracking but count was missing")

    daily = stats.get("daily") if isinstance(stats.get("daily"), list) else []
    stats_summary = {
        key: value
        for key, value in stats.items()
        if key != "daily"
    }
    if daily:
        stats_summary["recentDaily"] = daily[-24:]

    return {
        "source": "xtracker",
        "fetchedAt": utc_now_iso(),
        "trackingId": tracking_id,
        "title": detail.get("title") or best.get("title") or best.get("name"),
        "marketLink": detail.get("marketLink") or best.get("marketLink"),
        "startDate": parse_iso(detail.get("startDate") or best.get("startDate")),
        "endDate": parse_iso(detail.get("endDate") or best.get("endDate")),
        "count": total,
        "stats": stats_summary,
        "matchScore": best_score,
    }


def normalize_candidate(candidate):
    item = normalize_market_event(candidate)
    if item:
        return item

    slug = candidate.get("slug") if isinstance(candidate, dict) else None
    if not slug:
        return None

    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("title", "question", "description", "slug", "subtitle")
    )
    if not is_elon_tweet_text(text):
        return None

    event = fetch_event_by_slug(slug)
    return normalize_market_event(event) if event else None


def normalize_market_event(event):
    title = (
        event.get("title")
        or event.get("question")
        or event.get("name")
        or event.get("slug")
        or "Untitled market"
    )
    markets = ensure_list(event.get("markets"))
    if not markets and event.get("conditionId"):
        markets = [event]

    full_text = " ".join(
        str(part)
        for part in [
            title,
            event.get("description"),
            event.get("slug"),
            " ".join(str((m or {}).get("question") or "") for m in markets if isinstance(m, dict)),
        ]
        if part
    )
    if not is_elon_tweet_text(full_text):
        return None

    start_time = parse_iso(event.get("startDate") or event.get("startTime"))
    end_time = parse_iso(event.get("endDate") or event.get("endTime") or event.get("end_date"))
    text_start, text_end = parse_text_date_range(full_text)
    if text_start and text_end:
        start_time, end_time = text_start, text_end
    market_id = str(event.get("id") or event.get("eventId") or event.get("slug") or uuid.uuid4())
    outcomes = []

    for idx, market in enumerate(markets):
        if not isinstance(market, dict):
            continue
        question = market.get("question") or market.get("title") or title
        outcome_labels = ensure_list(market.get("outcomes"))
        token_ids = ensure_list(market.get("clobTokenIds") or market.get("clobTokenIDs"))
        outcome_prices = ensure_list(market.get("outcomePrices"))
        child_condition_id = market.get("conditionId") or market.get("condition_id")
        child_market_id = str(market.get("id") or child_condition_id or f"{market_id}:{idx}")
        neg_risk = bool(market.get("negRisk") or event.get("negRisk"))
        tick_size = to_float(market.get("minimumTickSize") or market.get("tickSize"), 0.01)

        if not end_time:
            end_time = parse_iso(market.get("endDate") or market.get("endTime"))
        if not start_time:
            start_time = parse_iso(market.get("startDate") or market.get("startTime"))

        if len(outcome_labels) >= 2 and any(str(x).lower() == "yes" for x in outcome_labels):
            yes_index = next(i for i, x in enumerate(outcome_labels) if str(x).lower() == "yes")
            token_id = str(token_ids[yes_index]) if yes_index < len(token_ids) else None
            price = to_float(outcome_prices[yes_index] if yes_index < len(outcome_prices) else None)
            low, high, label = parse_range(question)
            outcomes.append(
                {
                    "id": child_market_id,
                    "conditionId": child_condition_id,
                    "tokenId": token_id,
                    "label": label,
                    "question": question,
                    "lower": low,
                    "upper": high,
                    "isOpenEnded": high is None or low is None,
                    "gammaPrice": price,
                    "tickSize": tick_size,
                    "negRisk": neg_risk,
                    "volume": to_float(market.get("volume") or market.get("volumeNum"), 0),
                }
            )
            continue

        for out_idx, label_text in enumerate(outcome_labels):
            token_id = str(token_ids[out_idx]) if out_idx < len(token_ids) else None
            price = to_float(outcome_prices[out_idx] if out_idx < len(outcome_prices) else None)
            low, high, label = parse_range(label_text)
            outcomes.append(
                {
                    "id": f"{child_market_id}:{out_idx}",
                    "conditionId": child_condition_id,
                    "tokenId": token_id,
                    "label": label,
                    "question": question,
                    "lower": low,
                    "upper": high,
                    "isOpenEnded": high is None or low is None,
                    "gammaPrice": price,
                    "tickSize": tick_size,
                    "negRisk": neg_risk,
                    "volume": to_float(market.get("volume") or market.get("volumeNum"), 0),
                }
            )

    outcomes = [o for o in outcomes if o.get("label") and o.get("tokenId")]
    if not outcomes:
        return None

    outcomes.sort(key=lambda x: (x["lower"] is None, x["lower"] if x["lower"] is not None else -1, x["upper"] or 10**9))
    return {
        "id": market_id,
        "title": title,
        "slug": event.get("slug"),
        "url": f"https://polymarket.com/event/{event.get('slug')}" if event.get("slug") else None,
        "periodType": infer_period_type(title, start_time, end_time),
        "startTime": start_time,
        "endTime": end_time,
        "volume": to_float(event.get("volume") or event.get("volumeNum"), 0),
        "liquidity": to_float(event.get("liquidity") or event.get("liquidityNum"), 0),
        "outcomes": outcomes,
    }


def infer_period_type(title, start_iso, end_iso):
    lower = (title or "").lower()
    if "7" in lower and ("day" in lower or "week" in lower):
        return "7d"
    if "2" in lower and "day" in lower:
        return "2d"
    if start_iso and end_iso:
        try:
            start = datetime.fromisoformat(start_iso)
            end = datetime.fromisoformat(end_iso)
            hours = (end - start).total_seconds() / 3600
            if hours <= 60:
                return "2d"
            if hours <= 190:
                return "7d"
        except ValueError:
            pass
    return "unknown"


def fetch_gamma_markets():
    search_terms = [
        "Elon Musk tweets",
        "Elon Musk posts",
    ]
    urls = []
    for term in search_terms:
        urls.append(
            f"{GAMMA_BASE}/public-search?"
            + parse.urlencode(
                {
                    "q": term,
                    "events_status": "active",
                    "limit_per_type": 10,
                    "keep_closed_markets": 0,
                }
            )
        )
    seen = set()
    normalized = []
    errors = []
    expanded = 0
    for url in urls:
        try:
            payload = http_get_json(url)
            for event in extract_search_candidates(payload)[:8]:
                has_full_markets = bool(ensure_list(event.get("markets"))) or bool(event.get("conditionId"))
                if not has_full_markets:
                    if expanded >= 3:
                        continue
                    expanded += 1
                item = normalize_candidate(event)
                if not item or item["id"] in seen:
                    continue
                seen.add(item["id"])
                normalized.append(item)
                if len(normalized) >= 8:
                    break
        except Exception as exc:
            errors.append(f"{url}: {exc}")
        if len(normalized) >= 8:
            break

    if not normalized:
        raise RuntimeError("; ".join(errors[-3:]) or "No live markets found")
    return normalized


def enrich_orderbooks(markets, max_books=ORDERBOOK_FETCH_LIMIT):
    jobs = []
    used = 0
    for market in markets:
        for outcome in market["outcomes"]:
            token_id = outcome.get("tokenId")
            if not token_id:
                apply_unavailable_book(outcome)
                continue
            if max_books is not None and used >= max_books:
                apply_unavailable_book(outcome)
                continue
            jobs.append((outcome, token_id))
            used += 1

    def fetch_book(job):
        outcome, token_id = job
        url = f"{CLOB_BASE}/book?token_id={parse.quote(str(token_id))}"
        return outcome, http_get_json(url, timeout=ORDERBOOK_TIMEOUT)

    if jobs:
        with ThreadPoolExecutor(max_workers=ORDERBOOK_WORKERS) as executor:
            future_map = {executor.submit(fetch_book, job): job[0] for job in jobs}
            for future in as_completed(future_map):
                outcome = future_map[future]
                try:
                    _, book = future.result()
                    apply_book(outcome, book)
                except Exception:
                    apply_unavailable_book(outcome)
    return markets


def apply_book(outcome, book):
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    parsed_bids = [(to_float(x.get("price")), to_float(x.get("size"), 0)) for x in bids if isinstance(x, dict)]
    parsed_asks = [(to_float(x.get("price")), to_float(x.get("size"), 0)) for x in asks if isinstance(x, dict)]
    parsed_bids = [(p, s) for p, s in parsed_bids if p is not None and s]
    parsed_asks = [(p, s) for p, s in parsed_asks if p is not None and s]

    best_bid = max((p for p, _ in parsed_bids), default=None)
    best_ask = min((p for p, _ in parsed_asks), default=None)
    mid = None
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / 2
    elif best_ask is not None:
        mid = best_ask
    elif best_bid is not None:
        mid = best_bid
    elif outcome.get("gammaPrice") is not None:
        mid = outcome["gammaPrice"]

    outcome["bestBid"] = best_bid
    outcome["bestAsk"] = best_ask
    outcome["midPrice"] = mid
    outcome["spread"] = (best_ask - best_bid) if best_ask is not None and best_bid is not None else None
    outcome["bidDepth"] = sum(p * s for p, s in parsed_bids[:10])
    outcome["askDepth"] = sum(p * s for p, s in parsed_asks[:10])
    outcome["orderbookStatus"] = "live"


def apply_synthetic_book(outcome):
    price = outcome.get("gammaPrice")
    if price is None:
        price = 0.1
    bid = max(0.01, price - 0.02)
    ask = min(0.99, price + 0.02)
    outcome["bestBid"] = round(bid, 4)
    outcome["bestAsk"] = round(ask, 4)
    outcome["midPrice"] = round((bid + ask) / 2, 4)
    outcome["spread"] = round(ask - bid, 4)
    outcome["bidDepth"] = 0
    outcome["askDepth"] = 0
    outcome["orderbookStatus"] = "synthetic"


def apply_unavailable_book(outcome):
    price = outcome.get("gammaPrice")
    outcome["bestBid"] = "--"
    outcome["bestAsk"] = "--"
    outcome["midPrice"] = price if price is not None else None
    outcome["spread"] = "--"
    outcome["bidDepth"] = 0
    outcome["askDepth"] = 0
    outcome["orderbookStatus"] = "unavailable"


def build_sample_market(sample_id, title, period_type, start, end, prices, volume, liquidity):
    prices = [
        (label, low, high, price) for label, low, high, price in prices
    ]
    outcomes = []
    for idx, (label, low, high, price) in enumerate(prices):
        outcome = {
            "id": f"{sample_id}:{idx}",
            "conditionId": f"{sample_id}-condition-{idx}",
            "tokenId": f"{sample_id}-token-{idx}",
            "label": label,
            "question": f"Will Elon Musk have {label} posts?",
            "lower": low,
            "upper": high,
            "isOpenEnded": low is None or high is None,
            "gammaPrice": price,
            "tickSize": 0.01,
            "negRisk": True,
            "volume": 1000 + idx * 250,
        }
        apply_synthetic_book(outcome)
        outcome["bidDepth"] = 400 + idx * 35
        outcome["askDepth"] = 450 + idx * 40
        outcomes.append(outcome)
    return {
        "id": sample_id,
        "title": title,
        "slug": sample_id,
        "url": None,
        "periodType": period_type,
        "startTime": start,
        "endTime": end,
        "volume": volume,
        "liquidity": liquidity,
        "outcomes": outcomes,
        "isSample": True,
    }


def sample_markets():
    weekly_prices = [
        ("<160", None, 159, 0.04),
        ("160-179", 160, 179, 0.08),
        ("180-199", 180, 199, 0.13),
        ("200-219", 200, 219, 0.20),
        ("220-239", 220, 239, 0.23),
        ("240-259", 240, 259, 0.18),
        ("260-279", 260, 279, 0.11),
        ("280-299", 280, 299, 0.06),
        ("300-319", 300, 319, 0.035),
        ("320+", 320, None, 0.025),
    ]
    two_day_prices = [
        ("<45", None, 44, 0.05),
        ("45-54", 45, 54, 0.11),
        ("55-64", 55, 64, 0.19),
        ("65-74", 65, 74, 0.25),
        ("75-84", 75, 84, 0.19),
        ("85-94", 85, 94, 0.11),
        ("95-104", 95, 104, 0.06),
        ("105+", 105, None, 0.04),
    ]
    weekend_prices = [
        ("<120", None, 119, 0.08),
        ("120-139", 120, 139, 0.15),
        ("140-159", 140, 159, 0.22),
        ("160-179", 160, 179, 0.20),
        ("180-199", 180, 199, 0.14),
        ("200-219", 200, 219, 0.08),
        ("220+", 220, None, 0.05),
    ]
    return [
        build_sample_market(
            "demo-elon-week-apr-21-apr-28",
            "Demo: Elon Musk posts Apr 21-Apr 28",
            "7d",
            "2026-04-21T16:00:00+00:00",
            "2026-04-28T16:00:00+00:00",
            weekly_prices,
            125000,
            22000,
        ),
        build_sample_market(
            "demo-elon-2d-apr-22-apr-24",
            "Demo: Elon Musk posts Apr 22-Apr 24",
            "2d",
            "2026-04-22T16:00:00+00:00",
            "2026-04-24T16:00:00+00:00",
            two_day_prices,
            68000,
            14500,
        ),
        build_sample_market(
            "demo-elon-weekend-apr-24-apr-27",
            "Demo: Elon Musk posts Apr 24-Apr 27",
            "3d",
            "2026-04-24T16:00:00+00:00",
            "2026-04-27T16:00:00+00:00",
            weekend_prices,
            42000,
            9700,
        ),
    ]


def markets_payload(refresh=False):
    now = time.time()
    if not refresh and CACHE["markets"] and now - CACHE["market_ts"] < 45:
        return CACHE["markets"]

    try:
        markets = fetch_gamma_markets()
        markets = enrich_orderbooks(markets)
        payload = {
            "source": "live",
            "warning": None,
            "fetchedAt": utc_now_iso(),
            "markets": markets,
        }
    except Exception as exc:
        payload = {
            "source": "error",
            "warning": str(exc),
            "fetchedAt": utc_now_iso(),
            "markets": [],
        }
    CACHE["markets"] = payload
    CACHE["market_ts"] = now
    CACHE["last_error"] = payload["warning"]
    return payload


def selected_from_payload(body):
    selected = body.get("selectedOutcomes") or []
    return [item for item in selected if isinstance(item, dict)]


def simulate_basket(body):
    selected = selected_from_payload(body)
    budget = max(0.0, to_float(body.get("budget"), 0) or 0)
    buffer_pct = max(0.0, to_float(body.get("bufferPct"), 0) or 0) / 100
    strategy_type = body.get("strategyType") or "Settlement Edge"

    cost_per_share = 0.0
    cover_probability = 0.0
    market_value_per_share = 0.0
    executable = True
    order_items = []

    for outcome in selected:
        ask = to_float(outcome.get("bestAsk"))
        bid = to_float(outcome.get("bestBid"))
        mid = to_float(outcome.get("midPrice"))
        gamma = to_float(outcome.get("gammaPrice"))
        fallback = next((value for value in (mid, gamma, ask, bid) if value is not None and value > 0), 0)
        price = ask if ask is not None and ask > 0 else fallback
        if price is None or price <= 0:
            executable = False
            price = 0
        probability = max(0.0, to_float(outcome.get("modelProbability"), 0) or 0)
        market_price = next((value for value in (mid, gamma, ask, bid) if value is not None and value > 0), price)
        cost_per_share += price
        cover_probability += probability
        market_value_per_share += market_price or 0
        order_items.append(
            {
                "tokenId": outcome.get("tokenId"),
                "label": outcome.get("label"),
                "ask": price,
                "bid": bid,
                "marketPrice": market_price or 0,
                "probability": probability,
            }
        )

    min_target_cost = 0.01 * len(selected)
    safe_entry_cost = max(min_target_cost, cover_probability - buffer_pct) if selected else 0.0
    safe_entry_cost = min(0.99, safe_entry_cost)
    target_entry_cost = 0.0
    for item in order_items:
        if cover_probability > 0:
            target_limit = safe_entry_cost * (item["probability"] / cover_probability)
        else:
            target_limit = item["ask"]
        target_limit = max(0.001, min(0.99, target_limit))
        item["targetLimit"] = target_limit
        target_entry_cost += target_limit

    shares = budget / cost_per_share if cost_per_share > 0 else 0
    cost = shares * cost_per_share
    hit_payout = shares
    profit_if_hit = hit_payout - cost
    edge = cover_probability - cost_per_share - buffer_pct
    convergence_edge = cover_probability - market_value_per_share
    expected_value = shares * edge
    fair_value = cover_probability
    price_gap = convergence_edge
    target_exit_price = min(0.99, market_value_per_share + max(0.02, convergence_edge * 0.55))
    planned_entry_cost = cost_per_share if edge >= 0 else target_entry_cost
    planned_shares = budget / planned_entry_cost if planned_entry_cost > 0 else 0
    swing_return = (target_exit_price - planned_entry_cost) * planned_shares
    avg_depth = 0.0
    if selected:
        avg_depth = (
            sum((to_float(item.get("askDepth"), 0) or 0) + (to_float(item.get("bidDepth"), 0) or 0) for item in selected)
            / len(selected)
        )

    limit_orderable = 0
    for item in order_items:
        bid = item.get("bid")
        ask = item.get("ask")
        target_limit = item.get("targetLimit") or 0
        if ask and target_limit < ask and (bid is None or target_limit >= bid + 0.001):
            limit_orderable += 1

    if not selected:
        status = "idle"
        risk = "none"
    elif not executable:
        status = "blocked"
        risk = "data"
    elif edge >= 0.08:
        status = "normal-size"
        risk = "low"
    elif edge >= 0.03:
        status = "small-size"
        risk = "medium"
    elif edge >= 0:
        status = "watch"
        risk = "thin"
    elif limit_orderable and convergence_edge >= 0.01:
        status = "limit-order"
        risk = "entry-price"
    elif convergence_edge >= 0.02:
        status = "swing-watch"
        risk = "mark-to-market"
    else:
        status = "skip"
        risk = "negative-edge"

    if strategy_type == "Convergence Edge" and status in ("normal-size", "small-size"):
        status = "small-size"
        risk = "medium"

    settlement_advice = {
        "normal-size": "可直接建仓",
        "small-size": "小仓试单",
        "watch": "谨慎小仓",
        "limit-order": "不吃 Ask",
        "swing-watch": "不做结算",
        "skip": "跳过",
        "blocked": "阻塞",
        "idle": "待选择",
    }.get(status, status)

    if not selected:
        limit_advice = "待选择"
    elif not executable:
        limit_advice = "阻塞"
    elif edge >= 0:
        limit_advice = "吃 Ask 可行"
    elif limit_orderable:
        limit_advice = "限价挂单"
    elif convergence_edge >= 0.01:
        limit_advice = "等待回落"
    else:
        limit_advice = "不挂单"

    if not selected:
        swing_advice = "待选择"
    elif not executable:
        swing_advice = "阻塞"
    elif convergence_edge >= 0.08 and avg_depth >= 100:
        swing_advice = "波段可做"
    elif convergence_edge >= 0.03:
        swing_advice = "重点观察"
    elif convergence_edge >= 0.01:
        swing_advice = "轻仓观察"
    elif convergence_edge >= -0.02:
        swing_advice = "观察"
    else:
        swing_advice = "跳过"

    direct_fill = edge >= 0
    orders = []
    for item in order_items:
        limit_price = item["ask"] if direct_fill else item["targetLimit"]
        orders.append(
            {
                "tokenId": item.get("tokenId"),
                "label": item.get("label"),
                "limitPrice": round(limit_price, 4),
                "side": "BUY",
                "mode": "TAKE_ASK" if direct_fill else "LIMIT_WAIT",
            }
        )

    return {
        "strategyType": strategy_type,
        "selectedCount": len(selected),
        "budget": budget,
        "costPerShare": cost_per_share,
        "coverProbability": min(1.0, cover_probability),
        "fairValue": fair_value,
        "marketValue": market_value_per_share,
        "priceGap": price_gap,
        "targetExitPrice": target_exit_price,
        "targetEntryCost": target_entry_cost,
        "plannedEntryCost": planned_entry_cost,
        "limitOrderableCount": limit_orderable,
        "convergenceEdge": convergence_edge,
        "bufferPct": buffer_pct,
        "edge": edge,
        "shares": shares,
        "cost": cost,
        "hitPayout": hit_payout,
        "profitIfHit": profit_if_hit,
        "maxLoss": cost,
        "expectedValue": expected_value,
        "swingReturn": swing_return,
        "settlementAdvice": settlement_advice,
        "limitAdvice": limit_advice,
        "swingAdvice": swing_advice,
        "status": status,
        "riskState": risk,
        "orders": orders,
    }


def make_paper_trade(body):
    simulation = simulate_basket(body)
    selected = selected_from_payload(body)
    record = {
        "id": str(uuid.uuid4()),
        "createdAt": utc_now_iso(),
        "marketId": body.get("marketId") or "",
        "marketTitle": body.get("marketTitle") or "",
        "strategyType": simulation["strategyType"],
        "selectedOutcomes": selected,
        "budget": simulation["budget"],
        "shares": simulation["shares"],
        "cost": simulation["cost"],
        "coverProbability": simulation["coverProbability"],
        "edge": simulation["edge"],
        "riskState": simulation["riskState"],
        "notes": body.get("notes") or "",
    }
    db_execute(
        """
        INSERT INTO paper_trades
        (id, created_at, market_id, market_title, strategy_type, selected_outcomes,
         budget, shares, cost, cover_probability, edge, risk_state, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["id"],
            record["createdAt"],
            record["marketId"],
            record["marketTitle"],
            record["strategyType"],
            json.dumps(selected, ensure_ascii=False),
            record["budget"],
            record["shares"],
            record["cost"],
            record["coverProbability"],
            record["edge"],
            record["riskState"],
            record["notes"],
        ),
    )
    return record


def list_paper_trades():
    rows = db_rows("SELECT * FROM paper_trades ORDER BY created_at DESC LIMIT 100")
    for row in rows:
        row["selectedOutcomes"] = json.loads(row.pop("selected_outcomes"))
        row["createdAt"] = row.pop("created_at")
        row["marketId"] = row.pop("market_id")
        row["marketTitle"] = row.pop("market_title")
        row["strategyType"] = row.pop("strategy_type")
        row["coverProbability"] = row.pop("cover_probability")
        row["riskState"] = row.pop("risk_state")
    return rows


def make_order_draft(body):
    simulation = simulate_basket(body)
    selected = selected_from_payload(body)
    record = {
        "id": str(uuid.uuid4()),
        "createdAt": utc_now_iso(),
        "marketId": body.get("marketId") or "",
        "marketTitle": body.get("marketTitle") or "",
        "side": "BUY",
        "selectedOutcomes": selected,
        "budget": simulation["budget"],
        "limitOrders": simulation["orders"],
        "status": "draft",
        "notes": body.get("notes") or "Manual confirmation required. No live order was submitted.",
    }
    db_execute(
        """
        INSERT INTO order_drafts
        (id, created_at, market_id, market_title, side, selected_outcomes,
         budget, limit_orders, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["id"],
            record["createdAt"],
            record["marketId"],
            record["marketTitle"],
            record["side"],
            json.dumps(selected, ensure_ascii=False),
            record["budget"],
            json.dumps(simulation["orders"], ensure_ascii=False),
            record["status"],
            record["notes"],
        ),
    )
    return record


def list_order_drafts():
    rows = db_rows("SELECT * FROM order_drafts ORDER BY created_at DESC LIMIT 100")
    for row in rows:
        row["selectedOutcomes"] = json.loads(row.pop("selected_outcomes"))
        row["limitOrders"] = json.loads(row.pop("limit_orders"))
        row["createdAt"] = row.pop("created_at")
        row["marketId"] = row.pop("market_id")
        row["marketTitle"] = row.pop("market_title")
    return rows


def json_response(handler, status, payload):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw or "{}")


def content_type_for(path):
    suffix = path.suffix.lower()
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
    }.get(suffix, "application/octet-stream")


class TraderHandler(BaseHTTPRequestHandler):
    server_version = "MuskTweetTrader/0.1"

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def do_GET(self):
        parsed = parse.urlparse(self.path)
        path = parsed.path
        query = parse.parse_qs(parsed.query)

        try:
            if path == "/api/health":
                return json_response(self, 200, {"ok": True, "time": utc_now_iso(), "db": str(DB_PATH)})
            if path == "/api/markets":
                refresh = query.get("refresh", ["0"])[0] == "1"
                return json_response(self, 200, markets_payload(refresh=refresh))
            if path == "/api/resolve-market":
                value = query.get("input", [""])[0]
                item = resolve_market_input(value)
                return json_response(self, 200, {"market": item})
            if path == "/api/tracker":
                item = fetch_tracker_for_market(
                    query.get("slug", [""])[0],
                    query.get("startTime", [""])[0],
                    query.get("endTime", [""])[0],
                )
                return json_response(self, 200, item)
            if path == "/api/paper-trades":
                return json_response(self, 200, {"items": list_paper_trades()})
            if path == "/api/order-drafts":
                return json_response(self, 200, {"items": list_order_drafts()})
            return self.serve_static(path)
        except Exception as exc:
            return json_response(self, 500, {"ok": False, "error": str(exc)})

    def do_POST(self):
        parsed = parse.urlparse(self.path)
        path = parsed.path
        try:
            body = read_json(self)
            if path == "/api/basket/simulate":
                return json_response(self, 200, simulate_basket(body))
            if path == "/api/paper-trades":
                return json_response(self, 201, make_paper_trade(body))
            if path == "/api/order-drafts":
                return json_response(self, 201, make_order_draft(body))
            return json_response(self, 404, {"ok": False, "error": "Not found"})
        except Exception as exc:
            return json_response(self, 500, {"ok": False, "error": str(exc)})

    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        rel = Path(path.lstrip("/"))
        target = (PUBLIC_DIR / rel).resolve()
        if not str(target).startswith(str(PUBLIC_DIR.resolve())) or not target.exists() or target.is_dir():
            return json_response(self, 404, {"ok": False, "error": "Not found"})

        raw = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type_for(target))
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)


def main():
    init_db()
    port = int(os.environ.get("PORT", "8787"))
    server = ThreadingHTTPServer(("127.0.0.1", port), TraderHandler)
    print(f"Musk Tweet Trader running at http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
