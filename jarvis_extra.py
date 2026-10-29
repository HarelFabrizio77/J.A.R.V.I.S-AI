#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. Mark 3 -- EXTRA TOOLS.   Keep this file next to jarvis_core.py and jarvis_mk3.py.

It plugs itself into jarvis_core: every tool below is registered in the same TOOLS table the model
sees, and extra voice/text commands are added in front of the core keyword router.
Optional installs:  pip install psutil pillow pytesseract opencv-python pypdf tzdata
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import os
import random
import re
import secrets
import socket
import subprocess
import time
import urllib.parse as up
from pathlib import Path

import requests

import jarvis_core as core
from jarvis_core import DATA, LOCK, NOWIN, UA, tool, load, save, human_secs, fmt_dt, parse_when

SHOTS = DATA / "screens"
SHOTS.mkdir(exist_ok=True)


# =====================================================================
# helpers
# =====================================================================
def _ps(cmd, inp=None, timeout=12):
    full = ("[Console]::InputEncoding=[Text.Encoding]::UTF8; "
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + cmd)
    return subprocess.run(["powershell", "-NoProfile", "-Command", full], input=inp, capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout, creationflags=NOWIN)


def _clip_text():
    try:
        return _ps("Get-Clipboard -Raw").stdout.strip()
    except Exception:
        return ""


def _set_clip(text):
    try:
        _ps("Set-Clipboard -Value ([Console]::In.ReadToEnd())", inp=str(text))
        return True
    except Exception:
        return False


def _combo(*vks):
    import ctypes
    u = ctypes.windll.user32
    for v in vks:
        u.keybd_event(v, 0, 0, 0)
    for v in reversed(vks):
        u.keybd_event(v, 0, 2, 0)


def _idr(v):
    return f"{v:,.0f} rupiah"


