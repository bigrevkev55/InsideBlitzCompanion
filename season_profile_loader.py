from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

PDFTOTEXT = r"C:\Program Files\Git\mingw64\bin\pdftotext.EXE"
TEAM_HEADER = re.compile(
    r"\b((?:19|20)\d{2})\s+([A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*){0,3})\s+(?=END:|Run Pass|W L T|KT PEN|OFFENSIVE LINE|RD\s+Q)"
)
CARD_TYPE = {"RB", "QB", "WR", "TE", "FB", "K", "P"}
DEF_POSITIONS = {"LDE", "LDT", "NT", "RDT", "RDE", "LOB", "LIB", "MLB", "RIB", "ROB", "LCB", "SS", "NB", "FS", "RCB", "DE", "DT", "OLB", "ILB", "LB", "CB", "S"}
RUN_CELL = re.compile(r"^(?:-?\d+(?:/-?\d+)?|[SB](?:/-?\d+)?)$")
OUTCOME_CELL = re.compile(r"^(?:X|R|\?|PR|PX|SC|SCK|RUN|\?/|(?:X|R|PR|SC|SCK|RUN|\?)/(?:X|R|PR|SC|SCK|RUN|\?)|/(?:PR|\?))$")
PASS_HEADER = re.compile(r"(\d+)\s+(QUICK|SHORT|MEDIUM|LONG)\s+PASS")
PASS_RANGE = re.compile(r"\b(\d{1,2}-\d{1,2})\b")


