# Setup Guide

Step-by-step instructions to get the TikTok Lebanon Comment Trend Analyzer running on Windows.

---

## 1. Prerequisites

You need:

- **Python 3.10 or newer** — check with:
  ```powershell
  python --version
  ```
  If you don't have it, install from <https://www.python.org/downloads/> (tick **"Add Python to PATH"** during install).

- **PowerShell** (already on Windows). All commands below assume PowerShell.

- About **500 MB free disk** (most is the Chromium browser Playwright downloads).

---

## 2. Create a virtual environment

From the project folder:

```powershell
cd "C:\Users\PC FACTORY\Desktop\scrape"
python -m venv .venv
```

Activate it (run this every time you open a new terminal):

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the script with an execution-policy error, run **once**:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Then re-run the `Activate.ps1` line. Your prompt should now start with `(.venv)`.

---

## 3. Install Python dependencies

```powershell
pip install -r requirements.txt
```

This installs: `playwright`, `rapidfuzz`, `pyarabic`, `pandas`, `pytest`.

---

## 4. Install the Chromium browser

Playwright needs its own copy of Chromium to drive (separate from your everyday Chrome):

```powershell
playwright install chromium
```

This downloads ~100 MB. Only needs to be done once per machine.

---

## 5. Verify everything works

Run the test suite — should report **19 passed**:

```powershell
pytest
```

Check the CLI loads:

```powershell
python -m src.cli --help
```

You should see three subcommands: `scrape`, `analyze`, `run`.

---

## 6. Scrape your TikTok profile

Start small — scrape just 3 videos first to make sure it works on your account:

```powershell
python -m src.cli scrape @your_handle --max-videos 3
```

(replace `@your_handle` with your actual TikTok username — the `@` is optional)

A Chromium window will open. Watch it:

1. Open your TikTok profile.
2. Scroll the video grid.
3. Open each video and scroll its comments.

If TikTok shows a CAPTCHA or login wall, solve it in that window — cookies are saved to `.playwright-profile/` so future runs won't ask again.

Per-video comments are written to `data/cache/<video_id>.json`.

---

## 7. Analyze the comments

```powershell
python -m src.cli analyze --username @your_handle
```

This:

- Reads every cached comment.
- Normalizes Arabic / English / Arabizi text.
- Fuzzy-matches against `data/lebanon_cities.json`.
- Writes:
  - `output/trends.csv` — ranked table (open in Excel).
  - `output/trends.json` — full structured data.
- Prints a top-10 leaderboard in the terminal.

---

## 8. Full scrape + analyze in one shot

Once you've confirmed step 6 works on a few videos, do the full run:

```powershell
python -m src.cli run @your_handle
```

Add `--max-videos 50` if you want to cap it. Already-cached videos are skipped automatically, so you can rerun this command after posting new videos and only the new ones will be scraped.

---

## 9. Adding villages

If a village you post about is missing from the ranking, add it to `data/lebanon_cities.json`:

```json
{
  "id": "your-village",
  "canonical_en": "Your Village",
  "canonical_ar": "قريتك",
  "governorate": "South",
  "aliases": ["yourvillage", "yur village", "3lt sp3lling"]
}
```

Then rerun **only** the analyze step — no re-scrape needed:

```powershell
python -m src.cli analyze --username @your_handle
```

---

## Common issues

| Problem | Fix |
|---|---|
| `python` not recognized | Reinstall Python with "Add to PATH" ticked, or use `py` instead of `python`. |
| `Activate.ps1 cannot be loaded` | Run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once. |
| CAPTCHA / "verify you're human" | Solve it in the Chromium window — cookies persist. |
| Zero comments captured | TikTok may have changed their internal API. Open DevTools on a video → Network tab → look for `comment/list` requests → share the URL pattern so the scraper can be patched. |
| Browser closes immediately | You probably passed `--headless`. Remove that flag for the first runs. |
| `ModuleNotFoundError: src` | You're not in the project root, or the venv isn't activated. `cd` into the scrape folder and re-activate. |

---

## What gets created

```
scrape/
├── .venv/                       # virtual environment (gitignored)
├── .playwright-profile/         # browser cookies (gitignored)
├── data/
│   ├── lebanon_cities.json      # YOU CAN EDIT THIS
│   └── cache/                   # scraped comments per video
└── output/
    ├── trends.csv               # ranked report
    └── trends.json              # structured report
```