def _amount(s):
    t = str(s).lower().replace("rp", "").replace(",", "").strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", t):          # Indonesian style 50.000
        t = t.replace(".", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(k|rb|ribu|thousand|jt|juta|m|million|b|billion)?\b", t)
    if not m:
        return None
    mult = {"k": 1e3, "rb": 1e3, "ribu": 1e3, "thousand": 1e3, "jt": 1e6, "juta": 1e6, "m": 1e6,
            "million": 1e6, "b": 1e9, "billion": 1e9}.get(m.group(2) or "", 1)
    return float(m.group(1)) * mult


# =====================================================================
# SCREEN / CAMERA / IMAGE
# =====================================================================
@tool("screenshot", "screenshot() - save a screenshot to jarvis_data/screens", direct=True)
def t_screenshot():
    try:
        from PIL import ImageGrab
    except ImportError:
        return "Screenshots need: pip install pillow"
    p = SHOTS / f"screen_{dt.datetime.now():%Y%m%d_%H%M%S}.png"
    ImageGrab.grab().save(p)
    return f"Screenshot saved as {p.name}."


@tool("photo", "photo() - take a photo with the webcam and save it", direct=True)
def t_photo():
    try:
        img = core._get_image("camera")
    except ImportError:
        return "The camera needs: pip install opencv-python pillow"
    except Exception as e:
        return f"Camera failed: {e}."
    p = SHOTS / f"photo_{dt.datetime.now():%Y%m%d_%H%M%S}.jpg"
    img.save(p)
    return f"Photo saved as {p.name}."


@tool("copy_text", "copy_text(source?) - read the text in an image or on the screen (OCR) and copy it to the clipboard",
      direct=True)
def t_copy_text(source="screen"):
    try:
        img = core._get_image(source)
    except Exception as e:
        return f"I couldn't get the image: {e}."
    txt = core._ocr(img)
    if not txt:
        return "I couldn't find readable text there."
    return f"Copied {len(txt)} characters to the clipboard." if _set_clip(txt) else "I couldn't reach the clipboard."


@tool("compare_images", "compare_images(source_a, source_b, question?) - compare two images: file paths, 'screen', "
                        "'clipboard' or 'camera'")
def t_compare_images(source_a, source_b, question=""):
    try:
        a, b = core._get_image(source_a), core._get_image(source_b)
    except ImportError:
        return "Image recognition needs: pip install pillow (and opencv-python for the camera)."
    except Exception as e:
        return f"I couldn't get the images: {e}."
    model = core._pick_vision()
    if not model:
        return "No vision model installed. Run: ollama pull qwen2.5vl:3b"
    q = (question or "").strip() or "Compare these two images. What is the same and what is different?"
    msg = {"role": "user", "content": q, "images": [core._b64(a, 768), core._b64(b, 768)]}

    def call(think):
        p = {"model": model, "stream": False, "keep_alive": core.VISION_KEEP, "messages": [msg],
             "options": {"temperature": 0.2, "num_predict": 320}}
        if think is not None:
            p["think"] = think
        return requests.post(f"{core.OLLAMA}/api/chat", json=p, timeout=300)
    try:
        r = call(False)
        if r.status_code == 400:
            r = call(None)
        r.raise_for_status()
        return f"Image comparison ({model}): " + core.clean(r.json()["message"]["content"])
    except Exception as e:
        return f"Comparison failed ({type(e).__name__})."


# =====================================================================
# LANGUAGE
# =====================================================================
LANGS = {"indonesian": "id", "bahasa": "id", "english": "en", "spanish": "es", "french": "fr", "german": "de",
         "japanese": "ja", "chinese": "zh-CN", "mandarin": "zh-CN", "korean": "ko", "arabic": "ar",
         "hebrew": "he", "javanese": "jv", "dutch": "nl", "italian": "it", "portuguese": "pt",
         "russian": "ru", "turkish": "tr", "thai": "th", "vietnamese": "vi", "hindi": "hi", "malay": "ms"}


@tool("translate", "translate(text, to) - translate text into a language, e.g. text='good morning', to='indonesian'",
      direct=True)
def t_translate(text, to="english"):
    code = LANGS.get(str(to).lower().strip(), str(to).lower().strip()[:5])
    txt = str(text).strip()[:480]
    if not txt:
        return "What should I translate?"
    try:
        j = requests.get("https://api.mymemory.translated.net/get", headers=UA, timeout=10,
                         params={"q": txt, "langpair": f"Autodetect|{code}"}).json()
        return htmllib.unescape(j["responseData"]["translatedText"])
    except Exception as e:
        return f"Translation failed ({type(e).__name__})."


@tool("translate_screen", "translate_screen(source?, to?) - read the text on the screen/image (OCR) and translate it",
      direct=True)
def t_translate_screen(source="screen", to="english"):
    try:
        img = core._get_image(source)
    except Exception as e:
        return f"I couldn't get the image: {e}."
    txt = core._ocr(img)
    if not txt:
        return "I couldn't find readable text there."
    return t_translate(re.sub(r"\s+", " ", txt)[:450], to)


# =====================================================================
# TO-DO + NOTES + EXPENSES
# =====================================================================
@tool("todo_add", "todo_add(task) - add an item to the to-do list", direct=True)
def t_todo_add(task):
    with LOCK:
        s = load("todo", {"items": []})
        it = {"id": max([i["id"] for i in s["items"]], default=0) + 1, "text": str(task).strip(), "done": False}
        s["items"].append(it)
        save("todo", s)
    return f"Added to your to-do list: {it['text']}."


@tool("todo_list", "todo_list() - read the open to-do items", direct=True)
def t_todo_list():
    open_ = [i for i in load("todo", {"items": []})["items"] if not i["done"]]
    if not open_:
        return "Your to-do list is empty."
    return f"You have {len(open_)} open task{'s' if len(open_) != 1 else ''}: " + "; ".join(
        i["text"] for i in open_[:8]) + "."


def _todo_match(q):
    q = str(q).lower().strip()
    return [i for i in load("todo", {"items": []})["items"] if not i["done"]
            and ((q.isdigit() and int(q) == i["id"]) or (q and not q.isdigit() and q in i["text"].lower()))]


@tool("todo_done", "todo_done(query) - tick off a to-do item by id or part of its text", direct=True)
def t_todo_done(query):
    hits = _todo_match(query)
    if not hits:
        return "No open task matched that."
    with LOCK:
        s = load("todo", {"items": []})
        ids = {h["id"] for h in hits}
        for i in s["items"]:
            if i["id"] in ids:
                i["done"] = True
        save("todo", s)
    return "Ticked off: " + ", ".join(h["text"] for h in hits) + "."


@tool("todo_clear", "todo_clear() - delete all finished to-do items", direct=True)
def t_todo_clear():
    with LOCK:
        s = load("todo", {"items": []})
        n = sum(1 for i in s["items"] if i["done"])
        s["items"] = [i for i in s["items"] if not i["done"]]
        save("todo", s)
    return f"Cleared {n} finished task{'s' if n != 1 else ''}."


def todo_lines():
    open_ = [i for i in load("todo", {"items": []})["items"] if not i["done"]]
    if not open_:
        return "All clear."
    out = [f"[ ] {i['text'][:34]}" for i in open_[:7]]
    if len(open_) > 7:
        out.append(f"+{len(open_) - 7} more")
    return "\n".join(out)


@tool("note_add", "note_add(text) - save a quick note", direct=True)
def t_note_add(text):
    with LOCK:
        s = load("notes", {"items": []})
        s["items"].append({"t": dt.datetime.now().isoformat(timespec="seconds"), "text": str(text).strip()})
        save("notes", s)
    return "Noted."


@tool("note_list", "note_list(count?) - read your latest notes", direct=True)
def t_note_list(count=4):
    try:
        n = max(1, min(int(count), 10))
    except Exception:
        n = 4
    items = load("notes", {"items": []})["items"][-n:]
    return ("Your latest notes: " + "; ".join(i["text"] for i in items) + ".") if items else "You have no notes."


@tool("note_search", "note_search(query) - search your notes", direct=True)
def t_note_search(query):
    q = str(query).lower()
    hits = [i["text"] for i in load("notes", {"items": []})["items"] if q in i["text"].lower()]
    return ("Found: " + "; ".join(hits[-5:]) + ".") if hits else "Nothing in your notes about that."


def notes_lines():
    items = load("notes", {"items": []})["items"][-6:]
    if not items:
        return "No notes yet."
    return "\n".join(f"{i['t'][5:10]} {i['text'][:32]}" for i in reversed(items))


@tool("expense_add", "expense_add(amount, what) - log money spent in rupiah, e.g. amount='50k', what='lunch'",
      direct=True)
def t_expense_add(amount, what):
    v = _amount(amount)
    if not v:
        return "How much was it?"
    with LOCK:
        s = load("expenses", {"items": []})
        s["items"].append({"t": dt.datetime.now().isoformat(timespec="seconds"), "amt": v,
                           "what": str(what).lower().strip()[:40]})
        save("expenses", s)
    return f"Logged {_idr(v)} for {what}."


@tool("expense_summary", "expense_summary() - how much you spent today and this month", direct=True)
def t_expense_summary():
    now = dt.datetime.now()
    today = month = 0.0
    cats = {}
    for i in load("expenses", {"items": []})["items"]:
        d = dt.datetime.fromisoformat(i["t"])
        if (d.year, d.month) == (now.year, now.month):
            month += i["amt"]
            cats[i["what"]] = cats.get(i["what"], 0) + i["amt"]
            if d.date() == now.date():
                today += i["amt"]
    if not month:
        return "No spending logged this month."
    top = sorted(cats.items(), key=lambda kv: -kv[1])[:3]
    return (f"Today {_idr(today)}, this month {_idr(month)}. Biggest: "
            + ", ".join(f"{k} {_idr(v)}" for k, v in top) + ".")


# =====================================================================
# CLOCKS, DATES, FOCUS
# =====================================================================
_MONTHS = {}
for _i, _m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                         "september", "october", "november", "december"], 1):
    _MONTHS[_m] = _i
    _MONTHS[_m[:3]] = _i