def pdf_to_text(pdf_path: Path) -> str:
    result = subprocess.run(
        [PDFTOTEXT, "-table", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def discover_teams(text: str) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}
    for page in text.split("\f"):
        for season, name in TEAM_HEADER.findall(page):
            clean_name = re.sub(r"\s+", " ", name).strip()
            found[(season, clean_name.casefold())] = {"season": season, "name": clean_name}
    return sorted(found.values(), key=lambda item: (item["season"], item["name"].casefold()))


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def team_pages(text: str, season: str, name: str) -> list[str]:
    marker = re.compile(
        rf"\b{re.escape(season)}\s+{re.escape(name)}\s+(?=END:|Run Pass|W L T|KT PEN|OFFENSIVE LINE|RD\s+Q)"
    )
    return [page for page in text.split("\f") if marker.search(page)]


def card_titles(line: str) -> list[dict[str, str]]:
    if "END:" in line or re.search(r"\b(?:19|20)\d{2}\b", line) or re.search(r"\b(?:INSIDE RUN|OUTSIDE RUN|RUN PLAY)\b", line) or re.match(r"\s*[1-6]\s", line):
        return []
    words = line.split()
    titles: list[dict[str, str]] = []
    start = 0
    for index, word in enumerate(words):
        if word in CARD_TYPE:
            name = " ".join(words[start:index]).strip()
            if name and not re.fullmatch(r"\(?\d+\)?", name):
                titles.append({"name": name, "position": word})
            start = index + 1
    return titles


def parse_range(value: str) -> tuple[int, int]:
    parts = value.split("-", 1)
    start = int(parts[0])
    return start, int(parts[-1])


def row_groups(line: str, row_number: int, pattern: re.Pattern[str] = RUN_CELL) -> list[list[str]]:
    tokens = line.split()
    groups: list[list[str]] = []
    for offset in range(0, len(tokens) - 6, 7):
        if tokens[offset] == str(row_number) and all(pattern.fullmatch(cell) for cell in tokens[offset + 1:offset + 7]):
            groups.append(tokens[offset + 1:offset + 7])
    return groups


def matrix_rows(lines: list[str], start: int, count: int, pattern: re.Pattern[str] = RUN_CELL) -> list[list[list[str]]] | None:
    rows: list[list[list[str]]] = []
    for row_number in range(1, 7):
        candidates = [
            row_groups(line, row_number, pattern)
            for line in lines[start:start + 24]
            if re.match(rf"^\s*{row_number}\s", line)
        ]
        valid = next((groups for groups in candidates if len(groups) >= count), None)
        if valid is None:
            return None
        rows.append(valid[:count])
    return [[rows[row][column] for row in range(6)] for column in range(count)]


def parse_receivers(pages: list[str]) -> list[dict[str, Any]]:
    receivers: dict[tuple[str, str], dict[str, Any]] = {}
    for page in pages:
        lines = page.splitlines()
        for header_index, line in enumerate(lines):
            titles = [title for title in card_titles(line) if title["position"] in {"RB", "WR", "TE", "FB"}]
            if not titles:
                continue
            next_header = next((i for i in range(header_index + 1, len(lines)) if card_titles(lines[i])), len(lines))
            section = lines[header_index + 1:next_header]
            for title in titles:
                receivers.setdefault((title["name"], title["position"]), {
                    "name": title["name"], "type": title["position"], "ranges": {}, "catches": {}, "average": {}
                })
            for heading in section:
                matches = list(PASS_HEADER.finditer(heading))
                if not matches:
                    continue
                ranges = PASS_RANGE.findall(heading)
                for index, match in enumerate(matches):
                    if index >= len(titles) or index >= len(ranges):
                        continue
                    receiver = receivers[(titles[index]["name"], titles[index]["position"])]
                    depth = match.group(2).title()
                    receiver["catches"][depth] = int(match.group(1))
                    receiver["ranges"][depth] = list(parse_range(ranges[index]))
            summary_index = next((i for i, item in enumerate(section) if re.search(r"REC\s+YDS\s+AVG\s+TD", item)), None)
            if summary_index is not None:
                values_line = next((item for item in section[summary_index + 1:] if item.split()), "")
                tokens = values_line.split()
                offset = 0
                for title in titles:
                    width = 7 if title["position"] in {"RB", "FB"} else 6
                    if len(tokens) < offset + 3:
                        break
                    try:
                        average = float(tokens[offset + 2])
                    except ValueError:
                        offset += width
                        continue
                    receiver = receivers[(title["name"], title["position"])]
                    for depth in receiver["ranges"]:
                        receiver["average"][depth] = average
                    offset += width
    return [receiver for receiver in receivers.values() if receiver["ranges"]]


def outcome_groups(line: str, row_number: int, count: int) -> list[list[str]]:
    tokens = line.split()
    groups: list[list[str]] = []
    for offset, token in enumerate(tokens):
        if token != str(row_number):
            continue
        cells: list[str] = []
        for candidate in tokens[offset + 1:]:
            if len(cells) == 6 or not OUTCOME_CELL.fullmatch(candidate):
                break
            cells.append(candidate)
        if cells:
            cells.extend([""] * (6 - len(cells)))
            groups.append(cells)
            if len(groups) == count:
                break
    return groups


def parse_pass_matrix(lines: list[str], heading_index: int, count: int) -> list[list[list[str]]] | None:
    rows: list[list[list[str]]] = []
    for row_number in range(1, 7):
        candidates = [
            outcome_groups(line, row_number, count)
            for line in lines[heading_index + 1:heading_index + 16]
            if re.match(rf"^\s*{row_number}\s", line)
        ]
        valid = next((groups for groups in candidates if len(groups) == count), None)
        if valid is None:
            return None
        rows.append(valid)
    return [[rows[row][card] for row in range(6)] for card in range(count)]


def split_pass_pair(value: str) -> tuple[str, str]:
    if "/" not in value:
        return value, value
    left, right = value.split("/", 1)
    return left, right


def parse_quarterbacks(pages: list[str]) -> list[dict[str, Any]]:
    quarterbacks: dict[str, dict[str, Any]] = {}
    for page in pages:
        lines = page.splitlines()
        for header_index, line in enumerate(lines):
            titles = [title for title in card_titles(line) if title["position"] == "QB"]
            if not titles:
                continue
            qbs = [quarterbacks.setdefault(title["name"], {
                "name": title["name"], "quick": [[""] * 6 for _ in range(6)],
                "short": [[""] * 6 for _ in range(6)], "medium": [[""] * 6 for _ in range(6)],
                "long": [[""] * 6 for _ in range(6)], "sackRoll": [1, 5], "scrambleRoll": [5, 6]
            }) for title in titles]
            for heading_index in range(header_index + 1, len(lines)):
                heading = lines[heading_index]
                if "QUICK PASS (" not in heading:
                    continue
                quick_matrices = parse_pass_matrix(lines, heading_index, len(qbs))
                if quick_matrices:
                    for qb_index, matrix in enumerate(quick_matrices):
                        for row in range(6):
                            for col in range(6):
                                quick, short = split_pass_pair(matrix[row][col])
                                qbs[qb_index]["quick"][row][col] = quick
                                qbs[qb_index]["short"][row][col] = short
                medium_heading = next((i for i in range(heading_index + 1, len(lines)) if "MEDIUM PASS (" in lines[i]), None)
                if medium_heading is not None:
                    medium_matrices = parse_pass_matrix(lines, medium_heading, len(qbs))
                    if medium_matrices:
                        for qb_index, matrix in enumerate(medium_matrices):
                            for row in range(6):
                                for col in range(6):
                                    medium, long = split_pass_pair(matrix[row][col])
                                    qbs[qb_index]["medium"][row][col] = medium
                                    qbs[qb_index]["long"][row][col] = long
                break
    return list(quarterbacks.values())


def parse_defenders(pages: list[str], season: str, team_name: str) -> list[dict[str, Any]]:
    position_pattern = "|".join(sorted(DEF_POSITIONS, key=len, reverse=True))
    entry = re.compile(
        rf"\b({position_pattern})\s+([A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*)*?)\s+\(\d+\)\s+"
        r"(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+(?:\(\d+\))?)\s+(\d+)\s+(\d+)"
    )
    found: dict[str, dict[str, Any]] = {}
    for page in pages:
        if "STARTERS" not in page or not re.search(rf"{re.escape(season)}\s+{re.escape(team_name)}\s+RD\s+Q", page):
            continue
        for line in page.splitlines():
            for match in entry.finditer(line):
                position, raw_name, rd, quick, short, medium, long, pr, interception, returned = match.groups()
                name = re.sub(r"\s+", " ", raw_name).strip()
                pieces = name.split()
                if pieces and pieces[0] in DEF_POSITIONS:
                    position = pieces[0]
                    name = " ".join(pieces[1:])
                if not name or name in found:
                    continue
                group = "front" if position in {"LDE", "LDT", "NT", "RDT", "RDE", "DE", "DT"} else "linebacker" if position in {"LOB", "LIB", "MLB", "RIB", "ROB", "OLB", "ILB", "LB"} else "secondary"
                found[name] = {
                    "name": name, "position": position, "group": group,
                    "rd": int(rd), "q": int(quick), "s": int(short), "m": int(medium), "l": int(long),
                    "pr": int(re.match(r"\d+", pr).group()),
                    "int": int(re.match(r"\d+", interception).group()), "ret": int(returned),
                }
    return list(found.values())


def parse_run_cards(pages: list[str]) -> list[dict[str, Any]]:
    cards: dict[tuple[str, int, int], dict[str, Any]] = {}
    for page in pages:
        lines = page.splitlines()
        for heading_index, heading in enumerate(lines):
            section_match = re.search(r"(INSIDE RUN|OUTSIDE RUN|RUN PLAY)\s+(\d+(?:-\d+)?)", heading)
            if not section_match:
                continue
            section = section_match.group(1)
            if section == "OUTSIDE RUN":
                prior_inside = next((index for index in range(heading_index - 1, -1, -1) if "INSIDE RUN" in lines[index]), None)
                header_candidates = lines[max(0, (prior_inside or 0) - 4):prior_inside] if prior_inside is not None else []
                header_line = next((candidate for candidate in reversed(header_candidates) if card_titles(candidate)), "")
                range_line = lines[prior_inside] if prior_inside is not None else heading
            else:
                header_line = next(
                    (candidate for candidate in reversed(lines[max(0, heading_index - 4):heading_index]) if card_titles(candidate)),
                    "",
                )
                range_line = heading
            titles = card_titles(header_line)
            ranges = re.findall(r"(?:INSIDE RUN|OUTSIDE RUN|RUN PLAY)\s+(\d+(?:-\d+)?)", range_line)
            count = min(len(titles), len(ranges))
            if not count:
                continue
            matrices = matrix_rows(lines, heading_index + 1, count)
            if matrices is None:
                continue
            for card_index, card_range in enumerate(ranges[:count]):
                low, high = parse_range(card_range)
                title = titles[card_index]
                key = (title["name"], low, high)
                card = cards.setdefault(key, {
                    "name": title["name"], "type": title["position"], "start": low, "end": high,
                    "long": None, "fumbles": None, "inside": None, "outside": None,
                })
                if section == "RUN PLAY":
                    card["inside"] = matrices[card_index]
                    card["outside"] = matrices[card_index]
                else:
                    card["inside" if section == "INSIDE RUN" else "outside"] = matrices[card_index]

        for stats_index, line in enumerate(lines):
            if not re.search(r"ATT\s+YDS\s+AVG\s+TD\s+LNG\b", line):
                continue
            first_match = re.search(r"ATT\s+YDS\s+AVG\s+TD\s+LNG\b", line)
            columns = [column for column in re.finditer(r"\b(ATT|YDS|AVG|TD|LNG|BLK|FUM)\b", line) if column.start() >= first_match.start()]
            group_starts = [index for index, column in enumerate(columns) if column.group(1) == "ATT"]
            groups = [
                columns[start:group_starts[position + 1] if position + 1 < len(group_starts) else len(columns)]
                for position, start in enumerate(group_starts)
            ]

            # Cards without a BLK column (QB/WR/TE) tell the title line above from the one below.
            def compatible(candidate: list[dict[str, str]]) -> bool:
                return len(candidate) >= len(groups) and all(
                    ("BLK" in [column.group(1) for column in group]) == (title["position"] in {"RB", "FB"})
                    for title, group in zip(candidate, groups)
                )

            before = next((card_titles(candidate) for candidate in reversed(lines[:stats_index]) if card_titles(candidate)), [])
            after = next((card_titles(candidate) for candidate in lines[stats_index + 1:stats_index + 6] if card_titles(candidate)), [])
            titles = before if compatible(before) or not compatible(after) else after

            value_tokens: list[re.Match[str]] = []
            for value_line in lines[stats_index + 1:stats_index + 4]:
                if not value_line.strip():
                    continue
                value_line = " " * first_match.start() + value_line[first_match.start():columns[-1].end() + 3]
                if not re.fullmatch(r"[\d\s./+\-]+", value_line):
                    break
                value_tokens.extend(re.finditer(r"\S+", value_line))
            centers = [(column.start() + column.end()) / 2 for column in columns]
            assigned: dict[int, str] = {}
            for token in value_tokens:
                center = (token.start() + token.end()) / 2
                nearest = min(range(len(columns)), key=lambda index: abs(centers[index] - center))
                assigned.setdefault(nearest, token.group())

            for card_index, title in enumerate(titles[:len(groups)]):
                matching = [card for card in cards.values() if card["name"] == title["name"]]
                if not matching:
                    continue
                offset = group_starts[card_index]
                labels = {column.group(1): assigned.get(offset + position) for position, column in enumerate(groups[card_index])}
                try:
                    long_value, fumbles = int(labels["LNG"]), int(labels["FUM"])
                except (KeyError, TypeError, ValueError):
                    continue
                for card in matching:
                    card["long"], card["fumbles"] = long_value, fumbles

    return [card for card in cards.values() if card["inside"] and card["outside"]]


def _row_groups(line: str, row_label: str, pattern: re.Pattern[str]) -> list[list[str]]:
    raw_tokens = line.split()
    tokens: list[str] = []
    index = 0
    while index < len(raw_tokens):
        if raw_tokens[index] == "TB" and index + 1 < len(raw_tokens) and raw_tokens[index + 1] in {"+", "*"}:
            tokens.append("TB" + raw_tokens[index + 1])
            index += 2
        else:
            tokens.append(raw_tokens[index])
            index += 1
    groups: list[list[str]] = []
    for offset, token in enumerate(tokens):
        if token != row_label:
            continue
        cells = tokens[offset + 1:offset + 7]
        if len(cells) == 6 and all(pattern.fullmatch(cell) for cell in cells):
            groups.append(cells)
    return groups


def parse_special_teams(pages: list[str]) -> dict[str, Any]:
    cell_pattern = re.compile(r"(?:TB[+*]?|OB|\d+[?n/]?\d?[+*]?|\d+n[+*]?)$")
    return_cell = re.compile(r"(?:-?\d+|TD)/-?\d+")
    number_cell = re.compile(r"\d+")
    result: dict[str, Any] = {"kicker": None, "punter": None, "puntReturners": []}
    for page in pages:
        lines = page.splitlines()
        card_line = next((line for line in lines if any(title["position"] in {"K", "P"} for title in card_titles(line))), "")
        titles = card_titles(card_line)
        kicker = next((title for title in titles if title["position"] == "K"), None)
        punter = next((title for title in titles if title["position"] == "P"), None)
        if kicker and punter:
            fg_index = next((i for i, line in enumerate(lines) if "FIELD GOALS" in line), None)
            inside_index = next((i for i, line in enumerate(lines) if "50 YD LINE AND CLOSER" in line), None)
            outside_index = next((i for i, line in enumerate(lines) if "OUTSIDE 50 YD LINE" in line), None)
            field_goals: list[list[int]] = []
            if fg_index is not None:
                for row in range(1, 7):
                    values = next((
                        _row_groups(line, str(row), number_cell)[0]
                        for line in lines[fg_index + 1:]
                        if line.split()[:1] == [str(row)]
                        and len(_row_groups(line, str(row), cell_pattern)) >= 2
                        and _row_groups(line, str(row), number_cell)
                    ), None)
                    if values is None:
                        field_goals = []
                        break
                    field_goals.append([int(value) for value in values])

            def punt_matrix(start: int | None, end: int) -> list[list[str]]:
                if start is None:
                    return []
                rows: list[list[str]] = []
                for row in range(1, 7):
                    candidates = next((
                        _row_groups(line, str(row), cell_pattern)
                        for line in lines[start:end]
                        if line.split()[:1] == [str(row)] and len(_row_groups(line, str(row), cell_pattern)) >= 2
                    ), [])
                    if len(candidates) < 2:
                        return []
                    rows.append(candidates[1])
                return rows

            outside_punts = punt_matrix(outside_index, fg_index if fg_index is not None else len(lines))
            inside_punts = punt_matrix(inside_index, len(lines))
            if len(field_goals) == 6:
                result["kicker"] = {"name": kicker["name"], "fieldGoalTable": field_goals}
            if len(outside_punts) == 6 and len(inside_punts) == 6:
                result["punter"] = {
                    "name": punter["name"], "outsideFifty": outside_punts, "insideFifty": inside_punts
                }

        return_headers: list[tuple[int, re.Match[str]]] = []
        label_line = next((line for line in lines if "Punt Return" in line), "")
        punt_col = max(0, label_line.find("Punt Return") - 6) if label_line else 0
        kick_col = label_line.find("Kick Return") - 6 if "Kick Return" in label_line else 10**6
        for line_index, line in enumerate(lines):
            if re.match(r"\s*(?:EXTRA POINTS|FIELD GOALS)", line) or "50 YD LINE AND CLOSER" in line:
                continue
            if "Punt Return" not in line and not re.search(r"[A-Z][A-Z .'-]+\s+\d{1,2}-\d{1,2}", line):
                continue
            matches = list(re.finditer(r"\b([A-Z][A-Z .'-]{1,35}?)\s+(\d{1,2}-\d{1,2})\b", line))
            matches = [match for match in matches if len(match.group(1).split()) > 1 and match.group(1).strip() not in {"EXTRA POINTS", "TB"}]
            matches = [match for match in matches if punt_col <= match.start(1) < kick_col]
            if matches and any(title["position"] == "P" for title in titles):
                return_headers.append((line_index, matches[0]))
        for header_index, match in return_headers:
            low, high = parse_range(match.group(2))
            rows: list[list[str]] = []
            for row_label in ("1-2", "3-4", "5-6"):
                groups = [
                    group for line in lines[header_index + 1:header_index + 15]
                    for group in _row_groups(line, row_label, return_cell)
                ]
                if not groups:
                    rows = []
                    break
                rows.append(groups[0])
            if len(rows) != 3:
                continue
            end_index = next((index for index, _ in return_headers if index > header_index), len(lines))
            fair_catch = next((int(value) for line in lines[header_index:end_index] for value in re.findall(r"FC\?\s*(\d+)", line)), None)
            result["puntReturners"].append({
                "name": re.sub(r"\s+", " ", match.group(1)).title(),
                "start": low, "end": high, "fairCatch": fair_catch, "table": rows,
            })
    return result


def parse_team_stats(pages: list[str]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for page in pages:
        lines = page.splitlines()
        record_header = next((i for i, line in enumerate(lines) if re.search(r"W\s+L\s+T\s+PF\s+PA", line)), None)
        if record_header is not None:
            values = next((
                tuple(map(int, match.groups()))
                for line in lines[record_header + 1:record_header + 4]
                for match in re.finditer(r"\b(\d{1,2})\s+(\d{1,2})\s+([01])\s+(\d{2,4})\s+(\d{2,4})\b", line)
            ), None)
            if values:
                wins, losses, ties, points_for, points_against = values
                stats.update({"record": f"{wins}-{losses}-{ties}", "pointsFor": points_for, "pointsAgainst": points_against})
        pass_header = next((i for i, line in enumerate(lines) if re.search(r"ATT\s+CMP\s+YDS\s+TD\s+INT\s+SCK\s+FUM", line)), None)
        if pass_header is not None:
            values_line = next((line for line in lines[pass_header + 1:pass_header + 4] if line.split()), "")
            values = values_line.split()
            if len(values) >= 3 and all(re.fullmatch(r"\d+", value) for value in values[:3]):
                stats.update({"passAttempts": int(values[0]), "completions": int(values[1]), "passYards": int(values[2])})
    return stats


def parse_team_indexes(pages: list[str]) -> dict[str, int | None]:
    offensive_page = next((page for page in pages if "OFFENSIVE LINE" in page), "")
    week_twelve = next((line for line in offensive_page.splitlines() if re.search(r"\bWeek\s+12\b", line)), "")
    offensive_token = week_twelve.split()[-1] if week_twelve else ""
    offense = int(offensive_token) if re.fullmatch(r"[+-]?\d+", offensive_token) and -20 <= int(offensive_token) <= 20 else None

    defensive_line = next((line for page in pages for line in page.splitlines() if "DEF FR" in line), "")
    match = re.search(r"\bDEF FR\s+\d+-\d+\s+RUN\s+-?\d+\s+\d+\s+RUN\s+([+-]?\d+)\b", defensive_line)
    defense = int(match.group(1)) if match and -20 <= int(match.group(1)) <= 20 else None
    return {"offense": offense, "defense": defense}


def parse_team_profiles(text: str) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for team in discover_teams(text):
        pages = team_pages(text, team["season"], team["name"])
        defenders = parse_defenders(pages, team["season"], team["name"])
        run_cards = parse_run_cards(pages)
        receivers = parse_receivers(pages)
        quarterbacks = parse_quarterbacks(pages)
        special_teams = parse_special_teams(pages)
        stats = parse_team_stats(pages)
        indexes = parse_team_indexes(pages)
        quarterback = quarterbacks[0] if quarterbacks else None
        pass_depths = ("Quick", "Short", "Medium", "Long")
        matrix_ok = lambda matrix: len(matrix) == 6 and all(len(row) == 6 for row in matrix)
        capabilities = {
            "defense": bool(defenders),
            "runCards": bool(run_cards) and all(card["long"] is not None and card["fumbles"] is not None for card in run_cards),
            "receivers": bool(receivers) and all(
                receiver["ranges"] and receiver["catches"]
                and all(depth in receiver["average"] for depth in receiver["ranges"])
                for receiver in receivers
            ) and all(any(depth in receiver["ranges"] for receiver in receivers) for depth in pass_depths),
            "quarterback": quarterback is not None and all(matrix_ok(quarterback[depth]) for depth in ("quick", "short", "medium", "long")),
            "kicker": special_teams["kicker"] is not None,
            "punter": special_teams["punter"] is not None,
            "puntReturners": bool(special_teams["puntReturners"]) and all(isinstance(player["fairCatch"], int) for player in special_teams["puntReturners"]),
            "stats": all(key in stats for key in ("record", "pointsFor", "passAttempts", "completions", "passYards")),
            "indexes": all(isinstance(indexes[key], int) for key in ("offense", "defense")),
        }
        capabilities["complete"] = all(capabilities.values())
        missing = [name for name, supported in capabilities.items() if name != "complete" and not supported]
        summary = f"Parsed from PDF: {len(run_cards)} run cards, {len(receivers)} receivers, {len(defenders)} defenders."
        profiles[f"{team['season']}-{slug(team['name'])}"] = {
            "id": f"{team['season']}-{slug(team['name'])}",
            "name": team["name"], "season": team["season"],
            "abbreviation": slug(team["name"]).replace("-", "")[:3].upper(),
            "stats": stats, "summary": summary,
            "indexes": indexes,
            "defense": {"players": defenders},
            "offense": {"runCards": run_cards, "receivers": receivers, "quarterback": quarterback},
            "specialTeams": special_teams,
            "sourcePages": len(pages),
            "capabilities": capabilities, "missing": missing,
        }
    return profiles


def parse_fac_cards(text: str) -> list[dict[str, Any]]:
    cards: dict[int, dict[str, Any]] = {}
    header_pattern = re.compile(r"(?<!\S)(\d{1,2})\s+Key\b")
    for page in text.split("\f"):
        lines = page.splitlines()
        sections: list[tuple[int, list[re.Match[str]]]] = []
        for line_index, line in enumerate(lines):
            matches = [match for match in header_pattern.finditer(line) if 1 <= int(match.group(1)) <= 82]
            if matches:
                sections.append((line_index, matches))
        for section_index, (start_line, matches) in enumerate(sections):
            next_line = sections[section_index + 1][0] if section_index + 1 < len(sections) else min(len(lines), start_line + 24)
            starts = [match.start(1) for match in matches]
            gaps = [right - left for left, right in zip(starts, starts[1:]) if right > left]
            column_width = round(sum(gaps) / len(gaps)) if gaps else 29
            for card_index, match in enumerate(matches):
                number = int(match.group(1))
                column_start = starts[card_index]
                column_end = starts[card_index + 1] if card_index + 1 < len(starts) else column_start + column_width
                content = "\n".join(
                    line[column_start:column_end].rstrip()
                    for line in lines[start_line:next_line]
                    if line[column_start:column_end].strip()
                ).strip()
                if content:
                    cards[number] = {"number": number, "content": content}
    missing = sorted(set(range(1, 83)) - cards.keys())
    if missing:
        raise ValueError(f"FAC PDF is missing numbered cards: {', '.join(map(str, missing))}")
    special = parse_special_fac_cards(text)
    return [cards[number] for number in range(1, 83)] + special


def parse_special_fac_cards(text: str) -> list[dict[str, Any]]:
    """Penalty and fumble cards, numbered 83-100; strategy cards are skipped."""
    token = re.compile(r"(?<!\S)(8[3-9]|9\d|100)(?!\S)")
    header_any = re.compile(r"(?<!\S)(?:\d{1,3}\s+Key\b|8[3-9](?!\S)|9\d(?!\S)|100(?!\S))")
    found: dict[int, str] = {}
    for page in text.split("\f"):
        lines = page.splitlines()
        for line_index, line in enumerate(lines):
            matches = list(token.finditer(line))
            if not matches:
                continue
            starts = sorted({match.start() for match in header_any.finditer(line)} | {match.start() for match in re.finditer(r"(?<!\S)\d{1,3}(?=\s+Key\b)", line)})
            end_line = next((index for index in range(line_index + 1, len(lines)) if header_any.search(lines[index])), min(len(lines), line_index + 24))
            for match in matches:
                number = int(match.group(1))
                column_start = match.start()
                later = [start for start in starts if start > column_start]
                # Strategy cards sit to the right of the numbered cards on the same row.
                strategy = re.search(r"\b(?:NO STRATEGY|RUN KEY|RUN NO KEY|RUN / WRONG|BLITZ|PASS)\b", line[column_start:])
                limits = later + ([column_start + strategy.start()] if strategy and column_start + strategy.start() > column_start else [])
                column_end = min(limits) if limits else column_start + 30
                content_lines: list[str] = []
                for segment in (item[column_start:column_end] for item in lines[line_index + 1:end_line]):
                    if re.search(r"\bDEF\s+OFF\b|\bKEY\b|\bBLITZ\b", segment):
                        break
                    if re.match(r"\s*(?:Runs?|Quick|Short|Medium|Long|Pass)\b", segment):
                        continue
                    if segment.strip():
                        text_part = re.split(r"\s{3,}", segment.strip())[0]
                        if len(text_part) > 4:
                            content_lines.append(re.sub(r"\s+", " ", text_part))
                content = "\n".join(content_lines)
                if content and ("PENALTY" in content or "FUMBLE" in content) and number not in found:
                    found[number] = content
    return [{"number": number, "content": found[number], "special": True} for number in sorted(found)]
