#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. Mark 3 -- CORE (tools, brain, scheduler, voice-in).
Keep this file in the same folder as jarvis_mk3.py (the HUD).
"""
from __future__ import annotations

import ast
import base64
import datetime as dt
import html as htmllib
import inspect
import io
import json
import math
import operator
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse as up
import webbrowser
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

# =====================================================================
# CONFIG  -- edit these
# =====================================================================
MODEL = "jarvis-qwen"
OLLAMA = "http://localhost:11434"
BASE_TEMP = 0.6
CHAOS_CHANCE = 0.0             # 0 = no random temperature spikes (they made him odd/rude). 0.05 = 5% of replies
CHAOS_RANGE = (1.2, 1.7)
MAX_TOKENS = 150               # shorter replies = faster (was 350)
NUM_CTX = 4096                 # smaller memory window = faster on CPU
HISTORY_TURNS = 5              # how many past exchanges he remembers in a chat
TOOL_CAP = 1500                # max characters of tool data fed to the model
CALL_ME = "sir"                # default name; say "call me Harel" to change it
WEB_AUTO = True                # True: he searches the web by himself for "latest/price/who won" questions

HOME = {"name": "Simprug, Jakarta", "lat": -6.2335, "lon": 106.7845, "tz": "Asia/Jakarta"}

NEWS_FEEDS = {
    "BBC World": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Antara (Indonesia)": "https://en.antaranews.com/rss/news.xml",
    "Detik (Indonesia)": "https://rss.detik.com/index.php/detikcom",
    "CNN Indonesia": "https://www.cnnindonesia.com/nasional/rss",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "The Guardian": "https://www.theguardian.com/world/rss",
    "NPR": "https://feeds.npr.org/1001/rss.xml",
    "TechCrunch": "https://techcrunch.com/feed/",
    "The Verge": "https://www.theverge.com/rss/index.xml",
    "Hacker News": "https://hnrss.org/frontpage",
}
DEFAULT_NEWS = ("BBC World", "Antara (Indonesia)", "Al Jazeera")     # used when you just say "news"
NEWS_GROUPS = {
    "tech": ("TechCrunch", "The Verge", "Hacker News"),
    "indonesia": ("Antara (Indonesia)", "Detik (Indonesia)", "CNN Indonesia"),
    "world": ("BBC World", "Al Jazeera", "The Guardian", "NPR"),
}
NEWS_ALIAS = [(r"\bbbc\b", "bbc"), (r"\bantara\b", "antara"), (r"\bdetik\b", "detik"), (r"\bcnn\b", "cnn"),
              (r"\bal ?jazeera\b", "al jazeera"), (r"\bguardian\b", "guardian"), (r"\bnpr\b", "npr"),
              (r"\btechcrunch\b", "techcrunch"), (r"\bverge\b", "verge"), (r"\bhacker ?news\b", "hacker"),
              (r"\b(tech|technology|gadgets?)\b", "tech"), (r"\b(indonesia|indonesian|local|jakarta)\b", "indonesia"),
              (r"\b(world|global|international)\b", "world")]

# websites you can open by name: "open github", "open tokopedia"
SITES = {
    "google": "https://www.google.com", "gmail": "https://mail.google.com", "youtube": "https://www.youtube.com",
    "github": "https://github.com", "reddit": "https://www.reddit.com", "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai", "whatsapp": "https://web.whatsapp.com", "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com", "twitter": "https://x.com", "x": "https://x.com",
    "linkedin": "https://www.linkedin.com", "netflix": "https://www.netflix.com", "tiktok": "https://www.tiktok.com",
    "tokopedia": "https://www.tokopedia.com", "shopee": "https://shopee.co.id", "traveloka": "https://www.traveloka.com",
    "maps": "https://www.google.com/maps", "google maps": "https://www.google.com/maps",
    "drive": "https://drive.google.com", "google drive": "https://drive.google.com",
    "docs": "https://docs.google.com", "sheets": "https://sheets.google.com", "calendar": "https://calendar.google.com",
    "translate": "https://translate.google.com", "wikipedia": "https://en.wikipedia.org",
    "stackoverflow": "https://stackoverflow.com", "stack overflow": "https://stackoverflow.com",
    "huggingface": "https://huggingface.co", "hugging face": "https://huggingface.co",
    "kaggle": "https://www.kaggle.com", "ollama": "https://ollama.com", "unsloth": "https://unsloth.ai",
    "amazon": "https://www.amazon.com", "ebay": "https://www.ebay.com", "pinterest": "https://www.pinterest.com",
    "twitch": "https://www.twitch.tv", "discord": "https://discord.com/app", "spotify web": "https://open.spotify.com",
    "detik": "https://www.detik.com", "kompas": "https://www.kompas.com", "bbc": "https://www.bbc.com/news",
    "cnn": "https://edition.cnn.com", "imdb": "https://www.imdb.com",
}
# "search github for ollama python" / "find laptops on tokopedia"
SEARCH_SITES = {
    "google": "https://www.google.com/search?q={}", "youtube": "https://www.youtube.com/results?search_query={}",
    "github": "https://github.com/search?q={}", "reddit": "https://www.reddit.com/search/?q={}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={}", "amazon": "https://www.amazon.com/s?k={}",
    "tokopedia": "https://www.tokopedia.com/search?q={}", "shopee": "https://shopee.co.id/search?keyword={}",
    "stackoverflow": "https://stackoverflow.com/search?q={}", "maps": "https://www.google.com/maps/search/{}",
    "x": "https://x.com/search?q={}", "spotify": "https://open.spotify.com/search/{}",
    "imdb": "https://www.imdb.com/find/?q={}", "bing": "https://www.bing.com/search?q={}",
    "huggingface": "https://huggingface.co/models?search={}", "ebay": "https://www.ebay.com/sch/i.html?_nkw={}",
}
SITE_ALIAS = {"google": "google", "youtube": "youtube", "yt": "youtube", "github": "github", "reddit": "reddit",
              "wikipedia": "wikipedia", "wiki": "wikipedia", "amazon": "amazon", "tokopedia": "tokopedia",
              "shopee": "shopee", "stack overflow": "stackoverflow", "stackoverflow": "stackoverflow",
              "google maps": "maps", "maps": "maps", "twitter": "x", "x": "x", "spotify": "spotify",
              "imdb": "imdb", "bing": "bing", "hugging face": "huggingface", "huggingface": "huggingface",
              "ebay": "ebay"}
SITE_RE = "|".join(sorted((re.escape(k) for k in SITE_ALIAS), key=len, reverse=True))

NAMES = ("jarvis", "jarvas", "jarves", "jervis", "javis")          # + common mishearings
WAKE_PREFIXES = ("wake up", "hey", "yo", "ok", "okay", "hi", "hello", "sup", "oi", "hey there")
WAKE_ON_BARE_NAME = True       # True: just saying "jarvis" works. False: needs a prefix ("hey jarvis")

PIPER_EXE = r"C:\piper\piper.exe"                  # optional; falls back to Windows built-in voice
PIPER_VOICE = r"C:\piper\voices\jarvis-high.onnx"       # if this exact file is missing, any jarvis*.onnx nearby is used
TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"   # text recognition (OCR)
OCR_LANG = "eng"               # "eng+ind" if you installed the Indonesian Tesseract language data
NO_THINK = True                # always skip Qwen's thinking phase (forced at the prompt level)
VISION_MODEL = "auto"          # "auto" = use the best vision model you have installed (or name one, e.g. "moondream")
VISION_PREFER = ("qwen2.5vl", "gemma3:4b", "gemma3:12b", "minicpm-v", "llava", "moondream")
VISION_KEEP = "2m"             # how long the vision model stays in RAM after use

SFX_ON = True
DEADLINE_WARN_HOURS = 24
STOP_WORDS = {"stop", "shut up", "be quiet", "quiet", "silence", "enough", "stop talking", "cancel that"}

DATA = Path(__file__).resolve().parent / "jarvis_data"
DATA.mkdir(exist_ok=True)
UA = {"User-Agent": "JarvisMk3/1.0 (personal assistant)"}
NOWIN = 0x08000000 if os.name == "nt" else 0       # no flashing console windows

# =====================================================================
# STORAGE
# =====================================================================
LOCK = threading.RLock()


def load(name, default):
    try:
        return json.loads((DATA / f"{name}.json").read_text("utf-8"))
    except Exception:
        return default


def save(name, obj):
    with LOCK:
        (DATA / f"{name}.json").write_text(json.dumps(obj, indent=2, ensure_ascii=False), "utf-8")


def call_me():
    return load("settings", {}).get("call_me", CALL_ME)


# =====================================================================
# TIME PARSING
# =====================================================================
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def human_secs(s):
    s = int(s)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if sec and not h:
        parts.append(f"{sec} second{'s' if sec != 1 else ''}")
    return " ".join(parts) or "0 seconds"


def fmt_dt(d):
    now = dt.datetime.now()
    if d.date() == now.date():
        day = "today"
    elif d.date() == (now + dt.timedelta(days=1)).date():
        day = "tomorrow"
    else:
        day = d.strftime("%a %d %b")
    return f"{day} at {d.strftime('%H:%M')}"


def parse_duration(text):
    t = str(text).lower()
    t = (t.replace("half an hour", "30 minutes").replace("an hour", "1 hour")
          .replace("a minute", "1 minute").replace("a second", "1 second"))
    total = 0.0
    for n, u in re.findall(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", t):
        total += float(n) * {"h": 3600, "m": 60, "s": 1}[u[0]]
    return int(total)


def parse_when(text, now=None):
    now = now or dt.datetime.now()
    t = str(text).lower()
    m = re.search(r"\bin\s+((?:\d|an?\s|half).*)", t)
    if m:
        secs = parse_duration(m.group(1))
        if secs > 0:
            return now + dt.timedelta(seconds=secs)
    date = None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            date = dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    elif "tomorrow" in t:
        date = now.date() + dt.timedelta(days=1)
    elif "today" in t or "tonight" in t:
        date = now.date()
    else:
        for i, w in enumerate(WEEKDAYS):
            if re.search(rf"\b{w}\b", t):
                date = now.date() + dt.timedelta(days=((i - now.weekday()) % 7) or 7)
                break
    tm = None
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)", t)
    if m:
        h = int(m[1]) % 12 + (12 if m[3].startswith("p") else 0)
        tm = (h, int(m[2] or 0))
    else:
        m = re.search(r"\b(\d{1,2}):(\d{2})\b", t)
        if m:
            tm = (int(m[1]), int(m[2]))
        elif "noon" in t:
            tm = (12, 0)
        elif "midnight" in t:
            tm = (0, 0)
        else:
            m = re.search(r"\bat\s+(\d{1,2})\b", t)
            if m:
                tm = (int(m[1]), 0)
    if tm and not (0 <= tm[0] < 24 and 0 <= tm[1] < 60):
        tm = None
    if date is None and tm is None:
        return None
    if tm is None:
        tm = (20, 0) if "tonight" in t else (9, 0)
    if date is None:
        cand = dt.datetime.combine(now.date(), dt.time(*tm))
        return cand if cand > now else cand + dt.timedelta(days=1)
    return dt.datetime.combine(date, dt.time(*tm))


_TIME_START = re.compile(
    r"\b(at \d|at noon|at midnight|in \d+|in (?:an?|half) |tomorrow|tonight|today|"
    r"on (?:" + "|".join(WEEKDAYS) + r")|next (?:" + "|".join(WEEKDAYS) + r")|"
    r"(?:" + "|".join(WEEKDAYS) + r")|\d{4}-\d{2}-\d{2}|\d{1,2}(?::\d{2})?\s*(?:am|pm))", re.I)


def split_title_when(text, allow_by=False):
    s = re.sub(r"^\s*(?:please\s+)?(?:remind me(?: to)?|set (?:a )?reminder(?: to| for)?|"
               r"schedule(?: a| an)?|add(?: a| an)?|put|create(?: a| an)?|new)\s+", "", text.strip(), flags=re.I)
    s = re.sub(r"^(?:deadline\s*)?(?:for|to|:)\s+", "", s, flags=re.I)
    pat = _TIME_START
    if allow_by:
        pat = re.compile(r"\bby\b\s*(?=\S)|" + _TIME_START.pattern, re.I)
    m = pat.search(s)
    if m and m.start() > 0:
        title, when = s[:m.start()].strip(" ,"), s[m.start():]
    else:
        title, when = s.strip(), s
    title = re.sub(r"\s+(?:to|on|in)\s+(?:my\s+)?(?:calendar|schedule|list)$", "", title, flags=re.I)
    return (title or "reminder"), when


# =====================================================================
# TOOLS
# =====================================================================
TOOLS = {}
QUIP_TOOLS = {"set_timer", "set_alarm", "add_event", "add_deadline", "cancel", "remember",
              "set_volume", "open_app", "youtube", "site_search"}
QUIPS = ["As you wish.", "Certainly.", "Done.", "Right away.", "Of course.", "Consider it done."]


def tool(name, usage, direct=False):
    def deco(fn):
        TOOLS[name] = {"fn": fn, "usage": usage, "direct": direct}
        return fn
    return deco


def run_tool(name, args):
    fn = TOOLS[name]["fn"]
    try:
        params = inspect.signature(fn).parameters
        return str(fn(**{k: v for k, v in (args or {}).items() if k in params}))
    except TypeError as e:
        return f"Bad arguments for {name}: {e}"
    except Exception as e:
        return f"{name} failed: {e}"


def _ddgs():
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
            return DDGS
        except ImportError:
            return None


# ---- time ------------------------------------------------------------
@tool("get_time", "get_time() - current date and time", direct=True)
def t_time():
    return dt.datetime.now().strftime("It's %A, %d %B %Y, %H:%M.")


# ---- weather ---------------------------------------------------------
WMO = {0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
       61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers",
       81: "rain showers", 82: "violent rain showers", 85: "snow showers", 86: "snow showers",
       95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm with hail"}


@tool("weather", "weather(place?) - current weather + 3 day outlook; no place = home (Simprug, Jakarta)")
def t_weather(place=None):
    loc = HOME
    if place and str(place).lower().strip() not in ("", "here", "home", "simprug", "my area", "local", "outside"):
        try:
            g = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                             params={"name": place, "count": 1}, headers=UA, timeout=10).json()
            r = g["results"][0]
            loc = {"name": f'{r["name"]}, {r.get("country", "")}', "lat": r["latitude"],
                   "lon": r["longitude"], "tz": r.get("timezone", "auto")}
        except Exception:
            return f"I couldn't find a place called {place}."
    try:
        j = requests.get("https://api.open-meteo.com/v1/forecast", headers=UA, timeout=10, params={
            "latitude": loc["lat"], "longitude": loc["lon"], "timezone": loc["tz"], "forecast_days": 3,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}).json()
        c, d = j["current"], j["daily"]
        out = (f"{loc['name']} now: {WMO.get(c['weather_code'], 'unsettled')}, {c['temperature_2m']:.0f}C "
               f"(feels {c['apparent_temperature']:.0f}C), humidity {c['relative_humidity_2m']}%, "
               f"wind {c['wind_speed_10m']:.0f} km/h.")
        names = ["Today", "Tomorrow", "Day after"]
        for i in range(3):
            out += (f" {names[i]}: {WMO.get(d['weather_code'][i], 'unsettled')}, "
                    f"{d['temperature_2m_min'][i]:.0f}-{d['temperature_2m_max'][i]:.0f}C, "
                    f"rain chance {d['precipitation_probability_max'][i]}%.")
        return out
    except Exception as e:
        return f"Weather service unreachable ({type(e).__name__})."


# ---- news ------------------------------------------------------------
def _rss(url, n):
    r = requests.get(url, headers=UA, timeout=10)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = list(root.iter("item"))
    if items:
        titles = [(i.findtext("title") or "").strip() for i in items]
    else:                                              # Atom feeds (The Verge etc.)
        ns = "{http://www.w3.org/2005/Atom}"
        titles = [(e.findtext(ns + "title") or "").strip() for e in root.iter(ns + "entry")]
    return [t for t in titles if t][:n]


def _news_topic(topic, count):
    D = _ddgs()
    if not D:
        return "News search isn't installed. Run: pip install ddgs"
    try:
        res = D().news(str(topic), max_results=count)
        lines = [f"{r.get('title', '')} ({r.get('source', '')})" for r in res]
        return (f"News about {topic}: " + " | ".join(lines)) if lines else f"No news found about {topic}."
    except Exception as e:
        return f"News search failed ({type(e).__name__})."


@tool("news", "news(source?, count?, topic?) - headlines. source: bbc, antara, detik, cnn, al jazeera, guardian, npr, "
              "techcrunch, verge, hacker news, or a group: tech / indonesia / world. topic = news about a subject")
def t_news(source=None, count=4, topic=None):
    try:
        count = max(1, min(int(count), 8))
    except Exception:
        count = 4
    if topic:
        return _news_topic(topic, count)
    s = str(source or "").lower().strip()
    if s in NEWS_GROUPS:
        names = NEWS_GROUPS[s]
    elif s:
        names = [n for n in NEWS_FEEDS if s in n.lower()]
    else:
        names = DEFAULT_NEWS
    out = []
    for name in names:
        try:
            out.append(f"{name}: " + " | ".join(_rss(NEWS_FEEDS[name], count)))
        except Exception:
            out.append(f"{name}: unavailable right now")
    return "\n".join(out) or "No matching news source."


# ---- knowledge -------------------------------------------------------
@tool("wikipedia", "wikipedia(topic) - short factual summary of a person, place or thing")
def t_wiki(topic):
    try:
        s = requests.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=10, params={
            "action": "opensearch", "search": topic, "limit": 1, "format": "json"}).json()
        if not s[1]:
            return f"Wikipedia has nothing on '{topic}'."
        title = s[1][0]
        j = requests.get("https://en.wikipedia.org/api/rest_v1/page/summary/" + up.quote(title.replace(" ", "_")),
                         headers=UA, timeout=10).json()
        sents = re.split(r"(?<=[.!?])\s+", j.get("extract", ""))
        return f"{title}: " + " ".join(sents[:3])
    except Exception as e:
        return f"Wikipedia lookup failed ({type(e).__name__})."


@tool("web_search", "web_search(query) - quick web search, short snippets")
def t_search(query):
    D = _ddgs()
    if not D:
        return "Web search isn't installed. Run: pip install ddgs"
    try:
        res = D().text(str(query), max_results=4)
        return "\n".join(f"{r['title']}: {r['body'][:220]}" for r in res) or "No results."
    except Exception as e:
        return f"Search failed ({type(e).__name__})."


def _page_text(url, limit=1500):
    u = str(url).strip()
    if not u.startswith("http"):
        u = "https://" + u
    r = requests.get(u, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}, timeout=6)
    r.raise_for_status()
    h = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|form|aside)\b.*?</\1>", " ", r.text)
    paras = [re.sub(r"(?s)<[^>]+>", " ", p) for p in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", h)]
    paras = [re.sub(r"\s+", " ", htmllib.unescape(p)).strip() for p in paras]
    text = " ".join(p for p in paras if len(p) > 60)
    if len(text) < 200:
        text = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"(?s)<[^>]+>", " ", h))).strip()
    return text[:limit]


@tool("research", "research(query) - DEEP web research: searches AND reads the top page. Use for anything recent, "
                  "uncertain or factual that you might get wrong from memory")
def t_research(query):
    D = _ddgs()
    if not D:
        return "Web search isn't installed. Run: pip install ddgs"
    try:
        res = D().text(str(query), max_results=5)
    except Exception as e:
        return f"Search failed ({type(e).__name__})."
    if not res:
        return "No results."
    out = ["Search results:"] + [f"- {r['title']}: {r['body'][:200]}" for r in res[:4]]
    for r in res[:3]:                      # read only ONE page (faster)
        try:
            out.append(f"Page ({r['title'][:50]}): " + _page_text(r["href"], 700))
            break
        except Exception:
            continue
    return "\n".join(out)


@tool("read_page", "read_page(url) - open a web page or article and return its text so you can summarise it")
def t_read_page(url):
    try:
        t = _page_text(url, 1500)
        return ("Page text: " + t) if t else "That page has no readable text."
    except Exception as e:
        return f"I couldn't open that page ({type(e).__name__})."


@tool("define", "define(word) - dictionary definition of an English word", direct=True)
def t_define(word):
    w = str(word).strip().lower()
    try:
        r = requests.get("https://api.dictionaryapi.dev/v2/entries/en/" + up.quote(w), headers=UA, timeout=8)
        if r.status_code == 404:
            return f"No dictionary entry for '{w}'."
        m = r.json()[0]["meanings"][0]
        return f"{w} ({m['partOfSpeech']}): {m['definitions'][0]['definition']}"
    except Exception as e:
        return f"Dictionary lookup failed ({type(e).__name__})."


# ---- calculator ------------------------------------------------------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv,
        ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUN = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "log": math.log10,
        "ln": math.log, "abs": abs, "round": round}
_CONST = {"pi": math.pi, "e": math.e}


def _ev(n):
    if isinstance(n, ast.Expression):
        return _ev(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        a, b = _ev(n.left), _ev(n.right)
        if isinstance(n.op, ast.Pow) and (abs(b) > 1000 or abs(a) > 1e6):
            raise ValueError("too big")
        return _OPS[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
        return _OPS[type(n.op)](_ev(n.operand))
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUN:
        return _FUN[n.func.id](*[_ev(a) for a in n.args])
    if isinstance(n, ast.Name) and n.id in _CONST:
        return _CONST[n.id]
    raise ValueError("unsupported")


@tool("calculator", "calculator(expression) - exact maths, e.g. '12*(3+4)/7' or 'sqrt(144)'", direct=True)
def t_calc(expression):
    e = str(expression).lower().replace("^", "**").replace("\u00d7", "*").replace("\u00f7", "/")
    e = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", e)
    try:
        v = _ev(ast.parse(e.strip(), mode="eval"))
        return f"{expression} = {round(v, 6) if isinstance(v, float) else v}"
    except ZeroDivisionError:
        return "That is a division by zero, I'm afraid."
    except Exception:
        return "I couldn't evaluate that."


# ---- converter (units + currency) -------------------------------------
UNIT_ALIAS = {"kilometers": "km", "kilometres": "km", "kilometer": "km", "kms": "km", "meters": "m",
              "metres": "m", "meter": "m", "centimeters": "cm", "centimetres": "cm", "millimeters": "mm",
              "miles": "mi", "mile": "mi", "feet": "ft", "foot": "ft", "inches": "in", "inch": "in",
              "yards": "yd", "yard": "yd", "kilograms": "kg", "kilogram": "kg", "kilos": "kg", "kilo": "kg",
              "kgs": "kg", "grams": "g", "gram": "g", "pounds": "lb", "pound": "lb", "lbs": "lb",
              "ounces": "oz", "ounce": "oz", "liters": "l", "litres": "l", "liter": "l", "litre": "l",
              "milliliters": "ml", "gallons": "gal", "gallon": "gal", "celsius": "c", "centigrade": "c",
              "fahrenheit": "f", "kelvin": "k"}
UNIT_BASE = {"len": {"m": 1, "km": 1000, "cm": 0.01, "mm": 0.001, "mi": 1609.344, "ft": 0.3048, "in": 0.0254,
                     "yd": 0.9144},
             "mass": {"kg": 1, "g": 0.001, "lb": 0.45359237, "oz": 0.028349523},
             "vol": {"l": 1, "ml": 0.001, "gal": 3.785411784}}
CUR_ALIAS = {"dollar": "USD", "dollars": "USD", "bucks": "USD", "rupiah": "IDR", "euro": "EUR", "euros": "EUR",
             "yen": "JPY", "pound": "GBP", "pounds": "GBP", "sterling": "GBP", "ringgit": "MYR", "baht": "THB",
             "yuan": "CNY", "rupee": "INR", "rupees": "INR"}
CUR_CODES = {"USD", "EUR", "GBP", "JPY", "IDR", "AUD", "SGD", "MYR", "THB", "KRW", "CNY", "INR", "CAD", "CHF",
             "NZD", "HKD", "PHP", "VND", "SAR", "AED", "BRL", "MXN", "TRY", "ZAR", "RUB"}


def _unit(u):
    u = UNIT_ALIAS.get(str(u).lower().strip(), str(u).lower().strip())
    for cat, d in UNIT_BASE.items():
        if u in d:
            return cat, u
    if u in ("c", "f", "k"):
        return "temp", u
    return None


def _cur(u):
    u = str(u).lower().strip()
    if u in CUR_ALIAS:
        return CUR_ALIAS[u]
    return u.upper() if u.upper() in CUR_CODES else None


def _convertible(a, b):
    ua, ub = _unit(a), _unit(b)
    if _cur(a) and _cur(b):
        return True
    return bool(ua and ub and ua[0] == ub[0])


@tool("convert", "convert(amount, from_unit, to_unit) - units (km, miles, kg, lb, celsius, fahrenheit, litres) or "
                 "currencies (USD, IDR, EUR, dollars, rupiah)", direct=True)
def t_convert(amount, from_unit, to_unit):
    try:
        x = float(str(amount).replace(",", ""))
    except ValueError:
        return "I need a number to convert."
    a, b = str(from_unit), str(to_unit)
    ca, cb = _cur(a), _cur(b)
    if ca and cb:
        if ca == cb:
            return f"{x:g} {ca} is {x:g} {cb}."
        try:
            j = requests.get(f"https://open.er-api.com/v6/latest/{ca}", headers=UA, timeout=10).json()
            v = x * j["rates"][cb]
            shown = f"{v:,.0f}" if v >= 1000 else f"{v:,.2f}"
            return f"{x:,g} {ca} = {shown} {cb} (live rate)."
        except Exception as e:
            return f"Exchange rate lookup failed ({type(e).__name__})."
    ua, ub = _unit(a), _unit(b)
    if not (ua and ub and ua[0] == ub[0]):
        return f"I can't convert {a} to {b}."
    cat, u1 = ua
    u2 = ub[1]
    if cat == "temp":
        c = x if u1 == "c" else (x - 32) * 5 / 9 if u1 == "f" else x - 273.15
        v = c if u2 == "c" else c * 9 / 5 + 32 if u2 == "f" else c + 273.15
    else:
        v = x * UNIT_BASE[cat][u1] / UNIT_BASE[cat][u2]
    return f"{x:g} {u1} = {round(v, 3):,} {u2}."


# ---- schedule: timers, alarms, events --------------------------------
def _add_item(kind, label, due, repeat=None):
    with LOCK:
        s = load("schedule", {"items": []})
        it = {"id": max([i["id"] for i in s["items"]], default=0) + 1, "kind": kind, "label": label,
              "due": due.isoformat(timespec="seconds"), "repeat": repeat}
        s["items"].append(it)
        save("schedule", s)
    return it


@tool("set_timer", "set_timer(duration, label?) - countdown timer, duration like '10 minutes' or '1h 30m'", direct=True)
def t_timer(duration, label=""):
    d = str(duration).strip()
    secs = int(d) * 60 if d.isdigit() else parse_duration(d)
    if secs <= 0:
        return "How long should the timer run?"
    it = _add_item("timer", label or "timer", dt.datetime.now() + dt.timedelta(seconds=secs))
    return f"Timer #{it['id']} set for {human_secs(secs)}" + (f" ({label})." if label else ".")


@tool("set_alarm", "set_alarm(when, label?) - alarm at a clock time, e.g. '7am', 'tomorrow 6:30', 'monday 8am'. "
                   "Add 'daily' to repeat", direct=True)
def t_alarm(when, label=""):
    d = parse_when(when)
    if not d:
        return "What time should I set it for?"
    repeat = "daily" if re.search(r"\b(daily|every day|everyday)\b", str(when).lower()) else None
    it = _add_item("alarm", label or "alarm", d, repeat)
    return f"Alarm #{it['id']} set for {fmt_dt(d)}" + (", repeating daily." if repeat else ".")


@tool("add_event", "add_event(title, when) - schedule an event or reminder, e.g. title='dentist', when='friday 3pm'",
      direct=True)
def t_event(title, when):
    d = parse_when(when)
    if not d:
        return "When is it? Give me a time or a day."
    it = _add_item("event", title, d)
    return f"Noted: {title}, {fmt_dt(d)} (#{it['id']})."


@tool("list_schedule", "list_schedule() - upcoming timers, alarms and events", direct=True)
def t_list_sched():
    items = sorted(load("schedule", {"items": []})["items"], key=lambda i: i["due"])
    if not items:
        return "Nothing scheduled."
    now = dt.datetime.now()
    lines = []
    for i in items[:12]:
        d = dt.datetime.fromisoformat(i["due"])
        extra = f" (in {human_secs((d - now).total_seconds())})" if i["kind"] == "timer" else ""
        lines.append(f"#{i['id']} {i['kind']} '{i['label']}' {fmt_dt(d)}{extra}")
    return "; ".join(lines) + "."


@tool("cancel", "cancel(query) - cancel timers/alarms/events by id number, label, or kind ('timer', 'alarm', 'event')",
      direct=True)
def t_cancel(query):
    q = str(query).lower().strip()
    with LOCK:
        s = load("schedule", {"items": []})
        keep, gone = [], []
        for i in s["items"]:
            hit = (q.isdigit() and int(q) == i["id"]) or (not q.isdigit() and (
                q in i["label"].lower() or q in (i["kind"], i["kind"] + "s", "reminder", "reminders")
                and (q.startswith("remind") is False or i["kind"] == "event")))
            (gone if hit else keep).append(i)
        if gone:
            s["items"] = keep
            save("schedule", s)
    return f"Cancelled {len(gone)} item{'s' if len(gone) != 1 else ''}." if gone else "Nothing matched that."


# ---- deadlines -------------------------------------------------------
@tool("add_deadline", "add_deadline(task, due?) - track a deadline; due optional, e.g. 'friday 5pm'", direct=True)
def t_add_deadline(task, due=None):
    d = parse_when(due) if due else None
    with LOCK:
        s = load("deadlines", {"items": []})
        it = {"id": max([i["id"] for i in s["items"]], default=0) + 1, "task": task,
              "due": d.isoformat(timespec="seconds") if d else None, "warned": False}
        s["items"].append(it)
        save("deadlines", s)
    return f"Deadline logged: {task}" + (f", due {fmt_dt(d)}." if d else ", no due date.")


@tool("list_deadlines", "list_deadlines() - all open deadlines", direct=True)
def t_list_deadlines():
    items = load("deadlines", {"items": []})["items"]
    if not items:
        return "No open deadlines."
    items.sort(key=lambda i: i["due"] or "9999")
    now = dt.datetime.now()
    out = []
    for i in items:
        if i["due"]:
            d = dt.datetime.fromisoformat(i["due"])
            out.append(f"#{i['id']} {i['task']} - {'OVERDUE, was ' if d < now else 'due '}{fmt_dt(d)}")
        else:
            out.append(f"#{i['id']} {i['task']} - no date")
    return "; ".join(out) + "."


@tool("complete_deadline", "complete_deadline(query) - mark a deadline done by id or part of its name", direct=True)
def t_done_deadline(query):
    q = str(query).lower().strip()
    with LOCK:
        s = load("deadlines", {"items": []})
        keep, gone = [], []
        for i in s["items"]:
            ((gone if (q.isdigit() and int(q) == i["id"]) or (q and not q.isdigit() and q in i["task"].lower())
              else keep)).append(i)
        if gone:
            s["items"] = keep
            save("deadlines", s)
    return f"Crossed off: {', '.join(g['task'] for g in gone)}." if gone else "No deadline matched that."


# ---- memory ----------------------------------------------------------
@tool("remember", "remember(fact) - save something about the user for later", direct=True)
def t_remember(fact):
    with LOCK:
        m = load("memory", {"facts": []})
        m["facts"].append(str(fact).strip())
        save("memory", m)
    return "Noted."


@tool("recall", "recall() - list what you remember about the user", direct=True)
def t_recall():
    f = load("memory", {"facts": []})["facts"]
    return "; ".join(f[-15:]) + "." if f else "I don't know anything about you yet."


@tool("forget", "forget(query) - delete saved facts containing this text", direct=True)
def t_forget(query):
    q = str(query).lower().strip()
    with LOCK:
        m = load("memory", {"facts": []})
        keep = [f for f in m["facts"] if q not in f.lower()]
        n = len(m["facts"]) - len(keep)
        if n:
            m["facts"] = keep
            save("memory", m)
    return f"Forgotten {n} thing{'s' if n != 1 else ''}." if n else "I don't have anything like that."


@tool("set_name", "set_name(name) - change what you call the user", direct=True)
def t_set_name(name):
    n = re.sub(r"[^A-Za-z' -]", "", str(name)).strip()[:30]
    if not n:
        return "What should I call you?"
    with LOCK:
        s = load("settings", {})
        s["call_me"] = n
        save("settings", s)
    t_remember(f"The user wants to be called {n}")
    return f"Very well, {n}."


_AUTO_FACT = re.compile(
    r"^(?:i live in|i work (?:at|as|for)|i study|my birthday is|i was born|my favou?rite [\w ]+ is|"
    r"i (?:really )?(?:like|love|hate|prefer)|i(?:'m| am) (?:from|studying|learning|working on|building))\s+\S", re.I)


def _autofact(text):
    f = text.strip(" .!")
    with LOCK:
        m = load("memory", {"facts": []})
        if len(f) < 140 and f.lower() not in [x.lower() for x in m["facts"]]:
            m["facts"].append(f)
            save("memory", m)


# ---- fun -------------------------------------------------------------
JOKES = [
    "I told my computer I needed a break, and it promptly froze.",
    "I would tell you a UDP joke, but you might not receive it.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I have a joke about unemployment, but it doesn't work.",
    "There are only 10 kinds of people: those who understand binary and those who don't.",
    "A SQL query walks into a bar, approaches two tables and asks: may I join you?",
]


@tool("joke", "joke(kind?) - tell a joke. kind: 'dark', 'roast' or empty", direct=True)
def t_joke(kind=""):
    kind = str(kind or "").lower()
    topic = {"roast": "Gently and kindly tease the user for building an AI butler. Warm, never mean.",
             "dark": "Make it dark humor, but not cruel."}.get(kind, "Pick any topic. Keep it clean and witty.")
    sysmsg = ("You are a witty, good-natured comedian. Output exactly ONE short joke (1-2 sentences). "
              "No intro, no explanation. Never target people for race, religion, gender, sexuality or "
              "disability. " + topic)
    try:
        out = ollama_chat([{"role": "system", "content": sysmsg}, {"role": "user", "content": "Go."}],
                          temp=random.uniform(0.8, 1.1), max_tokens=100)
        out = clean(out)
        if len(out) > 8:
            return out
    except Exception:
        pass
    return random.choice(JOKES)


# ---- apps, web, system -----------------------------------------------
def _chrome():
    for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                 os.environ.get("LOCALAPPDATA", "")):
        p = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe") if base else ""
        if p and os.path.exists(p):
            return p
    return shutil.which("chrome")


def open_url(url):
    c = _chrome()
    if c:
        subprocess.Popen([c, url])
    else:
        webbrowser.open(url)


@tool("youtube", "youtube(query?) - play/search YouTube in Chrome; empty query just opens YouTube", direct=True)
def t_youtube(query=""):
    q = str(query or "").strip()
    if not q:
        open_url("https://www.youtube.com")
        return "YouTube is open."
    url = "https://www.youtube.com/results?search_query=" + up.quote_plus(q)
    try:
        page = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}, timeout=8).text
        m = re.search(r'"videoId":"([\w-]{11})"', page)
        if m:
            url = "https://www.youtube.com/watch?v=" + m.group(1)
    except Exception:
        pass
    open_url(url)
    return f"Putting on '{q}'."


@tool("site_search", "site_search(site, query) - open a site's search results in Chrome. site: google, youtube, "
                     "github, reddit, wikipedia, amazon, tokopedia, shopee, stackoverflow, maps, x, spotify, imdb, "
                     "huggingface, ebay", direct=True)
def t_site_search(site, query):
    key = SITE_ALIAS.get(str(site).lower().strip(), str(site).lower().strip())
    tpl = SEARCH_SITES.get(key)
    if not tpl:
        return f"I don't know how to search {site}."
    open_url(tpl.format(up.quote_plus(str(query))))
    return f"Searching {key} for {query}."


APPS = {"notepad": "notepad", "calculator": "calc", "paint": "mspaint", "explorer": "explorer",
        "file explorer": "explorer", "task manager": "taskmgr", "settings": "start ms-settings:",
        "cmd": "start cmd", "terminal": "start wt", "vscode": "code", "vs code": "code",
        "spotify": "start spotify:", "word": "start winword", "excel": "start excel",
        "edge": "start msedge", "downloads": f'explorer "{Path.home() / "Downloads"}"'}


@tool("open_app", "open_app(name) - open an app (notepad, calculator, chrome, spotify, vscode...) or a website "
                  "(github, gmail, tokopedia, whatsapp, netflix... or any domain)", direct=True)
def t_open(name):
    n = re.sub(r"^(?:the|my)\s+|\s+(?:website|site|page|app|please)$", "", str(name).lower().strip()).strip()
    if n in ("chrome", "google chrome", "browser"):
        open_url("https://www.google.com")
        return "Chrome is open."
    if n in APPS:
        subprocess.Popen(APPS[n], shell=True, creationflags=NOWIN)
        return f"Opening {n}."
    if n in SITES:
        open_url(SITES[n])
        return f"Opening {n}."
    if re.match(r"^(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?$", n):
        open_url(n if n.startswith("http") else "https://" + n)
        return f"Opening {n}."
    return f"I don't know '{n}'. Add it to APPS or SITES at the top of jarvis_core.py and I will."


def _key(vk, times=1):
    import ctypes
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


@tool("set_volume", "set_volume(action) - action: a number 0-100, 'up', 'down' or 'mute'", direct=True)
def t_volume(action):
    if os.name != "nt":
        return "Volume control only works on Windows."
    a = str(action).lower().strip()
    try:
        if a.isdigit():
            n = max(0, min(100, int(a)))
            _key(0xAE, 50)
            _key(0xAF, round(n / 2))
            return f"Volume at {n} percent."
        if a in ("up", "louder", "raise"):
            _key(0xAF, 5)
            return "Louder."
        if a in ("down", "quieter", "lower"):
            _key(0xAE, 5)
            return "Quieter."
        _key(0xAD)
        return "Mute toggled."
    except Exception as e:
        return f"Volume control failed ({e})."


@tool("system_status", "system_status() - battery, CPU, RAM and disk usage", direct=True)
def t_system():
    try:
        import psutil
    except ImportError:
        return "Install psutil for system stats: pip install psutil"
    b = psutil.sensors_battery()
    disk = shutil.disk_usage(os.path.abspath(os.sep))
    return (f"CPU {psutil.cpu_percent(interval=0.5):.0f}%, RAM {psutil.virtual_memory().percent:.0f}%, "
            f"disk {disk.used / disk.total * 100:.0f}% full"
            + (f", battery {b.percent:.0f}%{' (charging)' if b.power_plugged else ''}." if b else "."))


# ---- vision + OCR ----------------------------------------------------
def _active_window():
    try:
        import ctypes
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(u.GetWindowTextLengthW(h) + 1)
        u.GetWindowTextW(h, buf, len(buf))
        return buf.value
    except Exception:
        return ""


def _get_image(source):
    from PIL import Image, ImageGrab
    src = str(source or "screen").strip().strip("\"'")
    low = src.lower()
    if low in ("", "screen", "desktop", "monitor", "my screen"):
        return ImageGrab.grab()
    if low in ("clipboard", "copied", "copied image"):
        img = ImageGrab.grabclipboard()
        if isinstance(img, list) and img:
            img = Image.open(img[0])
        if img is None:
            raise ValueError("there's no image on the clipboard")
        return img
    if low in ("camera", "webcam", "cam"):
        import cv2
        cap = cv2.VideoCapture(0)
        frame, ok = None, False
        for _ in range(6):                      # let the sensor adjust exposure
            ok, frame = cap.read()
        cap.release()
        if not ok:
            raise ValueError("I can't open the camera")
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    path = Path(os.path.expandvars(src))
    if path.exists():
        return Image.open(path)
    raise ValueError(f"I can't find an image at {src}")


def _b64(img, max_side=1024):
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _ocr(img):
    """Return text found in an image, or '' (never raises)."""
    try:
        import pytesseract
        if os.path.exists(TESSERACT_EXE):
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE
        g = img.convert("L")
        if g.width < 1400:
            g = g.resize((g.width * 2, g.height * 2))
        return re.sub(r"\n\s*\n+", "\n", pytesseract.image_to_string(g, lang=OCR_LANG)).strip()
    except Exception:
        return ""


_VIS = {"t": 0.0, "m": None}


def _pick_vision():
    """Best installed vision model (or the one you named in VISION_MODEL)."""
    if VISION_MODEL != "auto":
        return VISION_MODEL
    if _VIS["m"] and time.time() - _VIS["t"] < 60:
        return _VIS["m"]
    try:
        names = [m["name"] for m in requests.get(OLLAMA + "/api/tags", timeout=3).json().get("models", [])]
    except Exception:
        return None
    for pref in VISION_PREFER:
        for n in names:
            if pref in n.lower():
                _VIS.update(t=time.time(), m=n)
                return n
    return None


@tool("look", "look(source?, question?) - IMAGE RECOGNITION: describe/analyse an image. source: 'screen' (default), "
              "'camera', 'clipboard' or an image file path. question = what to find out")
def t_look(source="screen", question=""):
    try:
        img = _get_image(source)
    except ImportError:
        return "Image recognition needs: pip install pillow (and opencv-python for the camera)."
    except Exception as e:
        return f"I couldn't get the image: {e}."
    model = _pick_vision()
    if not model:
        return "No vision model is installed. Run: ollama pull moondream   (better: ollama pull qwen2.5vl:3b)"
    q = (question or "").strip() or "Describe what you see in detail: objects, people, any visible text, and what is going on."
    msg = {"role": "user", "content": q, "images": [_b64(img)]}

    def call(think):
        p = {"model": model, "stream": False, "keep_alive": VISION_KEEP, "messages": [msg],
             "options": {"temperature": 0.2, "num_predict": 320}}
        if think is not None:
            p["think"] = think
        return requests.post(f"{OLLAMA}/api/chat", json=p, timeout=300)

    try:
        r = call(False)
        if r.status_code == 400:                # some models reject the "think" flag
            r = call(None)
        if r.status_code == 404:
            return f"The vision model isn't installed. Run: ollama pull {model}"
        r.raise_for_status()
        desc = clean(r.json()["message"]["content"])
    except requests.exceptions.ConnectionError:
        return "Ollama isn't running."
    except Exception as e:
        return f"Image recognition failed ({type(e).__name__})."
    out = f"Image analysis ({model}): " + desc
    if str(source or "screen").lower() not in ("camera", "webcam", "cam"):
        txt = _ocr(img)
        if txt:
            out += "\nText visible in the image: " + txt[:500]
    return out


@tool("read_text", "read_text(source?) - TEXT RECOGNITION (OCR): read the text in an image. source: 'screen' "
                   "(default), 'camera', 'clipboard' or an image file path")
def t_read_text(source="screen"):
    try:
        import pytesseract  # noqa: F401
        img = _get_image(source)
    except ImportError:
        return "Text recognition needs: pip install pillow pytesseract, plus the Tesseract OCR program."
    except Exception as e:
        return f"I couldn't get the image: {e}."
    txt = _ocr(img)
    win = _active_window() if str(source or "screen").lower() in ("", "screen") else ""
    return (f"Active window: {win}\n" if win else "") + (
        "Text found:\n" + txt[:2000] if txt else "I can't find any readable text there (is Tesseract installed?).")


def _upcoming_today():
    now, end = dt.datetime.now(), dt.datetime.combine(dt.date.today(), dt.time(23, 59, 59))
    its = [i for i in load("schedule", {"items": []})["items"] if i["kind"] != "timer"
           and now <= dt.datetime.fromisoformat(i["due"]) <= end]
    its.sort(key=lambda i: i["due"])
    return "; ".join(f"{i['label']} at {dt.datetime.fromisoformat(i['due']).strftime('%H:%M')}" for i in its)


@tool("briefing", "briefing() - morning briefing: time, weather, today's schedule, deadlines, headlines")
def t_brief():
    return "\n".join([t_time(), t_weather(), "Today's schedule: " + (_upcoming_today() or "nothing"),
                      "Deadlines: " + t_list_deadlines(), "Headlines:\n" + t_news(count=3)])


# =====================================================================
# SOUND EFFECTS + SPEECH OUT
# =====================================================================
SFX = {"wake": [(880, 80), (1320, 110)], "ok": [(1000, 60)], "err": [(300, 220)],
       "alarm": [(1200, 180), (900, 180)] * 4, "start": [(600, 70), (900, 70), (1300, 120)]}


def sfx(kind):
    if not SFX_ON or os.name != "nt":
        return

    def run():
        try:
            import winsound
            for f, d in SFX.get(kind, []):
                winsound.Beep(f, d)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def speakable(text):
    t = re.sub(r"https?://\S+", "", text)
    t = re.sub(r"[*_#`>~|]", "", t)
    t = re.sub(r"[\U00010000-\U0010ffff]", "", t)
    return re.sub(r"\s+", " ", t).strip()


_TTS_LOGGED = set()


def _tts_log(msg):
    """Write why the Jarvis voice failed to jarvis_data\\tts_error.txt (once per reason)."""
    if msg in _TTS_LOGGED:
        return
    _TTS_LOGGED.add(msg)
    try:
        with open(DATA / "tts_error.txt", "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except Exception:
        pass


def find_piper_voice():
    """The configured voice file, or any jarvis*.onnx found nearby."""
    if os.path.exists(PIPER_VOICE):
        return PIPER_VOICE
    folders = [Path(PIPER_VOICE).parent, Path(PIPER_EXE).parent]
    for folder in folders:
        try:
            if not folder.exists():
                continue
            for pat in ("jarvis*high*.onnx", "jarvis*.onnx"):
                hits = sorted(folder.rglob(pat))
                if hits:
                    return str(hits[0])
        except Exception:
            continue
    return None


class Speaker:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.q = queue.Queue()
        self.proc = None
        self.busy = False
        self._stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def say(self, text):
        t = speakable(text)
        if self.enabled and t:
            self.busy = True
            self.q.put(t)

    def stop(self):
        self._stop.set()
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
        except Exception:
            pass
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        self.busy = False

    def _loop(self):
        while True:
            text = self.q.get()
            self._stop.clear()
            try:
                self._speak(text)
            except Exception as e:
                _tts_log(f"TTS error: {e}")
            self.busy = not self.q.empty()

    def _speak(self, text):
        if os.name != "nt":
            return
        voice = find_piper_voice()
        if not os.path.exists(PIPER_EXE):
            _tts_log(f"piper.exe not found at {PIPER_EXE}")
        elif not voice:
            _tts_log(f"No jarvis .onnx voice file found in {Path(PIPER_VOICE).parent}")
        else:
            if not os.path.exists(voice + ".json"):
                _tts_log(f"The voice config file is missing: {voice}.json (it must sit next to the .onnx)")
            wav = os.path.join(tempfile.gettempdir(), "jarvis_tts.wav")
            try:
                if os.path.exists(wav):
                    os.remove(wav)
            except Exception:
                pass
            try:
                p = subprocess.run([PIPER_EXE, "--model", voice, "--output_file", wav],
                                   input=text.encode("utf-8"), capture_output=True, creationflags=NOWIN,
                                   timeout=90)
                if self._stop.is_set():
                    return
                if p.returncode == 0 and os.path.exists(wav):
                    import winsound
                    winsound.PlaySound(wav, winsound.SND_FILENAME)
                    return
                _tts_log("Piper failed: " + p.stderr.decode("utf-8", "ignore")[-400:])
            except Exception as e:
                _tts_log(f"Piper could not run: {e}")
        # fallback: Windows built-in voice
        ps = ("[Console]::InputEncoding=[Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; "
              "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak([Console]::In.ReadToEnd())")
        self.proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", ps],
                                     stdin=subprocess.PIPE, creationflags=NOWIN)
        self.proc.communicate(text.encode("utf-8"))


# =====================================================================
# BRAIN  (jarvis-qwen via Ollama)
# =====================================================================
THINK_RE = re.compile(r"<think>.*?(</think>|$)", re.S)
TOOL_RE = re.compile(r"<(tool|tool_call)>\s*(\{.*?\})\s*</\1>", re.S)


def clean(text):
    t = THINK_RE.sub("", text)
    t = TOOL_RE.sub("", t)
    t = re.sub(r"[*_`#]+", "", t)
    return re.sub(r"[ \t]+", " ", t).strip()


def _chatml(messages):
    parts = [f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages]
    # Pre-filling an empty think block is what actually switches Qwen's thinking off.
    parts.append("<|im_start|>assistant\n" + ("<think>\n\n</think>\n\n" if NO_THINK else ""))
    return "".join(parts)


def ollama_chat(messages, temp=BASE_TEMP, on_token=None, cancel=None, max_tokens=MAX_TOKENS):
    payload = {"model": MODEL, "prompt": _chatml(messages), "raw": True, "stream": True, "keep_alive": "30m",
               "options": {"temperature": temp, "top_p": 0.9, "num_ctx": NUM_CTX, "num_predict": max_tokens,
                           "repeat_penalty": 1.1, "stop": ["<|im_end|>", "<|im_start|>"]}}
    out = ""
    with requests.post(f"{OLLAMA}/api/generate", json=payload, stream=True, timeout=180) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if cancel is not None and cancel.is_set():
                break
            if not line:
                continue
            d = json.loads(line)
            piece = d.get("response", "")
            out += piece
            if on_token and piece:
                on_token(out)
            if d.get("done"):
                break
    return out


PERSONA = (
    "You are J.A.R.V.I.S., the user's personal AI assistant. You are calm, polite, warm and respectful, "
    "with a light touch of dry British wit. You are never rude, never insulting, never sarcastic toward the "
    "user, and you never swear. If the user is mistaken, correct them gently and politely with the facts. "
    "Your replies are spoken aloud, so keep them to 1-2 short sentences, with no emojis, no markdown and "
    "no lists. Address the user as '{call}'."
)


def parse_tool_call(text):
    m = TOOL_RE.search(text)
    if not m:
        return None
    try:
        d = json.loads(m.group(2))
    except Exception:
        return None
    name = d.get("name")
    args = d.get("args", d.get("arguments", {})) or {}
    return (name, args) if name in TOOLS and isinstance(args, dict) else None


WEB_HINT = re.compile(
    r"\b(latest|newest|current(?:ly)?|right now|these days|this (?:week|month|year)|recent(?:ly)?|"
    r"price of|who won|who is the (?:current|new)|score of|release date|stock price|exchange rate|"
    r"top \d+|trending|breaking|202[5-9])\b")


def needs_web(text):
    """True for questions whose answer is probably newer than the model's training."""
    t = text.lower()
    return (len(t.split()) >= 3 and WEB_HINT.search(t) is not None
            and re.search(r"\b(you|your|yourself|my|i'm)\b", t) is None)


