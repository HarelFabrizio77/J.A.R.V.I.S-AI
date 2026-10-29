#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. Mark 3  --  HUD + launcher.
Needs jarvis_core.py and jarvis_extra.py in the same folder.
model: jarvis-qwen (Qwen3.5 4B fine-tuned with Unsloth) served by Ollama

Run:   python jarvis_mk3.py            HUD window (+ wake word)
       python jarvis_mk3.py --cli      plain terminal chat
       pythonw jarvis_mk3.py           no console window (rename to .pyw for double-click)
Flags: --no-wake  --no-speak

Orb mode (F10):  drag = move | CLICK the orb = open/close the chat box | double-click = back to full HUD
Install:  pip install requests psutil SpeechRecognition pyaudio pillow pytesseract ddgs opencv-python pypdf tzdata
(only `requests` is mandatory; everything else is optional and degrades gracefully)
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import queue
import random
import re
import shutil
import threading
import time
from collections import deque

import requests

from jarvis_core import *   # noqa: F401,F403  (tools, brain, scheduler, listener, config)

try:
    import jarvis_extra as extra       # registers 40+ extra tools + routes into jarvis_core
except ImportError:
    extra = None
    print("[jarvis] jarvis_extra.py not found -- running with core tools only.")


def _x(fn, *a, default=""):
    """Call a helper from jarvis_extra without ever crashing the HUD."""
    try:
        return getattr(extra, fn)(*a) if extra else default
    except Exception:
        return default


# =====================================================================
# HUD
# =====================================================================
def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def lerp_hex(a, b, k):
    A, B = _hex(a), _hex(b)
    return "#%02x%02x%02x" % tuple(int(A[i] + (B[i] - A[i]) * k) for i in range(3))