_MONTHS["sept"] = 9


def _parse_date(text):
    t = str(text).lower()
    today = dt.date.today()
    try:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
        if m:
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3,9})\b(?:,?\s+(\d{4}))?", t)
        d = mo = y = None
        if m and m.group(2) in _MONTHS:
            d, mo, y = int(m.group(1)), _MONTHS[m.group(2)], m.group(3)
        else:
            m = re.search(r"\b([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?", t)
            if m and m.group(1) in _MONTHS:
                d, mo, y = int(m.group(2)), _MONTHS[m.group(1)], m.group(3)
        if d:
            date = dt.date(int(y) if y else today.year, mo, d)
            if not y and date < today:
                date = dt.date(today.year + 1, mo, d)
            return date
    except ValueError:
        return None
    w = parse_when(t)
    return w.date() if w else None


@tool("days_until", "days_until(date) - days left until a date, e.g. '17 August', 'december 25', 'friday'", direct=True)
def t_days_until(date):
    d = _parse_date(date)
    if not d:
        return "I couldn't read that date."
    n = (d - dt.date.today()).days
    if n == 0:
        return "That's today."
    if n == 1:
        return "That's tomorrow."
    if n < 0:
        return f"That was {-n} days ago."
    return f"{n} days to go" + (f", about {n // 7} weeks." if n > 14 else ".")


CITY_TZ = {"jakarta": "Asia/Jakarta", "bali": "Asia/Makassar", "tokyo": "Asia/Tokyo", "seoul": "Asia/Seoul",
           "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai", "hong kong": "Asia/Hong_Kong",
           "singapore": "Asia/Singapore", "kuala lumpur": "Asia/Kuala_Lumpur", "bangkok": "Asia/Bangkok",
           "delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata", "dubai": "Asia/Dubai", "riyadh": "Asia/Riyadh",
           "istanbul": "Europe/Istanbul", "moscow": "Europe/Moscow", "cairo": "Africa/Cairo",
           "london": "Europe/London", "paris": "Europe/Paris", "berlin": "Europe/Berlin",
           "amsterdam": "Europe/Amsterdam", "madrid": "Europe/Madrid", "rome": "Europe/Rome",
           "new york": "America/New_York", "chicago": "America/Chicago", "los angeles": "America/Los_Angeles",
           "san francisco": "America/Los_Angeles", "toronto": "America/Toronto", "sydney": "Australia/Sydney",
           "melbourne": "Australia/Melbourne", "auckland": "Pacific/Auckland"}


@tool("world_time", "world_time(city) - current time in another city, e.g. 'tokyo', 'new york', 'london'",
      direct=True)
def t_world_time(city):
    key = str(city).lower().strip()
    tz = CITY_TZ.get(key)
    if not tz:
        return f"I don't have a timezone for {city}."
    try:
        from zoneinfo import ZoneInfo
        there = dt.datetime.now(ZoneInfo(tz))
        here = dt.datetime.now(ZoneInfo(core.HOME["tz"]))
    except Exception:
        return "Timezone data is missing. Run: pip install tzdata"
    diff = (there.utcoffset() - here.utcoffset()).total_seconds() / 3600
    rel = "the same time as you" if diff == 0 else f"{abs(diff):g} hours {'ahead of' if diff > 0 else 'behind'} you"
    return f"In {key.title()} it's {there:%A %H:%M}, {rel}."


@tool("sun", "sun() - today's sunrise and sunset at home", direct=True)
def t_sun():
    try:
        h = core.HOME
        j = requests.get("https://api.open-meteo.com/v1/forecast", headers=UA, timeout=10, params={
            "latitude": h["lat"], "longitude": h["lon"], "timezone": h["tz"], "forecast_days": 1,
            "daily": "sunrise,sunset"}).json()
        return f"Sunrise {j['daily']['sunrise'][0][-5:]}, sunset {j['daily']['sunset'][0][-5:]}."
    except Exception as e:
        return f"Sun times unavailable ({type(e).__name__})."


@tool("pomodoro", "pomodoro(work_minutes?, break_minutes?) - focus session: a work timer then a break timer",
      direct=True)
def t_pomodoro(work_minutes=25, break_minutes=5):
    try:
        w, b = int(float(work_minutes)), int(float(break_minutes))
    except Exception:
        w, b = 25, 5
    now = dt.datetime.now()
    core._add_item("timer", "focus block finished, take a break", now + dt.timedelta(minutes=w))
    core._add_item("timer", "break is over, back to work", now + dt.timedelta(minutes=w + b))
    return f"Focus mode: {w} minutes of work, then a {b} minute break."


# =====================================================================
# MACROS (routines)
# =====================================================================
@tool("macro_add", "macro_add(name, steps) - save a routine; steps = comma-separated apps/sites, e.g. name='study', "
                   "steps='vscode, github, youtube lofi, timer 25 minutes, volume 30'", direct=True)
def t_macro_add(name, steps):
    n = str(name).lower().strip()
    st = [s.strip() for s in re.split(r"[,;]|\s+and then\s+|\s+then\s+|\s+and\s+", str(steps)) if s.strip()]
    if not n or not st:
        return "I need a name and at least one step."
    with LOCK:
        m = load("macros", {})
        m[n] = st
        save("macros", m)
    return f"Routine '{n}' saved with {len(st)} step{'s' if len(st) != 1 else ''}."


@tool("macro_list", "macro_list() - list saved routines", direct=True)
def t_macro_list():
    m = load("macros", {})
    return ("Routines: " + ", ".join(m) + ".") if m else "You have no routines yet."