def route(text):
    """Fast keyword router: returns (tool, args) for obvious commands, else None (let the model decide)."""
    orig = text.strip()
    t = orig.lower().rstrip("?!. ")
    t = re.sub(r"^(?:(?:hey|yo|ok|okay|please|jarvis|can you|could you|would you|i want you to|go ahead and)[, ]+)+", "", t)

    def has(p):
        return re.search(p, t) is not None

    m = re.search(r"[\"']?([a-zA-Z]:\\[^\"'<>|?*\n]+?\.(?:png|jpe?g|webp|bmp|gif))[\"']?", orig, re.I)
    if m:
        q = (orig[:m.start()] + orig[m.end():]).strip(" ,.")
        if re.search(r"\b(read|text|ocr|transcribe|says|written|words)\b", q.lower()):
            return "read_text", {"source": m.group(1)}
        return "look", {"source": m.group(1), "question": q}
    if has(r"\b(briefing|brief me|good morning|my day)\b"):
        return "briefing", {}
    # cancel
    if has(r"\b(cancel|delete|remove|stop|clear)\b.*\b(timers?|alarms?|reminders?|events?)\b"):
        m = re.search(r"(?:#|number |no\. )(\d+)", t)
        kind = re.search(r"\b(timer|alarm|reminder|event)s?\b", t).group(1)
        rest = re.sub(r"\b(cancel|delete|remove|stop|clear|the|my|a|an|all|timers?|alarms?|reminders?|events?|please)\b",
                      "", t).strip()
        return "cancel", {"query": m.group(1) if m else (rest if re.search(r"[a-z]", rest) else kind)}
    listing = has(r"\b(what|show|list|any|read|tell me|how long|left|remaining|upcoming|my)\b")
    adding = has(r"\b(set|start|add|create|put|schedule|remind|wake me|new)\b")
    # timers
    if has(r"\btimer\b") and (adding or not listing):
        secs = parse_duration(t)
        if secs:
            m = re.search(r"(?:minutes?|hours?|seconds?|mins?)\s+(?:for|to|called)\s+(.+)$", t)
            return "set_timer", {"duration": f"{secs} seconds", "label": m.group(1) if m else ""}
    # alarms
    if has(r"\balarm\b|\bwake me\b") and (adding or not listing) and parse_when(t):
        return "set_alarm", {"when": t}
    # reminders / events
    if has(r"\b(remind me|reminder|schedule|appointment|meeting)\b") and adding and parse_when(t):
        title, when = split_title_when(orig)
        return "add_event", {"title": title, "when": when}
    if has(r"\b(timers?|alarms?|schedule|agenda|calendar|reminders?|events?)\b") and listing:
        return "list_schedule", {}
    # deadlines
    if has(r"\bdeadlines?\b"):
        if has(r"\b(done|finished|complete[d]?|submitted|remove|delete|cross off)\b"):
            q = re.sub(r"\b(mark|as|done|finished|complete[d]?|submitted|remove|delete|cross off|the|my|deadline|"
                       r"for|i|have|has|is|it|please)\b", "", t).strip()
            return "complete_deadline", {"query": q}
        if has(r"\b(add|new|set|create|put|got|have)\b") and not has(r"\b(what|show|list|any)\b"):
            title, when = split_title_when(orig, allow_by=True)
            return "add_deadline", {"task": title, "due": when if parse_when(when) else None}
        return "list_deadlines", {}
    # name + memory
    m = re.match(r"(?:call me|address me as|my name is|i am called|i'm called)\s+([a-z][a-z' -]{0,29})$",
                 orig.strip(" .!?"), re.I)
    if m and len(m.group(1).split()) <= 3 and m.group(1).lower() not in (
            "back", "later", "tomorrow", "when you can", "maybe", "now", "if you can"):
        return "set_name", {"name": m.group(1).title()}
    m = re.match(r"(?:remember|keep in mind|don't forget|dont forget|note)\s+(?:that\s+)?(.+)", orig, re.I)
    if m:
        return "remember", {"fact": m.group(1)}
    if has(r"what do you (?:remember|know) about me|what have you saved"):
        return "recall", {}
    m = re.match(r"forget\s+(?:that\s+|about\s+)?(.+)", orig, re.I)
    if m:
        return "forget", {"query": m.group(1)}
    # fun
    if has(r"\b(joke|make me laugh|something funny|roast me)\b"):
        return "joke", {"kind": "dark" if "dark" in t else "roast" if "roast" in t else ""}
    # screen / camera / clipboard
    if not has(r"\bfull ?screen\b"):
        src = ("camera" if has(r"\b(camera|webcam|look at me|in front of you|what do you see|can you see me|"
                               r"what am i holding|identify this|what(?:'s| is) this (?:object|thing|plant|animal|item))\b")
               else "clipboard" if has(r"\b(clipboard|copied (?:image|picture|photo))\b")
               else "screen" if has(r"\b(screen|looking at|desktop|monitor)\b") else None)
        if src:
            if has(r"\b(read|text|ocr|transcribe|says|written|words)\b"):
                return "read_text", {"source": src}
            return "look", {"source": src, "question": orig}
    # read a link
    um = re.search(r"(https?://\S+|\b(?:www\.)?[\w-]+\.(?:com|org|net|io|co|id|dev|ai|edu|gov|news)\b(?:/\S*)?)", orig)
    if um and has(r"\b(read|summari[sz]e|tl;?dr|what does|what(?:'s| is) on|explain)\b"):
        return "read_page", {"url": um.group(1).rstrip(".,)")}
    if has(r"\b(battery|cpu|ram usage|memory usage|disk space|system (?:status|stats)|how'?s my (?:pc|laptop|computer))\b"):
        return "system_status", {}
    if has(r"\b(volume|mute|unmute|louder|quieter|turn it (?:up|down))\b"):
        m = re.search(r"\b(\d{1,3})\b", t)
        if m:
            return "set_volume", {"action": m.group(1)}
        if has(r"\bmute\b"):
            return "set_volume", {"action": "mute"}
        return "set_volume", {"action": "up" if has(r"\b(up|louder|raise|increase|higher)\b") else "down"}
    # converter
    m = re.match(r"(?:convert|change|how (?:much|many) is|what(?:'s| is))?\s*(-?\d[\d,]*\.?\d*)\s*(?:degrees?\s+)?"
                 r"([a-z]+)\s+(?:to|in|into|equals?|as)\s+([a-z]+)$", t)
    if m and _convertible(m.group(2), m.group(3)):
        return "convert", {"amount": m.group(1), "from_unit": m.group(2), "to_unit": m.group(3)}
    # search a specific site
    site = q = None
    m = re.match(rf"(?:search|find|look(?: for| up)?|show me)\s+(.+?)\s+(?:on|in|at)\s+({SITE_RE})$", t)
    if m:
        q, site = m.group(1), SITE_ALIAS[m.group(2)]
    else:
        m = re.match(rf"(?:search|find|look up|check)\s+({SITE_RE})\s+for\s+(.+)$", t)
        if m:
            site, q = SITE_ALIAS[m.group(1)], m.group(2)
    if site:
        return ("wikipedia", {"topic": q}) if site == "wikipedia" else ("site_search", {"site": site, "query": q})
    # youtube / open
    if has(r"\byoutube\b") or has(r"^play\b"):
        m = re.search(r"(?:play|search(?: for)?|find|put on|watch)\s+(.+?)(?:\s+on youtube|\s+in chrome|$)", t)
        q = m.group(1) if m else ""
        q = re.sub(r"^(?:youtube|some|me)\s+", "", q)
        return "youtube", {"query": "" if q in ("youtube", "") else q}
    m = re.match(r"(?:open|launch|start|run|go to|take me to)\s+(.+)", t)
    if m:
        return "open_app", {"name": m.group(1)}
    # info
    if has(r"\bwhat time is it\b|\bwhat(?:'s| is) the (?:time|date|day)\b|\bwhat day is (?:it|today)\b|\bcurrent (?:time|date)\b"):
        return "get_time", {}
    if has(r"\b(weather|forecast|temperature|raining|how (?:hot|cold|warm) is it|humid)\b"):
        m = re.search(r"\bin ([a-z][a-z .,'-]+?)(?:\s+(?:today|tomorrow|tonight|now|right now|this week))?$", t)
        place = m.group(1).strip() if m else None
        return "weather", {"place": place if place and place not in ("my area", "here") else None}
    if has(r"\b(news|headlines)\b"):
        m = re.search(r"\b(?:news|headlines)\s+(?:about|on|regarding)\s+(.+)$", t)
        if m:
            return "news", {"topic": m.group(1)}
        src = next((s for pat, s in NEWS_ALIAS if has(pat)), None)
        return "news", {"source": src}
    m = re.match(r"(?:calculate|compute|what(?:'s| is)|how much is|solve)\s+([-\d\s+*/().^%x\u00d7\u00f7]+)$", t)
    if m and re.search(r"\d", m.group(1)) and re.search(r"[-+*/^%x\u00d7\u00f7]", m.group(1)):
        return "calculator", {"expression": m.group(1)}
    # dictionary
    m = (re.match(r"(?:define|definition of|meaning of|what(?:'s| is) the (?:meaning|definition) of)\s+([a-z'-]+)$", t)
         or re.match(r"what does ([a-z'-]+) mean$", t))
    if m:
        return "define", {"word": m.group(1)}
    # research / web
    m = re.match(r"(?:research|investigate|dig (?:in)?to|find out (?:more )?about|deep dive (?:on|into)|"
                 r"do some research (?:on|about))\s+(.+)", t)
    if m:
        return "research", {"query": m.group(1)}
    m = re.match(r"(?:search (?:the )?(?:web|internet|online)(?: for)?|google|look online for)\s+(.+)", t)
    if m:
        return "web_search", {"query": m.group(1)}
    m = re.match(r"(who is|who was|who are|what is|what are|what was|tell me about|explain|define|wikipedia|look up|lookup)\s+(.+)", t)
    if m:
        topic = m.group(2)
        casual = topic.startswith(("you", "your", "my", "the time", "going", "up", "wrong", "happening", "it", "that", "this"))
        if not casual and (m.group(1) in ("who is", "who was", "tell me about", "wikipedia", "look up", "lookup")
                           or len(topic.split()) <= 5):
            return "wikipedia", {"topic": topic}
    return None