class HUD:
    """Arc-reactor HUD: radar reactor, tabbed live panels, sparklines, themes, chat, ticker, clickable orb."""
    BG, PANEL, EDGE = "#020a12", "#041722", "#0e5566"
    CORE = "#030b13"   # must differ from BG: BG is the see-through colour in orb mode
    CY, TXT, DIMT = "#27e6ff", "#8fe9ff", "#3f7f90"
    YELLOW = "#ffe066"
    SPEED = {"idle": 1.0, "listening": 1.7, "thinking": 4.0, "speaking": 2.4, "alert": 5.0}
    ORB_W, ORB_H, ORB_CHAT_H = 340, 380, 250
    THEMES = {
        "ARC CYAN": {"state": {"idle": "#27e6ff", "listening": "#4dff91", "thinking": "#ffc857",
                               "speaking": "#6df0ff", "alert": "#ff5c5c"}, "band": "#3aa7ea", "orange": "#ffb020"},
        "MARK 85 GOLD": {"state": {"idle": "#ffb020", "listening": "#4dff91", "thinking": "#ff6a3d",
                                   "speaking": "#ffd166", "alert": "#ff3030"}, "band": "#ff8a3d", "orange": "#ff4d4d"},
        "STEALTH GREEN": {"state": {"idle": "#33ff99", "listening": "#27e6ff", "thinking": "#ffe066",
                                    "speaking": "#8dffc7", "alert": "#ff5c5c"}, "band": "#1fbf7a", "orange": "#c0ff33"},
        "VIOLET": {"state": {"idle": "#b48cff", "listening": "#4dff91", "thinking": "#ffc857",
                             "speaking": "#d6bcff", "alert": "#ff5c5c"}, "band": "#7a5cff", "orange": "#ff6ad5"},
    }
    THEME_WORDS = {"cyan": "ARC CYAN", "blue": "ARC CYAN", "gold": "MARK 85 GOLD", "orange": "MARK 85 GOLD",
                   "red": "MARK 85 GOLD", "green": "STEALTH GREEN", "stealth": "STEALTH GREEN",
                   "violet": "VIOLET", "purple": "VIOLET"}
    QUICK = [("WEATHER", "what's the weather"), ("NEWS", "give me the news"),
             ("TECH NEWS", "show me the tech news"), ("BRIEFING", "good morning"),
             ("SCHEDULE", "what's on my schedule"), ("DEADLINES", "what are my deadlines"),
             ("TO-DO", "show my to-do list"), ("NOTES", "show my notes"),
             ("LOOK", "what am i looking at"), ("READ TEXT", "read the text on my screen"),
             ("TRANSLATE", "translate my screen to english"), ("CAMERA", "what do you see on the camera"),
             ("CLIPBOARD", "what's in my clipboard image"), ("SCREENSHOT", "take a screenshot"),
             ("FOCUS 25", "start a pomodoro"), ("NETWORK", "check my network"),
             ("BITCOIN", "what's the bitcoin price"), ("SYSTEM", "system status"),
             ("FUN FACT", "tell me a fun fact"), ("JOKE", "tell me a dark joke")]

    def __init__(self, brain, speaker, wake):
        import tkinter as tk
        self.tk = tk
        self.brain, self.speaker = brain, speaker
        self.ui = queue.Queue()
        self.work = threading.Lock()
        self.state, self.t, self.rot, self.level = "idle", 0.0, 0.0, 0.1
        self.t0 = time.time()
        self.theme = "ARC CYAN"
        self.apply_theme(load("settings", {}).get("theme", "ARC CYAN"), save_it=False)
        self.col = self.STATE["idle"]
        self.stream_on = False
        self.alert_until = 0.0
        self.online = False
        self.stats = {"cpu": 0.0, "ram": 0.0, "disk": 0.0, "bat": None, "down": 0.0, "up": 0.0, "ping": None}
        self.hist = {k: deque(maxlen=90) for k in ("cpu", "ram", "down", "up")}
        self.ticker = "   J.A.R.V.I.S. MK III ONLINE   ///   AWAITING INPUT   ///   "
        self.ticker_x = 0.0
        self.listener = None
        self.mode, self.saved_geo, self.drag = "normal", None, (0, 0)
        self.subtitle, self.sub_until, self.hint_until = "", 0.0, 0.0
        self.orb_open, self._click_job, self._press = False, None, (0, 0, False)
        self.cmds, self.cmd_i = [], 0
        self.boxes = {}

        root = self.root = tk.Tk()
        root.title("J.A.R.V.I.S. Mk III")
        root.geometry("1380x840")
        root.minsize(1180, 700)
        root.configure(bg=self.BG)
        root.bind("<F11>", lambda e: self.set_mode("full"))
        root.bind("<F10>", lambda e: self.set_mode("orb"))
        root.bind("<Escape>", self._esc)
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(0, weight=1)

        # ---------------- left: telemetry + tabs
        left = self.left = tk.Frame(root, bg=self.BG)
        left.grid(row=0, column=0, sticky="ns", padx=(10, 0), pady=(10, 4))
        self.sys_cv = tk.Canvas(left, width=300, height=148, bg=self.PANEL, highlightthickness=1,
                                highlightbackground=self.EDGE)
        self.sys_cv.pack(pady=(0, 6))
        tb = tk.Frame(left, bg=self.BG)
        tb.pack(fill="x", pady=(0, 4))
        self.tabs, self.tab_btns = {}, {}
        for i, name in enumerate(("OPS", "INTEL", "WORK", "SYS")):
            b = tk.Button(tb, text=name, command=lambda n=name: self._tab(n), relief="flat", bg=self.PANEL,
                          fg=self.TXT, activebackground=self.EDGE, activeforeground="white",
                          font=("Consolas", 9, "bold"))
            b.grid(row=0, column=i, sticky="ew", padx=1)
            tb.grid_columnconfigure(i, weight=1)
            self.tab_btns[name] = b
            self.tabs[name] = tk.Frame(left, bg=self.BG)
        T = self.tabs
        self.boxes["weather"] = self._panel(T["OPS"], "WEATHER // " + HOME["name"].split(",")[0].upper(), 7)
        self.boxes["sched"] = self._panel(T["OPS"], "SCHEDULE", 6)
        self.boxes["dead"] = self._panel(T["OPS"], "DEADLINES", 5)
        self.boxes["news"] = self._panel(T["INTEL"], "HEADLINES", 11)
        self.boxes["market"] = self._panel(T["INTEL"], "MARKETS", 6)
        self.boxes["todo"] = self._panel(T["WORK"], "TO-DO", 8)
        self.boxes["notes"] = self._panel(T["WORK"], "NOTES", 8)
        self.graph_cv = tk.Canvas(T["SYS"], width=300, height=214, bg=self.PANEL, highlightthickness=1,
                                  highlightbackground=self.EDGE)
        self.graph_cv.pack(pady=(0, 6))
        self.boxes["net"] = self._panel(T["SYS"], "NETWORK", 3)
        self.boxes["procs"] = self._panel(T["SYS"], "TOP PROCESSES", 10)
        self._tab("OPS")

        # ---------------- centre: reactor
        self.cv = tk.Canvas(root, bg=self.BG, highlightthickness=0)
        self.cv.grid(row=0, column=1, sticky="nsew", pady=(10, 4))
        self.cv.bind("<Configure>", lambda e: self._regrid())
        self.cv.bind("<ButtonPress-1>", self._press_start)
        self.cv.bind("<B1-Motion>", self._drag_move)
        self.cv.bind("<ButtonRelease-1>", self._press_end)
        self.cv.bind("<Double-Button-1>", self._dbl)
        self.cv.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        self.menu = tk.Menu(root, tearoff=0, bg=self.PANEL, fg=self.TXT)
        self.menu.add_command(label="Show HUD", command=lambda: self.set_mode("normal"))
        self.menu.add_command(label="Full screen", command=lambda: self.set_mode("full"))
        self.menu.add_command(label="Orb mode", command=lambda: self.set_mode("orb"))
        self.menu.add_command(label="Toggle orb chat", command=lambda: self.orb_chat())
        tm = tk.Menu(self.menu, tearoff=0, bg=self.PANEL, fg=self.TXT)
        for name in self.THEMES:
            tm.add_command(label=name, command=lambda n=name: self.apply_theme(n))
        self.menu.add_cascade(label="Theme", menu=tm)
        self.menu.add_separator()
        self.menu.add_command(label="Stop talking", command=self.stop)
        self.menu.add_command(label="Quit Jarvis", command=root.destroy)

        # ---------------- right: chat + controls
        right = self.right = tk.Frame(root, bg=self.BG)
        right.grid(row=0, column=2, sticky="ns", padx=(0, 10), pady=(10, 4))
        tk.Label(right, text="COMMS LOG", bg=self.BG, fg=self.CY, font=("Consolas", 9, "bold")).pack(anchor="w")
        self.chat = tk.Text(right, width=48, bg=self.PANEL, fg=self.TXT, font=("Consolas", 10), wrap="word",
                            relief="flat", state="disabled", padx=8, pady=6, highlightthickness=1,
                            highlightbackground=self.EDGE)
        self.chat.pack(fill="both", expand=True)

        qf = tk.Frame(right, bg=self.BG)
        qf.pack(fill="x", pady=(6, 0))
        for i, (label, phrase) in enumerate(self.QUICK):
            b = tk.Button(qf, text=label, bg=self.PANEL, fg=self.TXT, activebackground=self.EDGE,
                          activeforeground="white", relief="flat", font=("Consolas", 8, "bold"),
                          command=lambda p=phrase: self.submit(p))
            b.grid(row=i // 4, column=i % 4, sticky="ew", padx=1, pady=1)
            qf.grid_columnconfigure(i % 4, weight=1)

        row = tk.Frame(right, bg=self.BG)
        row.pack(fill="x", pady=(8, 0))
        self.entry = tk.Entry(row, bg=self.PANEL, fg="#ffffff", insertbackground="#ffffff",
                              font=("Consolas", 12), relief="flat", highlightthickness=1,
                              highlightbackground=self.EDGE, highlightcolor=self.CY)
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", lambda e: self.send())
        self.entry.bind("<Up>", lambda e: self._hist_nav(self.entry, -1))
        self.entry.bind("<Down>", lambda e: self._hist_nav(self.entry, 1))
        for txt, cmd, bg in (("MIC", self.ptt, "#2a7d46"), ("SEND", self.send, "#0a8fa3"),
                             ("STOP", self.stop, "#c0392b")):
            tk.Button(row, text=txt, command=cmd, bg=bg, fg="white", relief="flat", width=5,
                      font=("Consolas", 10, "bold")).pack(side="left", padx=(5, 0), fill="y")

        row2 = tk.Frame(right, bg=self.BG)
        row2.pack(fill="x", pady=(8, 0))
        tk.Label(row2, text="VOL", bg=self.BG, fg=self.CY, font=("Consolas", 9, "bold")).pack(side="left")
        self.vol = tk.Scale(row2, from_=0, to=100, orient="horizontal", length=190, bg=self.BG, fg=self.TXT,
                            troughcolor=self.PANEL, highlightthickness=0, activebackground=self.CY, bd=0)
        self.vol.set(50)
        self.vol.pack(side="left", padx=6)
        self.vol.bind("<ButtonRelease-1>", lambda e: threading.Thread(
            target=run_tool, args=("set_volume", {"action": str(self.vol.get())}), daemon=True).start())
        self.wake_btn = tk.Button(row2, text="WAKE: OFF", command=self.toggle_wake, bg=self.PANEL, fg=self.TXT,
                                  relief="flat", font=("Consolas", 9, "bold"), width=10)
        self.wake_btn.pack(side="right")

        row3 = tk.Frame(right, bg=self.BG)
        row3.pack(fill="x", pady=(8, 0))
        for label, cmd in (("IMAGE...", self.attach_image), ("FULLSCREEN  F11", lambda: self.set_mode("full")),
                           ("ORB MODE  F10", lambda: self.set_mode("orb"))):
            tk.Button(row3, text=label, command=cmd, bg=self.PANEL, fg=self.TXT, activebackground=self.EDGE,
                      activeforeground="white", relief="flat", font=("Consolas", 9, "bold")
                      ).pack(side="left", fill="x", expand=True, padx=1)

        # ---------------- bottom: ticker
        self.tk_cv = tk.Canvas(root, height=26, bg=self.PANEL, highlightthickness=1, highlightbackground=self.EDGE)
        self.tk_cv.grid(row=1, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 10))

        # ---------------- orb chat panel (shown over the orb when you click it)
        self.orb_panel = tk.Frame(root, bg=self.PANEL, highlightthickness=1, highlightbackground=self.CY)
        self.orb_log = tk.Text(self.orb_panel, height=9, bg=self.PANEL, fg=self.TXT, font=("Segoe UI", 9),
                               wrap="word", relief="flat", state="disabled", padx=6, pady=4, highlightthickness=0)
        orow = tk.Frame(self.orb_panel, bg=self.PANEL)
        orow.pack(side="bottom", fill="x", padx=4, pady=4)
        self.orb_entry = tk.Entry(orow, bg=self.BG, fg="#ffffff", insertbackground="#ffffff", font=("Segoe UI", 10),
                                  relief="flat", highlightthickness=1, highlightbackground=self.EDGE,
                                  highlightcolor=self.CY)
        self.orb_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.orb_entry.bind("<Return>", lambda e: self.orb_send())
        self.orb_entry.bind("<Up>", lambda e: self._hist_nav(self.orb_entry, -1))
        self.orb_entry.bind("<Down>", lambda e: self._hist_nav(self.orb_entry, 1))
        tk.Button(orow, text="MIC", command=self.ptt, bg="#2a7d46", fg="white", relief="flat",
                  font=("Consolas", 9, "bold")).pack(side="left", padx=(4, 0), fill="y")
        tk.Button(orow, text="X", command=lambda: self.orb_chat(False), bg="#c0392b", fg="white", relief="flat",
                  font=("Consolas", 9, "bold")).pack(side="left", padx=(4, 0), fill="y")
        self.orb_log.pack(side="top", fill="both", expand=True)

        self.logs = [self.chat, self.orb_log]
        for w in self.logs:
            w.tag_config("you", foreground="#ffffff")
            w.tag_config("jarvis", foreground=self.CY)
            w.tag_config("sys", foreground=self.DIMT, font=("Consolas", 9, "italic"))
            w.tag_config("alert", foreground="#ff8a8a")

        if wake:
            self._start_listener()
        self.entry.focus()
        self.log("sys", "Systems online. F11 = fullscreen, F10 = orb mode (click the orb to chat, double-click to "
                 "come back). Right-click the reactor for themes."
                 + (" Say 'hey jarvis' to talk." if wake else ""))
        sfx("start")
        threading.Thread(target=self._fast_loop, daemon=True).start()
        threading.Thread(target=self._slow_loop, daemon=True).start()
        self._pump()
        self._draw()
        self._tick_ticker()

    # ---------------------------------------------------------------- helpers
    def apply_theme(self, name, save_it=True):
        th = self.THEMES.get(name) or self.THEMES["ARC CYAN"]
        self.theme = name if name in self.THEMES else "ARC CYAN"
        self.STATE = dict(th["state"])
        self.BAND, self.ORANGE = th["band"], th["orange"]
        if save_it:
            s = load("settings", {})
            s["theme"] = self.theme
            save("settings", s)

    def _panel(self, parent, title, lines):
        tk = self.tk
        f = tk.Frame(parent, bg=self.BG)
        f.pack(fill="x", pady=(0, 6))
        tk.Label(f, text=title, bg=self.BG, fg=self.CY, font=("Consolas", 9, "bold")).pack(anchor="w")
        box = tk.Text(f, width=40, height=lines, bg=self.PANEL, fg=self.TXT, font=("Consolas", 9), wrap="word",
                      relief="flat", state="disabled", padx=6, pady=4, highlightthickness=1,
                      highlightbackground=self.EDGE)
        box.pack(fill="x")
        return box

    def _tab(self, name):
        for n, f in self.tabs.items():
            f.pack_forget()
            self.tab_btns[n].config(bg=self.EDGE if n == name else self.PANEL)
        self.tabs[name].pack(fill="x")

    @staticmethod
    def _set(box, text):
        box.config(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.config(state="disabled")

    def post(self, kind, *a):
        self.ui.put((kind, a))

    def _line(self, who, text, tag):
        for c in self.logs:
            c.config(state="normal")
            if who:
                c.insert("end", f"{who}: ", tag)
            c.insert("end", text + "\n", tag)
            c.config(state="disabled")
            c.see("end")

    def log(self, tag, text):
        self._line("", text, tag)

    def _lstatus(self, s):
        self.post("status" if s in self.STATE else "sys", s)

    def _start_listener(self):
        self.listener = Listener(self.voice_cmd, self.speaker, self._lstatus)
        self.listener.start()
        self.wake_btn.config(text="WAKE: ON")

    def _hist_nav(self, entry, d):
        if self.cmds:
            self.cmd_i = max(0, min(len(self.cmds), self.cmd_i + d))
            entry.delete(0, "end")
            if self.cmd_i < len(self.cmds):
                entry.insert(0, self.cmds[self.cmd_i])
        return "break"

    def _esc(self, e=None):
        if self.mode == "orb" and self.orb_open:
            self.orb_chat(False)
        elif self.mode == "full":
            self.set_mode("normal")

    # ---------------------------------------------------------------- background data
    def _fast_loop(self):
        """Every 2 s: CPU/RAM/disk/battery/network speed + sparkline history."""
        n, last_net, last_t = 0, None, time.time()
        while True:
            try:
                import psutil
                now = time.time()
                nio = psutil.net_io_counters()
                down = up = 0.0
                if last_net:
                    d = max(0.1, now - last_t)
                    down = (nio.bytes_recv - last_net.bytes_recv) / d / 1024
                    up = (nio.bytes_sent - last_net.bytes_sent) / d / 1024
                last_net, last_t = nio, now
                b = psutil.sensors_battery()
                du = shutil.disk_usage(os.path.abspath(os.sep))
                cpu, ram = psutil.cpu_percent(), psutil.virtual_memory().percent
                self.stats.update(cpu=cpu, ram=ram, disk=du.used / du.total * 100,
                                  bat=b.percent if b else None, down=down, up=up)
                for k, v in (("cpu", cpu), ("ram", ram), ("down", down), ("up", up)):
                    self.hist[k].append(v)
            except Exception:
                pass
            if n % 3 == 0:
                try:
                    self.online = requests.get(OLLAMA + "/api/tags", timeout=1.5).ok
                except Exception:
                    self.online = False
                self.stats["ping"] = _x("ping_ms", default=None)
                self.post("panels", {"sched": t_list_sched().replace("; ", "\n"),
                                     "dead": t_list_deadlines().replace("; ", "\n"),
                                     "todo": _x("todo_lines", default="(jarvis_extra.py missing)"),
                                     "notes": _x("notes_lines", default="")})
            self.post("stats")
            n += 1
            time.sleep(2)

    def _slow_loop(self):
        """Slow network stuff: weather, news, markets, process list, IP info."""
        n = 0
        while True:
            panels = {}
            try:
                if n % 30 == 0:
                    panels["weather"] = t_weather()
                    panels["news"] = t_news(count=3)
                if n % 90 == 0:
                    panels["market"] = _x("market_snapshot", default="(extras not loaded)")
                if n % 5 == 0:
                    panels["procs"] = _x("top_lines", default="(extras not loaded)")
                if n % 15 == 0:
                    panels["net"] = _x("net_lines", default="")
            except Exception:
                pass
            if panels:
                self.post("panels", panels)
            n += 1
            time.sleep(2)

    # ---------------------------------------------------------------- UI event pump
    def _pump(self):
        try:
            while True:
                kind, a = self.ui.get_nowait()
                if kind == "you":
                    self._line("YOU", a[0], "you")
                elif kind == "sys":
                    self.log("sys", a[0])
                elif kind == "alert":
                    self.state = "alert"
                    self.alert_until = time.time() + 6
                    self._line("JARVIS", a[0], "alert")
                    self.subtitle, self.sub_until = a[0], time.time() + 8
                elif kind == "status":
                    self.state = a[0]
                elif kind == "stream":
                    self._stream(a[0], False)
                elif kind == "final":
                    self._stream(a[0], True)
                    self.subtitle = a[0][:240]
                    self.sub_until = time.time() + max(6.0, len(a[0]) * 0.07)
                elif kind == "mode":
                    self.set_mode(a[0])
                elif kind == "theme":
                    self.apply_theme(a[0])
                elif kind == "stats":
                    self._draw_sys()
                    self._draw_graph()
                elif kind == "panels":
                    for k, v in a[0].items():
                        if k in self.boxes:
                            self._set(self.boxes[k], v)
                        if k == "news":
                            heads = [ln.split(": ", 1)[-1] for ln in v.splitlines() if ": " in ln]
                            flat = "   ///   ".join(h.replace(" | ", "   ///   ") for h in heads)
                            if flat:
                                self.ticker = "   " + flat + "   ///   "
        except queue.Empty:
            pass
        self.root.after(50, self._pump)

    def _stream(self, text, final):
        first = not self.stream_on
        for c in self.logs:
            c.config(state="normal")
            if first:
                c.insert("end", "JARVIS: ", "jarvis")
                c.mark_set("sm", "end-1c")
                c.mark_gravity("sm", "left")
            c.delete("sm", "end-1c")
            c.insert("end", text, "jarvis")
            if final:
                c.insert("end", "\n")
            c.config(state="disabled")
            c.see("end")
        self.stream_on = not final

    # ---------------------------------------------------------------- drawing
    def _draw_sys(self):
        c = self.sys_cv
        c.delete("all")
        st = self.stats
        c.create_text(8, 12, anchor="w", text="SYSTEM", fill=self.CY, font=("Consolas", 9, "bold"))
        c.create_text(292, 12, anchor="e", text="OLLAMA " + ("ONLINE" if self.online else "OFFLINE"),
                      fill="#4dff91" if self.online else "#ff5c5c", font=("Consolas", 9, "bold"))
        rows = [("CPU", st["cpu"]), ("RAM", st["ram"]), ("DISK", st["disk"])]
        if st["bat"] is not None:
            rows.append(("BAT", st["bat"]))
        for i, (name, v) in enumerate(rows):
            y = 34 + i * 21
            c.create_text(8, y, anchor="w", text=name, fill=self.TXT, font=("Consolas", 9))
            c.create_rectangle(52, y - 6, 240, y + 6, outline=self.EDGE)
            bad = v >= 85 if name != "BAT" else v <= 20
            c.create_rectangle(53, y - 5, 53 + 186 * max(0, min(v, 100)) / 100, y + 5,
                               fill="#ff5c5c" if bad else self.CY, outline="")
            c.create_text(292, y, anchor="e", text=f"{v:.0f}%", fill=self.TXT, font=("Consolas", 9))
        ping = st.get("ping")
        c.create_text(8, 134, anchor="w", text=f"PING {ping} ms" if ping is not None else "PING --",
                      fill=self.TXT if ping is not None else "#ff5c5c", font=("Consolas", 9))
        c.create_text(292, 134, anchor="e", text=f"DN {st['down']:.0f}  UP {st['up']:.0f} KB/s", fill=self.TXT,
                      font=("Consolas", 9))

    def _spark(self, c, x0, y0, x1, y1, data, color, label, vmax=100, frame=True):
        if frame:
            c.create_rectangle(x0, y0, x1, y1, outline=self.EDGE)
            c.create_text(x0 + 5, y0 + 8, anchor="w", text=label, fill=color, font=("Consolas", 8, "bold"))
            for g in (0.25, 0.5, 0.75):
                c.create_line(x0, y1 - (y1 - y0) * g, x1, y1 - (y1 - y0) * g, fill="#06202c")
        n = len(data)
        if n < 2:
            return
        step = (x1 - x0) / (data.maxlen - 1)
        pts = []
        for i, v in enumerate(data):
            pts += [x1 - (n - 1 - i) * step, y1 - (y1 - y0 - 2) * min(max(v, 0), vmax) / vmax - 1]
        c.create_line(*pts, fill=color, width=1.6)

    def _draw_graph(self):
        c = self.graph_cv
        c.delete("all")
        h = self.hist
        cpu, ram, dn, up = h["cpu"], h["ram"], h["down"], h["up"]
        self._spark(c, 6, 6, 294, 64, cpu, self.col, f"CPU {cpu[-1]:.0f}%" if cpu else "CPU")
        self._spark(c, 6, 74, 294, 132, ram, self.ORANGE, f"RAM {ram[-1]:.0f}%" if ram else "RAM")
        vmax = max(max(dn, default=0), max(up, default=0), 50) * 1.15
        self._spark(c, 6, 142, 294, 200, dn, "#4dff91",
                    f"NET  DN {dn[-1]:.0f}  UP {up[-1]:.0f} KB/s" if dn else "NET", vmax)
        self._spark(c, 6, 142, 294, 200, up, "#ff8a8a", "", vmax, frame=False)

    def _regrid(self):
        if self.mode == "orb":
            return
        c = self.cv
        w, h = c.winfo_width(), c.winfo_height()
        c.delete("grid")
        for x in range(0, w, 40):
            c.create_line(x, 0, x, h, fill="#06202c", tags="grid")
        for y in range(0, h, 40):
            c.create_line(0, y, w, y, fill="#06202c", tags="grid")
        c.tag_lower("grid")

    def _draw(self):
        cv = self.cv
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 80 or h < 80:
            self.root.after(100, self._draw)
            return
        cv.delete("a")
        if self.state == "speaking" and not self.speaker.busy:
            self.state = "idle"
        if self.state == "alert" and time.time() > self.alert_until and not self.speaker.busy:
            self.state = "idle"
        st = self.state
        self.t += 0.033
        self.rot += self.SPEED[st]
        t, rot = self.t, self.rot
        self.col = lerp_hex(self.col, self.STATE[st], 0.12)
        col = self.col
        dim, mid = lerp_hex(col, self.BG, 0.7), lerp_hex(col, self.BG, 0.35)
        orb = self.mode == "orb"
        boot = min(1.0, (time.time() - self.t0) / 1.6)
        ease = 1 - (1 - boot) ** 3
        if orb:
            off = self.ORB_CHAT_H if self.orb_open else 0
            ch = h - off
            cx, cy, s = w / 2, off + ch * 0.40, min(w, ch * 0.78) / 590
        else:
            cx, cy = w / 2, h / 2 - 4
            s = min(w, h - 10) / 590
        s *= 0.6 + 0.4 * ease

        def ring(r, width, start, extent, color, dash=None):
            r *= s
            kw = dict(start=start, extent=extent, style="arc", outline=color, width=max(1, width * s), tags="a")
            if dash:
                kw["dash"] = dash
            cv.create_arc(cx - r, cy - r, cx + r, cy + r, **kw)

        # level meter drives the bright band
        if st == "speaking":
            target = 0.55 + 0.4 * abs(math.sin(t * 7)) * random.uniform(0.7, 1.0)
        elif st == "thinking":
            target = 0.5 + 0.5 * math.sin(t * 5)
        elif st == "listening":
            target = 0.3 + 0.25 * random.random()
        elif st == "alert":
            target = 0.5 + 0.5 * math.sin(t * 12)
        else:
            target = 0.12 + 0.75 * min(1.0, self.stats["cpu"] / 100)
        self.level += (target - self.level) * 0.25

        # outer dotted ring + three big segments
        ring(285, 1, rot * 0.2, 359.9, dim, (1, 9))
        for k in range(3):
            ring(272, 3, -rot * 0.35 + k * 120, 78, mid)
        ring(250, 10, rot * 0.12, 359.9, dim, (1, 4))
        ring(262, 1, 0, 359.9, dim)
        # radar sweep
        sw, rr = (rot * 2.0) % 360, 192 * s
        for k in range(9):
            cv.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, start=sw - k * 4, extent=4.5, style="pieslice",
                          fill=lerp_hex(col, self.BG, 0.62 + k * 0.04), outline="", tags="a")
        # bright segmented band
        n = 52
        lit = int(self.level * n)
        for i in range(n):
            a0 = 225 - i * (290 / n)
            ring(212, 34, a0, -(290 / n) + 1.2, lerp_hex(col, self.BAND, 0.45) if i < lit else
                 lerp_hex(col, self.BG, 0.86))
        ring(192, 1, 0, 359.9, mid)
        ring(232, 1, 0, 359.9, dim)
        # orange arcs + yellow dots
        ring(178, 4, rot * 0.9, 105, self.ORANGE)
        ring(178, 4, rot * 0.9 + 125, 24, self.ORANGE)
        for k in range(4):
            ang = math.radians(rot * 1.4 + k * 7)
            r2 = 238 * s
            cv.create_oval(cx + r2 * math.cos(ang) - 3 * s, cy - r2 * math.sin(ang) - 3 * s,
                           cx + r2 * math.cos(ang) + 3 * s, cy - r2 * math.sin(ang) + 3 * s,
                           fill=self.YELLOW, outline="", tags="a")
        # inner machinery
        ring(150, 7, -rot * 0.6, 359.9, dim, (2, 7))
        for k in range(4):
            ring(138, 2, rot * 0.5 + k * 90, 62, col)
        ring(124, 1, 0, 359.9, mid)
        # radial waveform
        bars = 84
        for i in range(bars):
            ang = math.radians(i * 360 / bars + rot * 0.1)
            amp = 3 + self.level * 30 * (0.35 + 0.65 * abs(math.sin(i * 0.9 + t * 6)))
            r0, r1 = 104 * s, (104 + amp) * s
            cv.create_line(cx + r0 * math.cos(ang), cy - r0 * math.sin(ang),
                           cx + r1 * math.cos(ang), cy - r1 * math.sin(ang),
                           fill=col if i % 2 else mid, width=max(1, 1.4 * s), tags="a")
        # core
        r = 96 * s
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=self.CORE, outline=col, width=2, tags="a")
        cv.create_text(cx, cy - 8 * s, text="J.A.R.V.I.S.", fill="#ffffff",
                       font=("Segoe UI", max(8, int(21 * s)), "bold"), tags="a")
        cv.create_text(cx, cy + 20 * s, text=st.upper(), fill=col, font=("Consolas", max(7, int(10 * s)), "bold"),
                       tags="a")
        cv.create_text(cx, cy + 38 * s, text=dt.datetime.now().strftime("%H:%M:%S"), fill=self.TXT,
                       font=("Consolas", max(7, int(11 * s))), tags="a")
        if orb:
            # status dot (green = Ollama online) + hint / subtitle under the orb
            dx, dy = cx + 270 * s, cy - 250 * s
            cv.create_oval(dx - 4, dy - 4, dx + 4, dy + 4, fill="#4dff91" if self.online else "#ff5c5c",
                           outline="", tags="a")
            if not self.orb_open:
                if self.subtitle and time.time() < self.sub_until:
                    cv.create_text(w / 2, cy + 292 * s + 8, text=self.subtitle, fill=self.TXT, width=w - 24,
                                   anchor="n", justify="center", font=("Segoe UI", 10), tags="a")
                elif time.time() < self.hint_until:
                    cv.create_text(w / 2, cy + 292 * s + 8, text="click the orb to chat", fill=self.DIMT,
                                   anchor="n", font=("Segoe UI", 9, "italic"), tags="a")
        else:
            f = ("Consolas", 9)
            sx = self.stats
            cv.create_text(14, 14, anchor="nw", text="MK III // JARVIS-QWEN", fill=self.TXT, font=f, tags="a")
            cv.create_text(14, 30, anchor="nw", text=f"CPU {sx['cpu']:.0f}%  RAM {sx['ram']:.0f}%",
                           fill=self.DIMT, font=f, tags="a")
            cv.create_text(w - 14, 14, anchor="ne", text=dt.datetime.now().strftime("%a %d %b %Y").upper(),
                           fill=self.TXT, font=f, tags="a")
            cv.create_text(w - 14, 30, anchor="ne", text=f"THEME {self.theme}", fill=self.DIMT, font=f, tags="a")
            cv.create_text(14, h - 14, anchor="sw", text=f"LOC {HOME['name'].upper()}", fill=self.DIMT, font=f,
                           tags="a")
            cv.create_text(w - 14, h - 14, anchor="se",
                           text=f"THINKING OFF  TEMP {BASE_TEMP}  CHAOS {int(CHAOS_CHANCE * 100)}%",
                           fill=self.DIMT, font=f, tags="a")
            for (x, y, dx, dy) in ((8, 8, 1, 1), (w - 8, 8, -1, 1), (8, h - 8, 1, -1), (w - 8, h - 8, -1, -1)):
                cv.create_line(x, y, x + 26 * dx, y, fill=col, width=2, tags="a")
                cv.create_line(x, y, x, y + 26 * dy, fill=col, width=2, tags="a")
            if st == "alert" and math.sin(t * 10) > 0:
                cv.create_rectangle(3, 3, w - 3, h - 3, outline=col, width=3, tags="a")
        self.root.after(33, self._draw)

    def _tick_ticker(self):
        c = self.tk_cv
        c.delete("all")
        txt = self.ticker * 2
        self.ticker_x -= 1.6
        item = c.create_text(self.ticker_x, 13, anchor="w", text=txt, fill=self.TXT, font=("Consolas", 10))
        bb = c.bbox(item)
        if bb and self.ticker_x < -(bb[2] - bb[0]) / 2:
            self.ticker_x = 0
        self.root.after(33, self._tick_ticker)

    # ---------------------------------------------------------------- window modes
    def set_mode(self, mode):
        """normal = full HUD window | full = fullscreen HUD | orb = small floating orb (click it to chat)."""
        r, prev = self.root, self.mode
        if mode == prev:
            if mode == "normal":
                return
            mode = "normal"                      # pressing the same mode key again toggles back
        if prev == "normal":
            self.saved_geo = r.geometry()
        self.mode = mode
        orb_switch = "orb" in (prev, mode)
        if orb_switch:
            r.withdraw()
        try:
            if prev == "full":
                r.attributes("-fullscreen", False)
            if prev == "orb":
                self.orb_open = False
                self.orb_panel.place_forget()
                for opt, val in (("-transparentcolor", ""), ("-topmost", False)):
                    try:
                        r.attributes(opt, val)
                    except Exception:
                        pass
                r.overrideredirect(False)
                self.left.grid()
                self.right.grid()
                self.tk_cv.grid()
            if mode == "orb":
                self.left.grid_remove()
                self.right.grid_remove()
                self.tk_cv.grid_remove()
                self.cv.delete("grid")
                r.minsize(200, 200)
                r.overrideredirect(True)
                sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
                r.geometry(f"{self.ORB_W}x{self.ORB_H}+{sw - self.ORB_W - 30}+{sh - self.ORB_H - 80}")
                self.hint_until = time.time() + 7
                for opt, val in (("-topmost", True), ("-transparentcolor", self.BG)):
                    try:
                        r.attributes(opt, val)
                    except Exception:
                        pass
            else:
                r.minsize(1180, 700)
                if prev == "orb" and self.saved_geo:
                    r.geometry(self.saved_geo)
                if mode == "full":
                    r.attributes("-fullscreen", True)
        finally:
            if orb_switch:
                r.deiconify()
            self.root.after(150, self._regrid)

    # ---- orb: click = chat, drag = move, double-click = back to HUD
    def _press_start(self, e):
        r = self.root
        self.drag = (e.x_root - r.winfo_x(), e.y_root - r.winfo_y())
        self._press = (e.x_root, e.y_root, False)

    def _drag_move(self, e):
        if self.mode != "orb":
            return
        px, py, moved = self._press
        if not moved and abs(e.x_root - px) + abs(e.y_root - py) > 5:
            self._press = (px, py, True)
        if self._press[2]:
            self.root.geometry(f"+{e.x_root - self.drag[0]}+{e.y_root - self.drag[1]}")

    def _press_end(self, e):
        if self.mode == "orb" and not self._press[2]:
            if self._click_job:
                self.root.after_cancel(self._click_job)
            self._click_job = self.root.after(260, self._single_click)

    def _single_click(self):
        self._click_job = None
        self.orb_chat()

    def _dbl(self, e):
        if self.mode == "orb":
            if self._click_job:
                self.root.after_cancel(self._click_job)
                self._click_job = None
            self.set_mode("normal")

    def orb_chat(self, open_=None):
        """Open/close the little chat box attached to the orb (only in orb mode)."""
        if self.mode != "orb":
            return
        want = (not self.orb_open) if open_ is None else open_
        if want == self.orb_open:
            return
        r = self.root
        x, y, w, h = r.winfo_x(), r.winfo_y(), r.winfo_width(), r.winfo_height()
        off = self.ORB_CHAT_H
        self.orb_open = want
        if want:
            ny = max(0, y - off)
            r.geometry(f"{w}x{h + off}+{x}+{ny}")
            self.orb_panel.place(x=0, y=0, relwidth=1, height=off)
            self.orb_panel.lift()
            self.orb_log.see("end")
            r.after(120, self._orb_focus)
        else:
            self.orb_panel.place_forget()
            r.geometry(f"{w}x{max(200, h - off)}+{x}+{y + off}")

    def _orb_focus(self):
        try:
            self.root.focus_force()
            self.orb_entry.focus_force()
        except Exception:
            pass

    def orb_send(self):
        t = self.orb_entry.get().strip()
        self.orb_entry.delete(0, "end")
        if t:
            self.submit(t)

    def attach_image(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="Pick an image", filetypes=[
            ("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("All files", "*.*")])
        if path:
            q = self.entry.get().strip() or "describe this image"
            self.entry.delete(0, "end")
            self.submit(f'{q} "{path}"')

    # ---------------------------------------------------------------- actions
    def send(self):
        t = self.entry.get().strip()
        self.entry.delete(0, "end")
        if t:
            self.submit(t)

    def voice_cmd(self, text):
        self.submit(text)

    def ptt(self):
        """Push-to-talk: one spoken command, no wake word needed."""
        def run():
            try:
                import speech_recognition as sr
            except ImportError:
                self.post("sys", "Voice input needs: pip install SpeechRecognition pyaudio")
                return
            self.post("status", "listening")
            sfx("wake")
            try:
                rec = sr.Recognizer()
                with sr.Microphone() as src:
                    rec.adjust_for_ambient_noise(src, 0.4)
                    audio = rec.listen(src, timeout=6, phrase_time_limit=12)
                text = rec.recognize_google(audio)
            except Exception as e:
                self.post("sys", f"Didn't catch that ({type(e).__name__}).")
                self.post("status", "idle")
                return
            self.submit(text)
        threading.Thread(target=run, daemon=True).start()

    def submit(self, text):
        if not self.cmds or self.cmds[-1] != text:
            self.cmds.append(text)
        self.cmd_i = len(self.cmds)
        self.post("you", text)
        threading.Thread(target=self._work, args=(text,), daemon=True).start()

    def _local(self, msg, mode):
        self.post("mode", mode)
        self._say(msg)

    def _say(self, msg):
        self.post("final", msg)
        self.speaker.say(msg)
        self.post("status", "speaking" if self.speaker.enabled else "idle")

    def _work(self, text):
        low = text.lower().strip(" .!?,")
        if low in STOP_WORDS:
            self.stop()
            return
        if re.search(r"\b(orb mode|go (?:to )?(?:the )?background|stand ?by mode|minimi[sz]e|hide (?:the )?(?:hud|interface))\b", low):
            return self._local("Going to the background. Click the orb when you need me.", "orb")
        if re.search(r"\bfull ?screen\b", low):
            return self._local("Full screen.", "full")
        if re.search(r"\b(?:show|open|bring up) (?:the )?(?:hud|interface|dashboard|window)\b|\bnormal mode\b|\b(?:restore|expand)\b", low):
            return self._local("Back on screen.", "normal")
        m = re.search(r"\b(?:theme|colou?r|skin)\b.*\b(cyan|blue|gold|orange|red|green|stealth|violet|purple)\b", low)
        if m:
            self.post("theme", self.THEME_WORDS[m.group(1)])
            return self._say("Theme updated.")
        with self.work:
            self.post("status", "thinking")
            try:
                reply = self.brain.respond(text, on_stream=lambda s: self.post("stream", s))
            except Exception as e:
                reply = f"Something broke: {e}"
            self.post("final", reply)
            self.speaker.say(reply)
            self.post("status", "speaking" if self.speaker.enabled else "idle")

    def stop(self):
        self.brain.cancel.set()
        self.speaker.stop()
        self.post("status", "idle")

    def toggle_wake(self):
        if not self.listener:
            self._start_listener()
            return
        self.listener.active = not self.listener.active
        self.wake_btn.config(text="WAKE: ON" if self.listener.active else "WAKE: OFF")

    def alert(self, msg):
        self.post("alert", msg)
        self.speaker.say(msg)
        sfx("alarm")

    def run(self):
        self.root.mainloop()


# =====================================================================
# MAIN
# =====================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", action="store_true")
    ap.add_argument("--no-wake", action="store_true")
    ap.add_argument("--no-speak", action="store_true")
    a = ap.parse_args()
    brain, speaker = Brain(), Speaker(enabled=not a.no_speak)

    if a.cli:
        def alert(msg):
            print(f"\n[JARVIS] {msg}\nyou> ", end="", flush=True)
            speaker.say(msg)
            sfx("alarm")
        Scheduler(alert).start()
        print("JARVIS Mk III online. Type 'exit' to quit.")
        while True:
            try:
                t = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if t.lower() in ("exit", "quit"):
                break
            if not t:
                continue
            if t.lower().strip(" .!?") in STOP_WORDS:
                speaker.stop()
                continue
            reply = brain.respond(t, on_stream=None)
            print("jarvis>", reply)
            speaker.say(reply)
        return

    hud = HUD(brain, speaker, wake=not a.no_wake)
    Scheduler(hud.alert).start()
    hud.run()


if __name__ == "__main__":
    main()
