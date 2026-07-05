#!/usr/bin/env python3

import json
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk
import yt_dlp

# ── Paths ─────────────────────────────────────────────────────────────────────

# Works both as .py and frozen .exe
SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
HISTORY_FILE = os.path.join(SCRIPT_DIR, "history.json")
DEFAULT_OUTPUT = os.path.join(SCRIPT_DIR, "output")

_FFMPEG_WINGET = os.path.expandvars(
    r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin"
)


def _ffmpeg_location() -> str | None:
    if shutil.which("ffmpeg"):
        return None
    if os.path.isfile(os.path.join(_FFMPEG_WINGET, "ffmpeg.exe")):
        return _FFMPEG_WINGET
    return None


# ── History helpers ───────────────────────────────────────────────────────────

def history_load() -> list[dict]:
    if not os.path.isfile(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def history_save(entries: list[dict]):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def history_add(entries: list[dict], title: str, url: str, size_mb: float, path: str):
    entries.insert(0, {
        "title": title,
        "url": url,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "size_mb": round(size_mb, 1),
        "path": path,
    })
    history_save(entries)


# ── App ───────────────────────────────────────────────────────────────────────

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class HistoryRow(ctk.CTkFrame):
    """Single row in the history list."""

    def __init__(self, master, entry: dict, on_delete, **kwargs):
        super().__init__(master, fg_color="#1e1e2e", corner_radius=8, **kwargs)
        self.entry = entry
        self.on_delete = on_delete
        self._build(entry)

    def _build(self, e: dict):
        self.grid_columnconfigure(0, weight=1)

        title_lbl = ctk.CTkLabel(
            self,
            text=e["title"],
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        title_lbl.grid(row=0, column=0, padx=12, pady=(8, 0), sticky="ew")

        meta = f"{e['date']}   ·   {e['size_mb']} MB"
        meta_lbl = ctk.CTkLabel(
            self,
            text=meta,
            font=ctk.CTkFont(size=11),
            text_color="gray60",
            anchor="w",
        )
        meta_lbl.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")

        open_btn = ctk.CTkButton(
            self,
            text="📂",
            width=34,
            height=34,
            fg_color="gray30",
            hover_color="gray40",
            font=ctk.CTkFont(size=14),
            command=self._open_folder,
        )
        open_btn.grid(row=0, column=1, rowspan=2, padx=(4, 4), pady=8)

        del_btn = ctk.CTkButton(
            self,
            text="✕",
            width=34,
            height=34,
            fg_color="#4a1515",
            hover_color="#6b2020",
            font=ctk.CTkFont(size=13),
            command=lambda: self.on_delete(self.entry),
        )
        del_btn.grid(row=0, column=2, rowspan=2, padx=(0, 10), pady=8)

    def _open_folder(self):
        folder = os.path.dirname(self.entry["path"])
        if os.path.isdir(folder):
            os.startfile(folder)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("yt2mp3")
        self.geometry("720x680")
        self.minsize(600, 560)
        self.resizable(True, True)

        self._msg_queue: queue.Queue = queue.Queue()
        self._download_thread: threading.Thread | None = None
        self._history: list[dict] = history_load()
        self._output_dir = tk.StringVar(value=DEFAULT_OUTPUT)

        self._build_ui()
        self._poll_queue()

    # ── UI layout ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=24, pady=(18, 0), sticky="ew")
        ctk.CTkLabel(
            header_frame,
            text="yt2mp3",
            font=ctk.CTkFont(size=28, weight="bold"),
        ).pack(side="left")

        # Tabs
        self.tabs = ctk.CTkTabview(self, anchor="nw")
        self.tabs.grid(row=1, column=0, padx=16, pady=(8, 16), sticky="nsew")
        self.tabs.add("⬇  Pobieranie")
        self.tabs.add("📋  Historia")

        self._build_download_tab(self.tabs.tab("⬇  Pobieranie"))
        self._build_history_tab(self.tabs.tab("📋  Historia"))

    # ── Download tab ──────────────────────────────────────────────────────────

    def _build_download_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=2)
        parent.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(
            parent,
            text="Wklej linki YouTube — jeden na linię",
            font=ctk.CTkFont(size=13),
            text_color="gray70",
        ).grid(row=0, column=0, pady=(4, 4), sticky="w")

        # URL input
        self.url_box = ctk.CTkTextbox(
            parent,
            font=ctk.CTkFont(family="Consolas", size=13),
            wrap="none",
        )
        self.url_box.grid(row=1, column=0, sticky="nsew")
        self.url_box.insert("1.0", "https://www.youtube.com/watch?v=...\n")
        self.url_box.bind("<FocusIn>", self._clear_placeholder)

        # Folder picker row
        folder_frame = ctk.CTkFrame(parent, fg_color="transparent")
        folder_frame.grid(row=2, column=0, pady=(10, 0), sticky="ew")
        folder_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            folder_frame,
            text="Folder docelowy:",
            font=ctk.CTkFont(size=13),
        ).grid(row=0, column=0, padx=(0, 8))

        self.folder_entry = ctk.CTkEntry(
            folder_frame,
            textvariable=self._output_dir,
            font=ctk.CTkFont(family="Consolas", size=12),
            height=34,
        )
        self.folder_entry.grid(row=0, column=1, sticky="ew")

        ctk.CTkButton(
            folder_frame,
            text="Przeglądaj",
            width=90,
            height=34,
            fg_color="gray30",
            hover_color="gray40",
            command=self._pick_folder,
        ).grid(row=0, column=2, padx=(6, 0))

        # Buttons
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.grid(row=3, column=0, pady=10, sticky="ew")
        btn_frame.grid_columnconfigure(1, weight=1)

        self.download_btn = ctk.CTkButton(
            btn_frame,
            text="⬇  Pobierz MP3",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            command=self._start_download,
        )
        self.download_btn.grid(row=0, column=0, sticky="w")

        self.open_btn = ctk.CTkButton(
            btn_frame,
            text="📂  Otwórz folder",
            height=40,
            fg_color="gray30",
            hover_color="gray40",
            command=self._open_output,
        )
        self.open_btn.grid(row=0, column=2, sticky="e")

        ctk.CTkButton(
            btn_frame,
            text="Wyczyść log",
            height=40,
            width=110,
            fg_color="gray25",
            hover_color="gray35",
            command=self._clear_log,
        ).grid(row=0, column=3, padx=(8, 0), sticky="e")

        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(parent, height=6)
        self.progress_bar.grid(row=4, column=0, pady=(0, 6), sticky="ew")
        self.progress_bar.set(0)

        # Log
        ctk.CTkLabel(
            parent, text="Log", font=ctk.CTkFont(size=12), text_color="gray60"
        ).grid(row=5, column=0, pady=(0, 2), sticky="w")  # label before log

        self.log_box = ctk.CTkTextbox(
            parent,
            font=ctk.CTkFont(family="Consolas", size=12),
            state="disabled",
            wrap="none",
        )
        self.log_box.grid(row=6, column=0, sticky="nsew")
        parent.grid_rowconfigure(6, weight=1)

        self.log_box._textbox.tag_configure("ok",   foreground="#4ade80")
        self.log_box._textbox.tag_configure("err",  foreground="#f87171")
        self.log_box._textbox.tag_configure("info", foreground="#93c5fd")
        self.log_box._textbox.tag_configure("dim",  foreground="#9ca3af")

    # ── History tab ───────────────────────────────────────────────────────────

    def _build_history_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.grid(row=0, column=0, pady=(4, 8), sticky="ew")
        top.grid_columnconfigure(0, weight=1)

        self._history_count_lbl = ctk.CTkLabel(
            top,
            text=self._history_count_text(),
            font=ctk.CTkFont(size=13),
            text_color="gray70",
            anchor="w",
        )
        self._history_count_lbl.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            top,
            text="Wyczyść historię",
            width=130,
            height=32,
            fg_color="#4a1515",
            hover_color="#6b2020",
            command=self._clear_history,
        ).grid(row=0, column=1, sticky="e")

        self._history_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._history_scroll.grid(row=1, column=0, sticky="nsew")
        self._history_scroll.grid_columnconfigure(0, weight=1)

        self._render_history()

    def _history_count_text(self) -> str:
        n = len(self._history)
        return f"{n} {'pobranie' if n == 1 else 'pobrań'} w historii"

    def _render_history(self):
        for w in self._history_scroll.winfo_children():
            w.destroy()

        if not self._history:
            ctk.CTkLabel(
                self._history_scroll,
                text="Historia jest pusta.",
                text_color="gray50",
                font=ctk.CTkFont(size=13),
            ).grid(row=0, column=0, pady=40)
            return

        for i, entry in enumerate(self._history):
            row = HistoryRow(
                self._history_scroll,
                entry,
                on_delete=self._delete_history_entry,
            )
            row.grid(row=i, column=0, pady=(0, 6), sticky="ew")

    def _delete_history_entry(self, entry: dict):
        self._history = [e for e in self._history if e is not entry]
        history_save(self._history)
        self._history_count_lbl.configure(text=self._history_count_text())
        self._render_history()

    def _clear_history(self):
        self._history = []
        history_save(self._history)
        self._history_count_lbl.configure(text=self._history_count_text())
        self._render_history()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _clear_placeholder(self, _event):
        content = self.url_box.get("1.0", "end").strip()
        if content.startswith("https://www.youtube.com/watch?v=..."):
            self.url_box.delete("1.0", "end")

    def _pick_folder(self):
        chosen = filedialog.askdirectory(
            title="Wybierz folder docelowy",
            initialdir=self._output_dir.get(),
        )
        if chosen:
            self._output_dir.set(chosen)

    def _log(self, text: str, tag: str = ""):
        self.log_box.configure(state="normal")
        if tag:
            self.log_box._textbox.insert("end", text + "\n", tag)
        else:
            self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.progress_bar.set(0)

    def _open_output(self):
        path = os.path.abspath(self._output_dir.get())
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def _set_buttons(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.download_btn.configure(state=state)

    # ── Download logic ────────────────────────────────────────────────────────

    def _start_download(self):
        raw = self.url_box.get("1.0", "end").strip()
        urls = [
            line.strip()
            for line in raw.splitlines()
            if line.strip()
            and not line.strip().startswith("#")
            and "youtube.com/watch?v=..." not in line
        ]
        if not urls:
            self._log("⚠  Brak linków do pobrania.", "err")
            return

        self._set_buttons(False)
        self.progress_bar.set(0)
        self._log(f"▶  Kolejka: {len(urls)} {'link' if len(urls)==1 else 'linków'}", "info")

        self._download_thread = threading.Thread(
            target=self._download_worker,
            args=(urls,),
            daemon=True,
        )
        self._download_thread.start()

    def _download_worker(self, urls: list[str]):
        total = len(urls)
        ok_titles = []
        skip_titles = []
        err_count = 0

        for i, url in enumerate(urls):
            self._msg_queue.put(("log", f"\n[{i+1}/{total}] {url}", "dim"))
            result, title = self._download_one(url, i, total)
            if result == "ok":
                ok_titles.append(title)
            elif result == "skip":
                skip_titles.append(title)
            else:
                err_count += 1
            self._msg_queue.put(("progress", (i + 1) / total))

        lines = ["\n─────────────────────────────────────"]
        if ok_titles:
            lines.append(f"✔  Pobrano ({len(ok_titles)}):")
            for t in ok_titles:
                lines.append(f"     • {t}")
        if skip_titles:
            lines.append(f"ℹ  Pominięto — już istnieje ({len(skip_titles)}):")
            for t in skip_titles:
                lines.append(f"     • {t}")
        if err_count:
            lines.append(f"✖  Błędy: {err_count}")
        lines.append("─────────────────────────────────────")

        tag = "ok" if not err_count else "err"
        self._msg_queue.put(("log", "\n".join(lines), tag))
        self._msg_queue.put(("done", None))

    def _download_one(self, url: str, idx: int, total: int) -> tuple:
        output_dir = self._output_dir.get()
        os.makedirs(output_dir, exist_ok=True)

        last_percent = [-1]
        q = self._msg_queue

        def progress_hook(d):
            if d["status"] == "downloading":
                pct_str = d.get("_percent_str", "").strip()
                speed = d.get("_speed_str", "?").strip()
                try:
                    pct = float(pct_str.replace("%", ""))
                except (ValueError, AttributeError):
                    return
                if int(pct) != last_percent[0]:
                    last_percent[0] = int(pct)
                    bar = "█" * int(pct / 2.5) + "░" * (40 - int(pct / 2.5))
                    q.put(("progress_line", f"  {bar} {pct:5.1f}%  {speed}"))
                    overall = (idx + pct / 100) / total
                    q.put(("progress", overall))
            elif d["status"] == "finished":
                q.put(("progress_line", "  Konwersja do MP3..."))

        ffmpeg_dir = _ffmpeg_location()
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "progress_hooks": [progress_hook],
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
            "noplaylist": True,
            "js_runtimes": {"node": {}},
            **({"ffmpeg_location": ffmpeg_dir} if ffmpeg_dir else {}),
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    q.put(("log", "  ✖  Nie można pobrać informacji o wideo.", "err"))
                    return ("err", url)

                title = info.get("title", "unknown")
                q.put(("log", f"  ♪  {title}", "info"))

                out_path = os.path.join(output_dir, f"{title}.mp3")
                if os.path.exists(out_path):
                    size_mb = os.path.getsize(out_path) / (1024 * 1024)
                    q.put(("log", f"  ℹ  Plik już istnieje, pomijam: {title}.mp3  ({size_mb:.1f} MB)", "dim"))
                    return ("skip", title)

                ydl.download([url])

            out_path = os.path.join(output_dir, f"{title}.mp3")
            size_mb = os.path.getsize(out_path) / (1024 * 1024) if os.path.exists(out_path) else 0
            q.put(("log", f"  ✔  Zapisano: {title}.mp3  ({size_mb:.1f} MB)", "ok"))
            q.put(("history_add", {"title": title, "url": url, "size_mb": size_mb, "path": out_path}))
            return ("ok", title)

        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "Private video" in msg:
                reason = "Film jest prywatny."
            elif "unavailable" in msg.lower() or "not available" in msg.lower():
                reason = "Film niedostępny."
            elif "Unsupported URL" in msg or "not a valid URL" in msg:
                reason = "Nieprawidłowy URL."
            else:
                reason = msg.split("\n")[0][:120]
            q.put(("log", f"  ✖  Błąd: {reason}", "err"))
            return ("err", url)
        except Exception as e:
            q.put(("log", f"  ✖  Nieoczekiwany błąd: {e}", "err"))
            return ("err", url)

    # ── Queue polling ─────────────────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                item = self._msg_queue.get_nowait()
                kind = item[0]

                if kind == "log":
                    _, text, tag = item
                    self._log(text, tag)

                elif kind == "progress":
                    self.progress_bar.set(item[1])

                elif kind == "progress_line":
                    self.log_box.configure(state="normal")
                    content = self.log_box._textbox.get("end-2l", "end-1c")
                    if content.startswith("  ") and ("█" in content or "░" in content or "Konwersja" in content):
                        self.log_box._textbox.delete("end-2l", "end-1c")
                    self.log_box._textbox.insert("end", item[1] + "\n", "dim")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")

                elif kind == "history_add":
                    e = item[1]
                    history_add(self._history, e["title"], e["url"], e["size_mb"], e["path"])
                    self._history_count_lbl.configure(text=self._history_count_text())
                    self._render_history()

                elif kind == "done":
                    self._set_buttons(True)
                    self.progress_bar.set(1.0)

        except queue.Empty:
            pass

        self.after(50, self._poll_queue)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