class Brain:
    def __init__(self):
        self.history = []
        self.cancel = threading.Event()

    def system_prompt(self):
        facts = load("memory", {"facts": []})["facts"][-15:]
        now = dt.datetime.now().strftime("%A %d %B %Y, %H:%M")
        # short prompt = faster replies: full help text only for tools the model must call itself
        tools = "\n".join(f"- {v['usage']}" if not v["direct"] else f"- {v['usage'].split(' - ')[0]}"
                          for v in TOOLS.values())
        return (PERSONA.format(call=call_me())
                + "\n\nTOOLS: when you need live data or an action, reply with ONLY a tool tag and nothing else, e.g. "
                  '<tool>{"name": "tool_name", "args": {"arg": "value"}}</tool>'
                  ". You then receive the result and answer in your own voice. Never invent tool results. "
                  "For ordinary conversation, don't use tools.\n"
                  "RULES: for facts that could be new or real-world (news, prices, sports, who holds a job) use "
                  "research or web_search instead of guessing. For the screen, camera or a picture use look. "
                  "To read a link use read_page. After a tool result, answer in 1-2 sentences with the key facts. "
                  "If a tool fails, say so honestly. Reply in the language the user writes in.\n" + tools
                + f"\n\nCurrent time: {now}. Home: {HOME['name']}."
                + (("\nAbout the user: " + "; ".join(facts)) if facts else ""))

    def _gen(self, msgs, temp, on_stream):
        def cb(full):
            s = full.lstrip()
            if on_stream and len(s) >= 7 and not s.startswith(("<tool", "<think")):
                on_stream(clean(full))
        return ollama_chat(msgs, temp, cb, self.cancel)

    def respond(self, text, on_stream=None):
        self.cancel.clear()
        routed = route(text)
        if not routed and WEB_AUTO and needs_web(text):
            routed = ("research", {"query": text})
        if not routed and _AUTO_FACT.match(text.strip()):
            _autofact(text)
        result, final = None, None
        user_content, note = text, ""
        if routed:
            name, args = routed
            result = run_tool(name, args)
            if TOOLS[name]["direct"]:
                final = result
                if name in QUIP_TOOLS and random.random() < 0.3:
                    final = random.choice(QUIPS) + " " + result
            else:
                note = f"\n[{name} data: {result[:300]}]"
                user_content = (f"{text}\n\n[Live data from your {name} tool. Answer me politely and briefly, "
                                f"using only this data. No URLs, no lists:]\n{result[:TOOL_CAP]}")
        if final is None:
            msgs = ([{"role": "system", "content": self.system_prompt()}]
                    + self.history[-HISTORY_TURNS * 2:] + [{"role": "user", "content": user_content}])
            temp = BASE_TEMP
            if not routed and CHAOS_CHANCE > 0 and random.random() < CHAOS_CHANCE:
                temp = round(random.uniform(*CHAOS_RANGE), 2)
            try:
                for _ in range(4):
                    out = self._gen(msgs, temp, on_stream)
                    call = parse_tool_call(out)
                    if not call:
                        final = clean(out)
                        break
                    name, args = call
                    res = run_tool(name, args)
                    if TOOLS[name]["direct"]:
                        final = res
                        break
                    note = f"\n[{name} data: {res[:300]}]"
                    msgs += [{"role": "assistant", "content": out},
                             {"role": "user", "content": f"[Tool result from {name}]: {res[:TOOL_CAP]}\n"
                                                         "Now answer me politely and briefly."}]
                    temp = BASE_TEMP
                final = final or "I got lost in my own tool calls. Please ask me again."
            except requests.exceptions.ConnectionError:
                final = result or "My brain isn't answering. Is Ollama running?"
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    final = result or f"Ollama doesn't have a model called {MODEL}. Run: ollama create {MODEL} -f Modelfile"
                else:
                    final = result or f"Ollama error: {e}"
            except Exception as e:
                final = result or f"Something went wrong: {e}"
        if self.cancel.is_set():
            final = final or "Stopped."
        # tool data is kept in history so follow-ups ("and tomorrow?", "who is that?") still work
        self.history += [{"role": "user", "content": text + note}, {"role": "assistant", "content": final}]
        self.history = self.history[-HISTORY_TURNS * 2:]
        return final