@tool("macro_run", "macro_run(name) - run a saved routine", direct=True)
def t_macro_run(name):
    n = str(name).lower().strip()
    steps = load("macros", {}).get(n)
    if not steps:
        return f"I don't have a routine called {n}."
    for s in steps:
        low = s.lower()
        try:
            if low.startswith("timer "):
                core.t_timer(low[6:])
            elif low.startswith("volume "):
                core.t_volume(low[7:])
            elif low.startswith("youtube "):
                core.t_youtube(s[8:])
            else:
                core.t_open(s)
        except Exception:
            pass
        time.sleep(0.8)
    return f"Routine {n} is running."


# =====================================================================
# RANDOM / FUN
# =====================================================================
@tool("roll_dice", "roll_dice(sides?, count?) - roll dice", direct=True)
def t_dice(sides=6, count=1):
    try:
        sides, count = max(2, min(1000, int(sides))), max(1, min(20, int(count)))
    except Exception:
        sides, count = 6, 1
    r = [random.randint(1, sides) for _ in range(count)]
    return f"Rolled {r[0]}." if count == 1 else f"Rolled {', '.join(map(str, r))}, total {sum(r)}."


@tool("flip_coin", "flip_coin() - flip a coin", direct=True)
def t_coin():
    return random.choice(["Heads.", "Tails."])


@tool("choose", "choose(options) - pick one of several options, e.g. 'pizza or sushi or burgers'", direct=True)
def t_choose(options):
    opts = [o.strip() for o in re.split(r",|\bor\b", str(options)) if o.strip()]
    return f"I'd go with {random.choice(opts)}." if opts else "Give me some options."


@tool("password", "password(length?) - generate a strong password and copy it to the clipboard", direct=True)
def t_password(length=16):
    try:
        n = max(8, min(64, int(length)))
    except Exception:
        n = 16
    pw = "".join(secrets.choice("abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%&*?") for _ in range(n))
    return (f"Generated a {n} character password and copied it to your clipboard."
            if _set_clip(pw) else "I couldn't reach the clipboard.")


@tool("fun_fact", "fun_fact() - a random fun fact", direct=True)
def t_fact():
    try:
        j = requests.get("https://uselessfacts.jsph.pl/api/v2/facts/random?language=en", headers=UA, timeout=8).json()
        return j["text"]
    except Exception:
        return "Honey never spoils; jars found in ancient tombs were still edible."


# =====================================================================
# MONEY
# =====================================================================
COINS = {"btc": "bitcoin", "eth": "ethereum", "sol": "solana", "doge": "dogecoin", "bnb": "binancecoin",
         "xrp": "ripple", "ada": "cardano", "ltc": "litecoin", "usdt": "tether"}


@tool("crypto", "crypto(coin) - live price of a coin (bitcoin, ethereum, solana, doge...) in dollars and rupiah",
      direct=True)
def t_crypto(coin="bitcoin"):
    c = str(coin).lower().strip()
    cid = COINS.get(c, c)
    try:
        j = requests.get("https://api.coingecko.com/api/v3/simple/price", headers=UA, timeout=10, params={
            "ids": cid, "vs_currencies": "usd,idr", "include_24hr_change": "true"}).json()
        d = j.get(cid)
        if not d:
            return f"I couldn't find a coin called {coin}."
        ch = d.get("usd_24h_change")
        return (f"{cid.title()}: {d['usd']:,.2f} dollars, about {d['idr']:,.0f} rupiah"
                + (f", {ch:+.1f} percent in 24 hours." if ch is not None else "."))
    except Exception as e:
        return f"Crypto lookup failed ({type(e).__name__})."


def market_snapshot():
    out = []
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", headers=UA, timeout=8).json()["rates"]
        out += [f"USD/IDR  {r['IDR']:,.0f}", f"EUR/IDR  {r['IDR'] / r['EUR']:,.0f}",
                f"SGD/IDR  {r['IDR'] / r['SGD']:,.0f}"]
    except Exception:
        out.append("FX unavailable")
    try:
        j = requests.get("https://api.coingecko.com/api/v3/simple/price", headers=UA, timeout=8, params={
            "ids": "bitcoin,ethereum", "vs_currencies": "usd", "include_24hr_change": "true"}).json()
        for k, n in (("bitcoin", "BTC"), ("ethereum", "ETH")):
            out.append(f"{n}  ${j[k]['usd']:,.0f} ({j[k]['usd_24h_change']:+.1f}%)")
    except Exception:
        out.append("Crypto unavailable")
    return "\n".join(out)


# =====================================================================
# COMMUNICATION / WEB
# =====================================================================
@tool("compose_email", "compose_email(to, subject, body) - open a Gmail draft in Chrome", direct=True)
def t_email(to="", subject="", body=""):
    url = ("https://mail.google.com/mail/?view=cm&fs=1&to=" + up.quote(str(to).strip())
           + "&su=" + up.quote(str(subject).strip()) + "&body=" + up.quote(str(body).strip()))
    core.open_url(url)
    return "Draft opened. Review it and press send."


@tool("whatsapp", "whatsapp(number, text) - open WhatsApp with a message ready to send (Indonesian 08.. numbers ok)",
      direct=True)
def t_whatsapp(number, text=""):
    n = re.sub(r"\D", "", str(number))
    if n.startswith("0"):
        n = "62" + n[1:]
    if not n:
        return "Which number?"
    core.open_url(f"https://wa.me/{n}?text=" + up.quote(str(text).strip()))
    return "WhatsApp is open with your message ready. Press send."


@tool("directions", "directions(destination) - open Google Maps directions to a place", direct=True)
def t_directions(destination, mode="driving"):
    core.open_url("https://www.google.com/maps/dir/?api=1&travelmode=" + up.quote(str(mode))
                  + "&destination=" + up.quote_plus(str(destination)))
    return f"Directions to {destination} are on screen."


