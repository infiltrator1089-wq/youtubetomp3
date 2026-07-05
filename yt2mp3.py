#!/usr/bin/env python3

import argparse
import os
import shutil
import sys
import yt_dlp


OUTPUT_DIR = "./output"

# ffmpeg shipped by winget lands outside PATH — find it automatically
_FFMPEG_WINGET = os.path.expandvars(
    r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin"
)


def _ffmpeg_location() -> str | None:
    """Return ffmpeg bin dir if not on PATH, else None (let yt-dlp auto-detect)."""
    if shutil.which("ffmpeg"):
        return None
    if os.path.isfile(os.path.join(_FFMPEG_WINGET, "ffmpeg.exe")):
        return _FFMPEG_WINGET
    return None


def make_progress_hook():
    last_percent = [-1]

    def hook(d):
        if d["status"] == "downloading":
            percent_str = d.get("_percent_str", "").strip()
            speed_str = d.get("_speed_str", "").strip()
            eta_str = d.get("_eta_str", "").strip()
            try:
                percent = float(percent_str.replace("%", ""))
            except (ValueError, AttributeError):
                return

            if int(percent) != last_percent[0]:
                last_percent[0] = int(percent)
                bar_width = 40
                filled = int(bar_width * percent / 100)
                bar = "#" * filled + "-" * (bar_width - filled)
                print(
                    f"\r  [{bar}] {percent_str:>6}  {speed_str}  ETA {eta_str}",
                    end="",
                    flush=True,
                )
        elif d["status"] == "finished":
            print(f"\r  [{'#' * 40}] 100.00%  Done.              ")

    return hook


def download_url(url: str) -> bool:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    ffmpeg_dir = _ffmpeg_location()
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(OUTPUT_DIR, "%(title)s.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "progress_hooks": [make_progress_hook()],
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        # Use Node.js as JS runtime so yt-dlp can parse YouTube properly
        "noplaylist": True,
        "js_runtimes": {"node": {}},
        **({"ffmpeg_location": ffmpeg_dir} if ffmpeg_dir else {}),
    }

    print(f"Fetching: {url}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                print(f"  Error: could not retrieve video info for {url}", file=sys.stderr)
                return False

            title = info.get("title", "unknown")
            print(f"  Title : {title}")

            out_path = os.path.join(OUTPUT_DIR, f"{title}.mp3")
            if os.path.exists(out_path):
                size_mb = os.path.getsize(out_path) / (1024 * 1024)
                print(f"  Pomijam: plik już istnieje — {out_path} ({size_mb:.1f} MB)")
                return True

            ydl.download([url])

        out_path = os.path.join(OUTPUT_DIR, f"{title}.mp3")
        if os.path.exists(out_path):
            size_mb = os.path.getsize(out_path) / (1024 * 1024)
            print(f"  Saved : {out_path} ({size_mb:.1f} MB)")
        else:
            print(f"  Saved to: {OUTPUT_DIR}/")

        return True

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "Private video" in msg:
            print(f"  Error: video is private — {url}", file=sys.stderr)
        elif "This video is not available" in msg or "unavailable" in msg.lower():
            print(f"  Error: video unavailable — {url}", file=sys.stderr)
        elif "is not a valid URL" in msg or "Unsupported URL" in msg:
            print(f"  Error: invalid or unsupported URL — {url}", file=sys.stderr)
        else:
            print(f"  Error: {msg}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  Unexpected error: {e}", file=sys.stderr)
        return False


def load_urls_from_file(path: str) -> list[str]:
    if not os.path.isfile(path):
        print(f"Error: file not found — {path}", file=sys.stderr)
        sys.exit(1)

    urls = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)

    if not urls:
        print(f"Error: no URLs found in {path}", file=sys.stderr)
        sys.exit(1)

    return urls


def main():
    parser = argparse.ArgumentParser(
        prog="yt2mp3",
        description="Download YouTube videos as MP3 files.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("url", nargs="?", help="YouTube URL to download")
    group.add_argument(
        "--file", "-f", metavar="FILE", help="Text file with one YouTube URL per line"
    )
    args = parser.parse_args()

    if args.file:
        urls = load_urls_from_file(args.file)
    else:
        urls = [args.url]

    total = len(urls)
    failed = 0

    for i, url in enumerate(urls, 1):
        if total > 1:
            print(f"\n[{i}/{total}]")
        ok = download_url(url)
        if not ok:
            failed += 1

    if total > 1:
        print(f"\nDone: {total - failed}/{total} succeeded.")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