# =====================================================================
# SCHEDULER (timers, alarms, events, deadline warnings)
# =====================================================================
class Scheduler(threading.Thread):
    def __init__(self, announce):
        super().__init__(daemon=True)
        self.announce = announce
        self._last_dl = 0

    def run(self):
        while True:
            time.sleep(1)
            try:
                self.check()
            except Exception as e:
                print("scheduler:", e)

    def check(self):
        now = dt.datetime.now()
        fired, warn = [], []
        with LOCK:
            s = load("schedule", {"items": []})
            keep = []
            for it in s["items"]:
                due = dt.datetime.fromisoformat(it["due"])
                if due <= now:
                    fired.append((it, (now - due).total_seconds()))
                    if it.get("repeat") == "daily":
                        while due <= now:
                            due += dt.timedelta(days=1)
                        it["due"] = due.isoformat(timespec="seconds")
                        keep.append(it)
                else:
                    keep.append(it)
            if fired:
                s["items"] = keep
                save("schedule", s)
            if time.time() - self._last_dl > 30:
                self._last_dl = time.time()
                dl = load("deadlines", {"items": []})
                changed = False
                for d in dl["items"]:
                    if d.get("due") and not d.get("warned") and \
                            dt.datetime.fromisoformat(d["due"]) - now <= dt.timedelta(hours=DEADLINE_WARN_HOURS):
                        d["warned"] = changed = True
                        warn.append(d)
                if changed:
                    save("deadlines", dl)
        who = call_me()
        who = who[:1].upper() + who[1:]
        for it, late in fired:
            lab = it["label"]
            if it["kind"] == "timer":
                msg = "Timer finished" + (f": {lab}." if lab != "timer" else ".")
            elif it["kind"] == "alarm":
                msg = f"{who}, your alarm is going off." + (f" {lab}." if lab != "alarm" else "")
            else:
                msg = f"Reminder: {lab}."
            if late > 90:
                msg += f" That was {human_secs(late)} ago."
            self.announce(msg)
        for d in warn:
            self.announce(f"Heads up: '{d['task']}' is due {fmt_dt(dt.datetime.fromisoformat(d['due']))}.")