# =====================================================================
# PC CONTROL
# =====================================================================
@tool("media", "media(action) - play_pause, next, previous or stop the current music/video", direct=True)
def t_media(action="play_pause"):
    if os.name != "nt":
        return "Media keys only work on Windows."
    vk = {"play_pause": 0xB3, "play": 0xB3, "pause": 0xB3, "next": 0xB0, "previous": 0xB1, "prev": 0xB1,
          "stop": 0xB2}.get(str(action).lower().strip())
    if not vk:
        return "Use play_pause, next, previous or stop."
    core._key(vk)
    return "Done."


@tool("window_control", "window_control(action) - desktop, switch, snip, maximize, minimize, next_desktop, "
                        "prev_desktop, task_view", direct=True)
def t_window(action):
    if os.name != "nt":
        return "Window control only works on Windows."
    combos = {"desktop": (0x5B, 0x44), "switch": (0x12, 0x09), "snip": (0x5B, 0x10, 0x53),
              "maximize": (0x5B, 0x26), "minimize": (0x5B, 0x28), "next_desktop": (0x11, 0x5B, 0x27),
              "prev_desktop": (0x11, 0x5B, 0x25), "task_view": (0x5B, 0x09)}
    c = combos.get(str(action).lower().strip())
    if not c:
        return "I don't know that window action."
    _combo(*c)
    return "Done."


@tool("type_text", "type_text(text) - type text into the active window after a 3 second pause", direct=True)
def t_type(text):
    if os.name != "nt":
        return "Typing only works on Windows."
    if not _set_clip(text):
        return "I couldn't reach the clipboard."
    time.sleep(3)
    _combo(0x11, 0x56)
    return "Typed."


@tool("power", "power(action) - lock, sleep, shutdown (60s delay), restart (60s delay) or cancel", direct=True)
def t_power(action):
    if os.name != "nt":
        return "Power control only works on Windows."
    a = str(action).lower().strip()
    if a == "lock":
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return "Locked."
    if a == "sleep":
        subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True, creationflags=NOWIN)
        return "Going to sleep."
    if a in ("shutdown", "shut down", "off"):
        subprocess.Popen(["shutdown", "/s", "/t", "60"], creationflags=NOWIN)
        return "Shutting down in 60 seconds. Say cancel shutdown to stop it."
    if a in ("restart", "reboot"):
        subprocess.Popen(["shutdown", "/r", "/t", "60"], creationflags=NOWIN)
        return "Restarting in 60 seconds. Say cancel restart to stop it."
    if a in ("cancel", "abort"):
        subprocess.Popen(["shutdown", "/a"], creationflags=NOWIN)
        return "Cancelled."
    return "Use lock, sleep, shutdown, restart or cancel."


CLOSABLE = {"chrome": "chrome.exe", "google chrome": "chrome.exe", "notepad": "notepad.exe",
            "spotify": "Spotify.exe", "discord": "Discord.exe", "edge": "msedge.exe", "vscode": "Code.exe",
            "vs code": "Code.exe", "word": "WINWORD.EXE", "excel": "EXCEL.EXE", "paint": "mspaint.exe",
            "calculator": "CalculatorApp.exe", "task manager": "Taskmgr.exe", "telegram": "Telegram.exe",
            "whatsapp": "WhatsApp.exe", "steam": "steam.exe", "vlc": "vlc.exe", "obs": "obs64.exe"}


@tool("close_app", "close_app(name) - close a known app: chrome, notepad, spotify, discord, edge, vscode, word, "
                   "excel, paint, calculator, telegram, whatsapp, steam, vlc, obs", direct=True)
def t_close(name):
    n = str(name).lower().strip()
    exe = CLOSABLE.get(n)
    if not exe or os.name != "nt":
        return f"'{n}' isn't on my list of apps I can close."
    p = subprocess.run(["taskkill", "/IM", exe, "/F"], capture_output=True, text=True, creationflags=NOWIN)
    return f"Closed {n}." if p.returncode == 0 else f"{n} doesn't seem to be running."


def _top_data(n=3):
    import psutil
    procs = []
    for p in psutil.process_iter(["name"]):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except Exception:
            pass
    time.sleep(0.4)
    agg = {}
    for p in procs:
        try:
            a = agg.setdefault(p.info["name"] or "?", [0.0, 0.0])
            a[0] += p.cpu_percent(None)
            a[1] += p.memory_percent()
        except Exception:
            pass
    ncpu = psutil.cpu_count() or 1
    cpu = sorted(((k, v[0] / ncpu) for k, v in agg.items()), key=lambda kv: -kv[1])[:n]
    ram = sorted(((k, v[1]) for k, v in agg.items()), key=lambda kv: -kv[1])[:n]
    return cpu, ram


@tool("top_processes", "top_processes() - which programs are using the most CPU and memory", direct=True)
def t_top():
    try:
        cpu, ram = _top_data()
    except ImportError:
        return "Install psutil: pip install psutil"
    return ("Top CPU: " + ", ".join(f"{k} {v:.0f}%" for k, v in cpu) + ". Top memory: "
            + ", ".join(f"{k} {v:.0f}%" for k, v in ram) + ".")


def top_lines(n=4):
    try:
        cpu, ram = _top_data(n)
    except Exception:
        return "pip install psutil"
    return "\n".join(["CPU"] + [f" {k[:24]:<24}{v:5.1f}%" for k, v in cpu]
                     + ["RAM"] + [f" {k[:24]:<24}{v:5.1f}%" for k, v in ram])


def ping_ms(host="1.1.1.1", port=443):
    t0 = time.time()
    try:
        socket.create_connection((host, port), timeout=1.5).close()
        return int((time.time() - t0) * 1000)
    except Exception:
        return None


_PUB = {"ip": None, "t": 0.0}


