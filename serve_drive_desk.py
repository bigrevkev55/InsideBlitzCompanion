from __future__ import annotations

import cgi
import json
import re
import subprocess
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from season_profile_loader import parse_fac_cards, parse_team_profiles, pdf_to_text

ROOT = Path(__file__).resolve().parent
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
FAC_DECK_CACHE: list[dict[str, Any]] | None = None


class DriveDeskHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        global FAC_DECK_CACHE
        if self.path != "/api/fac-deck":
            super().do_GET()
            return
        if FAC_DECK_CACHE is None:
            try:
                FAC_DECK_CACHE = parse_fac_cards(pdf_to_text(ROOT / "FAC PDF.pdf"))
            except (OSError, ValueError, subprocess.CalledProcessError) as error:
                self.send_json(503, {"error": f"Could not read FAC PDF.pdf: {error}"})
                return
        self.send_json(200, {"cards": FAC_DECK_CACHE})

    def do_POST(self) -> None:
        if self.path != "/api/load-season":
            self.send_json(404, {"error": "Unknown endpoint."})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid upload size."})
            return
        if not 0 < length <= MAX_UPLOAD_BYTES:
            self.send_json(413, {"error": "Select a PDF smaller than 100 MB."})
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_json(400, {"error": "Choose a season PDF to upload."})
            return
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type},
        )
        upload = form["seasonFile"] if "seasonFile" in form else None
        if upload is None or not getattr(upload, "file", None):
            self.send_json(400, {"error": "Choose a season PDF to upload."})
            return
        filename = Path(getattr(upload, "filename", "season.pdf")).name
        data = upload.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            self.send_json(413, {"error": "Select a PDF smaller than 100 MB."})
            return
        if not filename.lower().endswith(".pdf") or not data.startswith(b"%PDF-"):
            self.send_json(415, {"error": "The selected file is not a valid PDF."})
            return

        source_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as source:
                source.write(data)
                source.flush()
                source_path = Path(source.name)
            extracted = pdf_to_text(source_path)
        except FileNotFoundError:
            self.send_json(503, {"error": "pdftotext is required to read this season PDF."})
            return
        except subprocess.CalledProcessError as error:
            self.send_json(422, {"error": (error.stderr or "Could not extract PDF text.")[:500]})
            return
        finally:
            if source_path:
                source_path.unlink(missing_ok=True)

        profiles = parse_team_profiles(extracted)
        if not profiles:
            self.send_json(422, {"error": "No team card headers were recognized in this PDF."})
            return

        self.send_json(200, {
            "filename": filename,
            "profiles": list(profiles.values()),
            "availableTeams": [profile["id"] for profile in profiles.values() if profile["capabilities"]["complete"]],
            "unavailableTeams": [
                {"id": profile["id"], "name": profile["name"], "season": profile["season"], "missing": profile["missing"]}
                for profile in profiles.values() if not profile["capabilities"]["complete"]
            ],
        })


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8765), DriveDeskHandler)
    print("Drive Desk: http://127.0.0.1:8765/Inside%20Blitz%20Drive%20Desk.html")
    print("Season PDFs are processed locally and discarded after extraction.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()