# Inside Blitz Companion

A browser-based drive desk for the Inside Blitz football tabletop game. It simulates drives using team cards from a season PDF and the FAC deck, tracks score, clock, timeouts and a drive ledger, and handles end-of-half and end-of-game situations (hurry-up, kneel-downs, timeouts, late field goals, overtime).

## Requirements

- Python 3.9+
- `pdftotext` (Poppler). `season_profile_loader.py` expects it at `C:\Program Files\Git\mingw64\bin\pdftotext.EXE`; edit `PDFTOTEXT` there if yours is elsewhere.
- Your own copies of the game files (not included in this repo):
  - `FAC PDF.pdf` in this folder (the FAC deck)
  - A season PDF such as `IB 2009 NFL.pdf`, uploaded from the app

## Run

On Windows, double-click `Start Inside Blitz Drive Desk.bat`, or run:

```
python serve_drive_desk.py
```

Then open http://127.0.0.1:8765/Inside%20Blitz%20Drive%20Desk.html.

## Use

1. Load a season PDF and pick two teams with complete profiles.
2. Start a new game, or start from an in-progress board state.
3. Simulate drives or record them manually. See `Inside Blitz Drive Desk Guide.html` for details.

## Files

- `Inside Blitz Drive Desk.html` - the app
- `serve_drive_desk.py` - local server and PDF upload API
- `season_profile_loader.py` - parses season and FAC PDFs into team profiles
- `Inside Blitz Drive Desk Guide.html` - user guide