def _local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def net_lines():
    try:
        local = _local_ip()
    except Exception:
        return "OFFLINE"
    if time.time() - _PUB["t"] > 600:
        _PUB["t"] = time.time()
        try:
            _PUB["ip"] = requests.get("https://api.ipify.org", timeout=3).text.strip()
        except Exception:
            pass
    p = ping_ms()
    return f"LOCAL  {local}\nPUBLIC {_PUB['ip'] or 'n/a'}\nPING   {str(p) + ' ms' if p is not None else 'no internet'}"


@tool("network_status", "network_status() - internet connection check: ping, local and public IP", direct=True)
def t_network():
    try:
        local = _local_ip()
    except Exception:
        return "You appear to be offline."
    p = ping_ms()
    if p is None:
        return f"Your network is up ({local}) but the internet isn't reachable."
    return f"Online. Ping {p} milliseconds, local address {local}."


def _find(name, limit=5, seconds=5):
    q = str(name).lower().strip().strip("\"'")
    home = Path.home()
    roots = [home / d for d in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music")]
    hits, end = [], time.time() + seconds
    for root in roots:
        if not root.exists():
            continue
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if not d.startswith(".") and d.lower() not in ("node_modules", "__pycache__",
                                                                                    "site-packages")]
            for f in fn:
                if q in f.lower():
                    hits.append(os.path.join(dp, f))
            if len(hits) >= limit or time.time() > end:
                return hits[:limit]
    return hits[:limit]


@tool("find_file", "find_file(name) - search Desktop, Documents, Downloads, Pictures for a file by name", direct=True)
def t_find_file(name):
    hits = _find(name)
    if not hits:
        return f"I couldn't find anything called {name}."
    return f"Found {len(hits)}: " + "; ".join(os.path.basename(h) + " in " + os.path.basename(os.path.dirname(h))
                                              for h in hits) + "."


@tool("open_file", "open_file(name) - open a file by name or full path", direct=True)
def t_open_file(name):
    p = Path(os.path.expandvars(str(name).strip().strip("\"'")))
    if not p.exists():
        hits = _find(name, 1)
        if not hits:
            return f"I couldn't find {name}."
        p = Path(hits[0])
    try:
        os.startfile(str(p))
        return f"Opening {p.name}."
    except Exception as e:
        return f"I couldn't open it ({type(e).__name__})."


@tool("read_file", "read_file(path) - read a text, code, PDF or Word file (by name or path) so you can summarise it")
def t_read_file(path):
    p = Path(os.path.expandvars(str(path).strip().strip("\"'")))
    if not p.exists():
        hits = _find(path, 1)
        if not hits:
            return "I can't find that file."
        p = Path(hits[0])
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            text = " ".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages[:5])
        elif ext == ".docx":
            import zipfile
            with zipfile.ZipFile(p) as z:
                xml = z.read("word/document.xml").decode("utf-8", "ignore")
            text = htmllib.unescape(re.sub(r"<[^>]+>", " ", xml.replace("</w:p>", "\n")))
        else:
            text = p.read_text("utf-8", errors="ignore")
    except ImportError:
        return "PDF reading needs: pip install pypdf"
    except Exception as e:
        return f"I couldn't read that file ({type(e).__name__})."
    text = re.sub(r"\s+", " ", text).strip()
    return f"File {p.name}: " + text[:core.TOOL_CAP] if text else "That file has no readable text."


@tool("clipboard_read", "clipboard_read() - read the text currently on the clipboard so you can summarise it")
def t_clip_read():
    t = _clip_text()
    return ("Clipboard text: " + t[:core.TOOL_CAP]) if t else "The clipboard has no text."


@tool("clipboard_set", "clipboard_set(text) - put text on the clipboard", direct=True)
def t_clip_set(text):
    return "Copied." if _set_clip(text) else "I couldn't reach the clipboard."


@tool("capabilities", "capabilities() - what Jarvis can do", direct=True)
def t_caps():
    return ("I handle weather, news, timers, alarms, deadlines, to-dos, notes, expenses, translation, web research, "
            "files, screen and camera vision, text recognition, music and window control, routines, and more. "
            "Just ask.")


# =====================================================================
# ROUTER  (runs BEFORE the core router; return None to fall through)
# =====================================================================
_PREFIX = re.compile(r"^(?:(?:hey|yo|ok|okay|please|jarvis|can you|could you|would you|i want you to|"
                     r"go ahead and)[, ]+)+", re.I)
_LR = "|".join(sorted(LANGS, key=len, reverse=True))