# =====================================================================
# VOICE IN (wake word)
# =====================================================================
def find_wake(text):
    """Return the command text after the wake word, '' if only the wake word was said, None if no wake word."""
    norm = re.sub(r"[^a-z0-9' ]", " ", text.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    for name in NAMES:
        for m in re.finditer(rf"\b{name}\b", norm):
            before = norm[:m.start()].strip()
            if WAKE_ON_BARE_NAME or any(before.endswith(p) for p in WAKE_PREFIXES):
                return norm[m.end():].strip(" ,")
    return None


class Listener(threading.Thread):
    def __init__(self, on_command, speaker, status):
        super().__init__(daemon=True)
        self.on_command, self.speaker, self.status = on_command, speaker, status
        self.active = True

    def run(self):
        try:
            import speech_recognition as sr
        except ImportError:
            self.status("Voice input needs: pip install SpeechRecognition pyaudio")
            return
        r = sr.Recognizer()
        r.dynamic_energy_threshold = True
        r.pause_threshold = 0.7
        try:
            mic = sr.Microphone()
            with mic as src:
                r.adjust_for_ambient_noise(src, 1)
                while True:
                    if not self.active or self.speaker.busy:
                        time.sleep(0.2)
                        continue
                    try:
                        text = r.recognize_google(r.listen(src, timeout=2, phrase_time_limit=7))
                    except (sr.WaitTimeoutError, sr.UnknownValueError):
                        continue
                    except Exception:
                        time.sleep(1)
                        continue
                    cmd = find_wake(text)
                    if cmd is None:
                        continue
                    sfx("wake")
                    if not cmd:
                        self.status("listening")
                        try:
                            cmd = r.recognize_google(r.listen(src, timeout=6, phrase_time_limit=10))
                        except Exception:
                            self.status("idle")
                            continue
                    self.on_command(cmd)
        except Exception as e:
            self.status(f"Microphone problem: {e}")