def extra_route(text):
    o = _PREFIX.sub("", text.strip()).rstrip("?!. ")
    t = o.lower()

    def has(p):
        return re.search(p, t) is not None

    def rm(p):
        return re.match(p, o, re.I)

    # --- screen / camera / images
    if has(r"\b(take|grab|capture|save)\b.*\b(screenshot|screen ?shot|screen capture)\b") or t in ("screenshot",):
        return "screenshot", {}
    if has(r"\b(take|snap)\b.*\b(photo|picture|selfie)\b") and not has(r"\bscreen"):
        return "photo", {}
    if has(r"\bcopy\b.*\b(text|words)\b.*\b(screen|image|picture|photo|camera)\b"):
        return "copy_text", {"source": "camera" if "camera" in t else "screen"}
    paths = re.findall(r"[a-zA-Z]:\\[^\"'<>|?*\n]+?\.(?:png|jpe?g|webp|bmp|gif)", o)
    if has(r"\bcompare\b"):
        if len(paths) >= 2:
            return "compare_images", {"source_a": paths[0], "source_b": paths[1], "question": ""}
        if has(r"\bscreen\b") and has(r"\bclipboard\b"):
            return "compare_images", {"source_a": "screen", "source_b": "clipboard", "question": ""}
    # --- translate
    if has(r"\btranslate\b") and has(r"\b(screen|window|page)\b"):
        m = re.search(rf"\b(?:to|into|in)\s+({_LR})\b", t)
        return "translate_screen", {"source": "screen", "to": m.group(1) if m else "english"}
    m = (rm(rf"translate\s+(.+?)\s+(?:into|to)\s+({_LR})$") or rm(rf"how (?:do|would) (?:you|i) say\s+(.+?)\s+in\s+({_LR})$")
         or rm(rf"(?:what(?:'s| is)|say)\s+(.+?)\s+in\s+({_LR})$"))
    if m:
        txt = m.group(1).strip("\"' ")
        if txt.lower() in ("this", "it", "that", "clipboard", "my clipboard", "what i copied"):
            txt = _clip_text() or txt
        return "translate", {"text": txt, "to": m.group(2).lower()}
    # --- to-do / notes / expenses
    m = (rm(r"(?:add|put)\s+(.+?)\s+(?:to|on|in)\s+(?:my\s+|the\s+)?(?:to-?do|task)s?(?:\s+list)?$")
         or rm(r"(?:new task|add task|add a task|todo|to-do)[: ]+(.+)$"))
    if m:
        return "todo_add", {"task": m.group(1)}
    m = (rm(r"(?:mark|tick|check|cross)\s+(?:off\s+)?(?:task\s+)?(.+?)\s+(?:as\s+)?(?:done|complete[d]?|finished)$")
         or rm(r"(?:finish|complete)\s+task\s+(.+)$"))
    if m and not has("deadline") and _todo_match(m.group(1)):
        return "todo_done", {"query": m.group(1)}
    if has(r"\b(clear|clean)\b.*\b(done|completed|finished)\b.*\btasks?\b"):
        return "todo_clear", {}
    if has(r"\b(to-?do|tasks?)\b") and has(r"\b(what|show|list|read|my|any|how many)\b") \
            and not has(r"\b(deadline|add|done|finish|complete)"):
        return "todo_list", {}
    m = (rm(r"(?:take|make|add|write)\s+a\s+note[: ,]*(?:that\s+)?(.+)$")
         or rm(r"(?:note down|write down|jot down)[: ,]*(?:that\s+)?(.+)$"))
    if m:
        return "note_add", {"text": m.group(1)}
    m = rm(r"(?:search|find)\s+(?:my\s+)?notes?\s+(?:for|about)\s+(.+)$")
    if m:
        return "note_search", {"query": m.group(1)}
    if has(r"\b(show|read|list|what(?:'s| are| is))\b.*\bnotes?\b"):
        return "note_list", {}
    m = rm(r"(?:i\s+)?(?:spent|paid|bought)\s+(?:rp\.?\s*)?([\d.,]+\s*(?:k|rb|ribu|jt|juta|thousand|million)?)"
           r"\s+(?:on|for)\s+(.+)$")
    if m:
        return "expense_add", {"amount": m.group(1), "what": m.group(2)}
    if has(r"\bhow much\b.*\b(spent|spend)\b|\b(spending|expenses?)\b.*\b(summary|report|total|this month|today)\b"
           r"|\bexpense (?:report|summary)\b"):
        return "expense_summary", {}
    # --- clipboard
    if has(r"\b(read|summari[sz]e|show|what(?:'s| is| did i))\b.*\b(clipboard|copied|i copy)\b") \
            and not has(r"\b(image|picture|photo)\b"):
        return "clipboard_read", {}
    m = rm(r"copy\s+(.+?)\s+to\s+(?:the\s+|my\s+)?clipboard$")
    if m:
        return "clipboard_set", {"text": m.group(1)}
    # --- time / dates / focus
    m = re.search(r"\b(?:time|clock)\s+(?:is it\s+)?in\s+([a-z ]+)$", t)
    if m and m.group(1).strip() in CITY_TZ:
        return "world_time", {"city": m.group(1).strip()}
    m = rm(r"(?:how many days (?:are there |is there |do i have )?(?:until|till|to|before)|how long (?:until|till)|"
           r"days (?:until|till|to)|countdown to)\s+(.+)$")
    if m and _parse_date(m.group(1)):
        return "days_until", {"date": m.group(1)}
    if has(r"\b(sunrise|sunset)\b|\bwhen does the sun\b"):
        return "sun", {}
    if has(r"\b(pomodoro|focus (?:session|mode|timer))\b"):
        n = re.findall(r"\d+", t)
        return "pomodoro", {"work_minutes": n[0] if n else 25, "break_minutes": n[1] if len(n) > 1 else 5}
    # --- routines
    m = rm(r"(?:create|make|save|add)\s+(?:a\s+|an\s+)?(?:routine|macro|mode)\s+(?:called\s+|named\s+)?(.+?)\s+"
           r"(?:that opens|to open|which opens|with|that launches)\s+(.+)$")
    if m:
        return "macro_add", {"name": m.group(1), "steps": m.group(2)}
    if has(r"\b(?:list|show|what)\b.*\b(routines|macros)\b"):
        return "macro_list", {}
    m = rm(r"(?:run|start|activate|launch|enter|begin)\s+(?:the\s+|my\s+)?(.+?)(?:\s+(?:routine|macro|mode))?$")
    if m and m.group(1).lower().strip() in load("macros", {}):
        return "macro_run", {"name": m.group(1)}
    # --- random / fun
    if has(r"\b(flip|toss)\b.*\bcoin\b|\bcoin (?:flip|toss)\b"):
        return "flip_coin", {}
    if has(r"\broll\b.*(?:dice|\bdie\b|\d*d\d+)"):
        sd, ct = re.search(r"d(\d+)\b", t), re.search(r"(\d+)\s*(?:dice|d\d)", t)
        return "roll_dice", {"sides": sd.group(1) if sd else 6, "count": ct.group(1) if ct else 1}
    m = rm(r"(?:choose|pick|decide)(?:\s+(?:between|one of|from))?\s+(.+?\s+or\s+.+)$")
    if m:
        return "choose", {"options": m.group(1)}
    if has(r"\b(generate|make|create|give me)\b.*\bpassword\b"):
        n = re.search(r"\b(\d{1,2})\b", t)
        return "password", {"length": n.group(1) if n else 16}
    if has(r"\b(fun|random|interesting) fact\b|\bdid you know\b"):
        return "fun_fact", {}
    # --- money
    m = re.search(r"\b(bitcoin|btc|ethereum|eth|solana|sol|dogecoin|doge|bnb|xrp|ripple|cardano|ada|litecoin|ltc)\b", t)
    if m and has(r"\b(price|worth|cost|how much|trading|value|rate)\b"):
        return "crypto", {"coin": m.group(1)}
    # --- communication
    m = rm(r"(?:write|compose|draft|send)\s+(?:an?\s+)?e-?mail\s+to\s+(\S+@\S+)\s*(?:about|saying|that says|:)?\s*(.*)$")
    if m:
        return "compose_email", {"to": m.group(1), "subject": m.group(2).strip()[:60], "body": m.group(2).strip()}
    m = rm(r"(?:write|compose|draft)\s+(?:an?\s+)?e-?mail(?:\s+about\s+(.+))?$")
    if m:
        return "compose_email", {"to": "", "subject": m.group(1) or "", "body": ""}
    m = rm(r"(?:send|write)\s+(?:a\s+)?(?:whatsapp|wa)(?:\s+message)?\s+to\s+(\+?[\d ]{6,})\s*(?:saying|that says|:)?\s*(.*)$")
    if m:
        return "whatsapp", {"number": m.group(1), "text": m.group(2)}
    m = rm(r"(?:directions? to|navigate to|route to|how (?:do i|to) get to)\s+(.+)$")
    if m:
        return "directions", {"destination": m.group(1)}
    # --- PC control
    if has(r"\bcancel\b.*\b(shut ?down|restart|reboot)\b"):
        return "power", {"action": "cancel"}
    if has(r"\block\b.*\b(computer|pc|laptop|screen|windows)\b"):
        return "power", {"action": "lock"}
    if has(r"\b(shut ?down|turn off|power off)\b.*\b(computer|pc|laptop)\b"):
        return "power", {"action": "shutdown"}
    if has(r"\b(restart|reboot)\b.*\b(computer|pc|laptop)\b"):
        return "power", {"action": "restart"}
    if has(r"\bsleep\b") and has(r"\b(computer|pc|laptop)\b"):
        return "power", {"action": "sleep"}
    if has(r"\b(pause|resume|play|stop)\b.*\b(music|song|track|media|video|playback)\b") \
            and not has(r"\b(youtube|spotify|search|find)\b"):
        return "media", {"action": "play_pause"}
    if has(r"\b(next|skip)\b.*\b(song|track)\b") or t in ("skip", "skip this", "skip song", "skip track"):
        return "media", {"action": "next"}
    if has(r"\b(previous|last|go back)\b.*\b(song|track)\b"):
        return "media", {"action": "previous"}
    if has(r"\bshow (?:the )?desktop\b"):
        return "window_control", {"action": "desktop"}
    if has(r"\bswitch (?:the )?window\b|\balt ?tab\b"):
        return "window_control", {"action": "switch"}
    if has(r"\bsnip(?:ping tool)?\b"):
        return "window_control", {"action": "snip"}
    if has(r"\bmaximi[sz]e (?:this |the )?window\b"):
        return "window_control", {"action": "maximize"}
    if has(r"\bnext desktop\b"):
        return "window_control", {"action": "next_desktop"}
    if has(r"\b(?:previous|last) desktop\b"):
        return "window_control", {"action": "prev_desktop"}
    m = rm(r"(?:dictate|type out)\s+(.+)$")
    if m:
        return "type_text", {"text": m.group(1)}
    if has(r"\bwhat(?:'s| is)\b.*\b(using|eating|hogging|slowing)\b.*\b(cpu|ram|memory|computer|pc|laptop)\b"
           r"|\btop processes\b|\bwhat(?:'s| is) running\b"):
        return "top_processes", {}
    m = rm(r"(?:close|quit|kill|exit)\s+(?:the\s+)?(.+)$")
    if m and m.group(1).lower().strip() in CLOSABLE:
        return "close_app", {"name": m.group(1).lower().strip()}
    if has(r"\bmy ip\b|\b(internet|wi-?fi|network)\b.*\b(status|speed|working|connected|check|slow|down)\b"
           r"|\bcheck (?:the |my )?(?:internet|network|wi-?fi)\b|\bam i online\b"):
        return "network_status", {}
    # --- files
    m = (rm(r"(?:find|locate)\s+(?:the\s+|my\s+)?file\s+(?:called\s+|named\s+)?(.+)$")
         or rm(r"(?:search|look)\s+(?:my\s+)?(?:pc|computer|laptop|files)\s+for\s+(.+)$")
         or rm(r"where(?:'s| is)\s+(?:my\s+)?(.+?)\s+file$"))
    if m:
        return "find_file", {"name": m.group(1)}
    m = rm(r"open\s+(?:the\s+|my\s+)?file\s+(?:called\s+|named\s+)?(.+)$")
    if m:
        return "open_file", {"name": m.group(1)}
    m = rm(r"(?:read|summari[sz]e)\s+(?:the\s+|my\s+)?(?:file|document|pdf|doc)\s+(?:called\s+|named\s+)?(.+)$")
    if m:
        return "read_file", {"path": m.group(1)}
    if has(r"\bwhat can you do\b|\b(?:your|the) (?:tools|commands|abilities|features)\b|\bhelp menu\b"):
        return "capabilities", {}
    return None


if not getattr(core, "_extra_patched", False):
    _orig_route = core.route

    def _route_plus(text):
        try:
            r = extra_route(text)
        except Exception:
            r = None
        return r or _orig_route(text)

    core.route = _route_plus
    core._extra_patched = True
