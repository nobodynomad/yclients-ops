#!/usr/bin/env python3
"""Build the Google-Sheets-only combined `Общее` tab from all monthly tabs.

This script intentionally does not read YCLIENTS, local audit checkpoints, or
sales exports. The monthly tabs in the main workbook are its only data source.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ROOT = Path(os.environ.get("YCLIENTS_OPS_HOME", Path(__file__).resolve().parents[1]))
SID = os.environ.get("GOOGLE_SHEETS_ID", "")
TOKEN = os.environ.get("GOOGLE_TOKEN_FILE", str(ROOT / "secrets/google_token.json"))
TARGET = "Общее"
SUMMARY_PATH = ROOT / "runtime/overall_build_summary.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

MONTH_NUM = {
    "Январь": 1,
    "Февраль": 2,
    "Март": 3,
    "Апрель": 4,
    "Май": 5,
    "Июнь": 6,
    "Июль": 7,
    "Август": 8,
    "Сентябрь": 9,
    "Октябрь": 10,
    "Ноябрь": 11,
    "Декабрь": 12,
}
MONTH_RE = re.compile(r"^(" + "|".join(MONTH_NUM) + r")\s+(20\d{2})$")
ALLOWED_STATUSES = {
    "Активирован",
    "Просрочен",
    "Исчерпан",
    "Обнулен",
    "Абонемента нет",
}
HEADERS = [
    "Месяц",
    "Тип блока",
    "Почта",
    "Курс",
    "Дата покупки",
    "Дата окончания абонемента",
    "Статус",
    "Групп",
    "Инди",
    "Отходили групп",
    "Отходили инди",
    "Осталось групп",
    "Осталось инди",
    "Просрочилось групп",
    "Просрочилось инди",
    "Уменьшили групп",
    "Прибавили групп",
    "Уменьшили инди",
    "Прибавили инди",
]


def get(row, col, default=""):
    return row[col] if col < len(row) else default


def normalize_date(raw, rendered, required=False):
    if raw in (None, "") and rendered in (None, ""):
        if required:
            raise ValueError("required date is blank")
        return "", ""
    text = str(rendered or raw).strip().split()[0]
    dt = datetime.strptime(text, "%d.%m.%Y")
    # Google Sheets serial-date epoch. Writing the serial with RAW keeps a real
    # date value while the format below guarantees date-only display.
    serial = (dt.date() - datetime(1899, 12, 30).date()).days
    return serial, text


def monthly_sort_key(title):
    m = MONTH_RE.fullmatch(title)
    if not m:
        raise ValueError(title)
    return int(m.group(2)), MONTH_NUM[m.group(1)]


def parse_notes(service, month_titles):
    ranges = [f"'{title}'!A1:Q200" for title in month_titles]
    response = service.spreadsheets().get(
        spreadsheetId=SID,
        ranges=ranges,
        includeGridData=True,
        fields="sheets(properties(title),data(startRow,startColumn,rowData(values(note))))",
    ).execute()
    result = defaultdict(dict)
    for sheet in response.get("sheets", []):
        title = sheet["properties"]["title"]
        for block in sheet.get("data", []):
            start_row = block.get("startRow", 0)
            start_col = block.get("startColumn", 0)
            for r_offset, row_data in enumerate(block.get("rowData", [])):
                texts = []
                for c_offset, cell in enumerate(row_data.get("values", [])):
                    note = cell.get("note")
                    if note and note.strip():
                        texts.append((start_col + c_offset + 1, note.strip()))
                if texts:
                    result[title][start_row + r_offset + 1] = texts
    return result


def combine(service, month_titles):
    ranges = [f"'{title}'!A1:Q200" for title in month_titles]
    raw_ranges = service.spreadsheets().values().batchGet(
        spreadsheetId=SID,
        ranges=ranges,
        valueRenderOption="UNFORMATTED_VALUE",
        dateTimeRenderOption="SERIAL_NUMBER",
    ).execute()["valueRanges"]
    rendered_ranges = service.spreadsheets().values().batchGet(
        spreadsheetId=SID,
        ranges=ranges,
        valueRenderOption="FORMATTED_VALUE",
    ).execute()["valueRanges"]
    notes = parse_notes(service, month_titles)

    combined = []
    combined_notes = {}
    counts = {}
    source_ids = set()
    status_counts = Counter()
    source_errors = []

    for title, raw_vr, fmt_vr in zip(month_titles, raw_ranges, rendered_ranges):
        raw = raw_vr.get("values", [])
        fmt = fmt_vr.get("values", [])
        max_rows = max(len(raw), len(fmt))
        raw += [[] for _ in range(max_rows - len(raw))]
        fmt += [[] for _ in range(max_rows - len(fmt))]

        package_title = next(
            (i for i, row in enumerate(fmt, 1) if str(get(row, 0)).strip().lower() == "пакет конс"),
            None,
        )
        if package_title is None:
            raise RuntimeError(f"{title}: package title not found")
        total_rows = [
            i for i, row in enumerate(fmt, 1)
            if str(get(row, 0)).strip().lower() == "итого"
        ]
        main_total = next((i for i in total_rows if i < package_title), None)
        package_total = next((i for i in total_rows if i > package_title), None)
        if not main_total or not package_total:
            raise RuntimeError(f"{title}: semantic totals not found")

        main_source_rows = list(range(2, main_total))
        package_source_rows = list(range(package_title + 2, package_total))
        counts[title] = {"Основной": len(main_source_rows), "Пакет": len(package_source_rows)}

        for block_type, source_rows in (
            ("Основной", main_source_rows),
            ("Пакет", package_source_rows),
        ):
            for source_row in source_rows:
                source_id = (title, block_type, source_row)
                if source_id in source_ids:
                    raise AssertionError(f"duplicate source identity: {source_id}")
                source_ids.add(source_id)
                rr = raw[source_row - 1]
                fr = fmt[source_row - 1]
                email = str(get(fr, 0)).strip()
                course = str(get(fr, 1)).strip()
                status = str(get(fr, 4)).strip()
                if not course:
                    source_errors.append((title, source_row, "blank course"))
                if status not in ALLOWED_STATUSES:
                    source_errors.append((title, source_row, f"invalid status {status!r}"))
                purchase_serial, purchase_text = normalize_date(get(rr, 2), get(fr, 2), required=True)
                expiry_serial, expiry_text = normalize_date(get(rr, 3), get(fr, 3), required=False)
                expected_year, expected_month = monthly_sort_key(title)
                purchase_dt = datetime.strptime(purchase_text, "%d.%m.%Y")
                if (purchase_dt.year, purchase_dt.month) != (expected_year, expected_month):
                    source_errors.append((title, source_row, f"purchase date outside month: {purchase_text}"))

                if block_type == "Основной":
                    values = [
                        title, block_type, email, course, purchase_serial, expiry_serial, status,
                        get(rr, 5), get(rr, 6), get(rr, 7), get(rr, 8), get(rr, 9), get(rr, 10),
                        get(rr, 11), get(rr, 12), get(rr, 13), get(rr, 14), get(rr, 15), get(rr, 16),
                    ]
                else:
                    # Package rows have the approved individual-only A:I schema.
                    # Group quantities are explicit zeroes; manual-change fields are
                    # blank because these columns do not apply to the package block.
                    values = [
                        title, block_type, email, course, purchase_serial, expiry_serial, status,
                        0, get(rr, 5), 0, get(rr, 6), 0, get(rr, 7), 0, get(rr, 8), "", "", "", "",
                    ]
                if len(values) != len(HEADERS):
                    raise AssertionError((title, source_row, len(values)))
                combined.append(values)
                output_row = len(combined) + 1
                row_notes = notes.get(title, {}).get(source_row, [])
                if row_notes:
                    combined_notes[output_row] = "\n\n".join(
                        f"Исходное примечание ({title}, колонка {col}):\n{text}"
                        for col, text in row_notes
                    )
                status_counts[status] += 1

    if source_errors:
        raise RuntimeError(f"source validation errors: {source_errors[:20]}")
    expected = sum(sum(v.values()) for v in counts.values())
    if len(combined) != expected or len(source_ids) != expected:
        raise AssertionError((len(combined), len(source_ids), expected))
    return combined, combined_notes, counts, dict(status_counts)


def ensure_target_sheet(service, required_rows):
    meta = service.spreadsheets().get(
        spreadsheetId=SID,
        fields="sheets.properties",
    ).execute()["sheets"]
    existing = next((s["properties"] for s in meta if s["properties"]["title"] == TARGET), None)
    row_count = max(required_rows + 100, 1200)
    if existing:
        sheet_id = existing["sheetId"]
        requests = [
            {"clearBasicFilter": {"sheetId": sheet_id}},
            {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"rowCount": row_count, "columnCount": len(HEADERS), "frozenRowCount": 1}}, "fields": "gridProperties(rowCount,columnCount,frozenRowCount)"}},
            {"repeatCell": {"range": {"sheetId": sheet_id}, "cell": {"note": "", "userEnteredFormat": {}}, "fields": "note,userEnteredFormat"}},
        ]
        service.spreadsheets().batchUpdate(spreadsheetId=SID, body={"requests": requests}).execute()
        service.spreadsheets().values().clear(spreadsheetId=SID, range=f"'{TARGET}'!A:Z", body={}).execute()
        return sheet_id, False
    reply = service.spreadsheets().batchUpdate(
        spreadsheetId=SID,
        body={"requests": [{"addSheet": {"properties": {"title": TARGET, "gridProperties": {"rowCount": row_count, "columnCount": len(HEADERS), "frozenRowCount": 1}}}}]},
    ).execute()
    return reply["replies"][0]["addSheet"]["properties"]["sheetId"], True


def write_target(service, sheet_id, rows, row_notes):
    values = [HEADERS] + rows
    service.spreadsheets().values().update(
        spreadsheetId=SID,
        range=f"'{TARGET}'!A1:S{len(values)}",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    white = {"red": 1, "green": 1, "blue": 1}
    dark_green = {"red": 0.106, "green": 0.369, "blue": 0.125}
    yellow = {"red": 1, "green": 0.949, "blue": 0.6}
    red = {"red": 1, "green": 0.8, "blue": 0.8}
    border = {"style": "SOLID", "color": {"red": 0.86, "green": 0.86, "blue": 0.86}}
    requests = [
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": len(values), "startColumnIndex": 0, "endColumnIndex": len(HEADERS)}, "cell": {"userEnteredFormat": {"backgroundColor": white, "textFormat": {"fontFamily": "Arial", "fontSize": 10, "foregroundColor": {"red": 0, "green": 0, "blue": 0}}, "verticalAlignment": "MIDDLE", "borders": {"top": border, "bottom": border, "left": border, "right": border}}}, "fields": "userEnteredFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": len(HEADERS)}, "cell": {"userEnteredFormat": {"backgroundColor": dark_green, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP", "textFormat": {"fontFamily": "Arial", "fontSize": 10, "bold": True, "foregroundColor": white}}}, "fields": "userEnteredFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(values), "startColumnIndex": 0, "endColumnIndex": 2}, "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}}, "fields": "userEnteredFormat.horizontalAlignment"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(values), "startColumnIndex": 4, "endColumnIndex": 7}, "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}}, "fields": "userEnteredFormat.horizontalAlignment"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(values), "startColumnIndex": 7, "endColumnIndex": 19}, "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}}, "fields": "userEnteredFormat.horizontalAlignment"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(values), "startColumnIndex": 4, "endColumnIndex": 6}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "dd.MM.yyyy"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(values), "startColumnIndex": 7, "endColumnIndex": 19}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.##"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 42}, "fields": "pixelSize"}},
        {"setBasicFilter": {"filter": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": len(values), "startColumnIndex": 0, "endColumnIndex": len(HEADERS)}}}},
    ]
    widths = [115, 95, 230, 190, 105, 125, 135] + [105] * 12
    for col, width in enumerate(widths):
        requests.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1}, "properties": {"pixelSize": width}, "fields": "pixelSize"}})
    for output_row, values_row in enumerate(rows, 2):
        status = values_row[6]
        if status == "Обнулен":
            color = yellow
        elif status == "Абонемента нет":
            color = red
        else:
            continue
        requests.append({"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": output_row - 1, "endRowIndex": output_row, "startColumnIndex": 0, "endColumnIndex": len(HEADERS)}, "cell": {"userEnteredFormat": {"backgroundColor": color}}, "fields": "userEnteredFormat.backgroundColor"}})
    for output_row, note in row_notes.items():
        requests.append({"updateCells": {"range": {"sheetId": sheet_id, "startRowIndex": output_row - 1, "endRowIndex": output_row, "startColumnIndex": 6, "endColumnIndex": 7}, "rows": [{"values": [{"note": note}]}], "fields": "note"}})
    # Sheets accepts at most a practical moderate number of requests per batch;
    # chunking keeps this robust if later months introduce many noted rows.
    for start in range(0, len(requests), 300):
        service.spreadsheets().batchUpdate(
            spreadsheetId=SID,
            body={"requests": requests[start:start + 300]},
        ).execute()


def main():
    credentials = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    properties = service.spreadsheets().get(
        spreadsheetId=SID,
        fields="sheets.properties",
    ).execute()["sheets"]
    month_titles = sorted(
        [s["properties"]["title"] for s in properties if MONTH_RE.fullmatch(s["properties"]["title"])],
        key=monthly_sort_key,
    )
    if not month_titles:
        raise RuntimeError("No monthly tabs found")
    rows, row_notes, counts, status_counts = combine(service, month_titles)
    sheet_id, created = ensure_target_sheet(service, len(rows) + 1)
    write_target(service, sheet_id, rows, row_notes)

    summary = {
        "sheet_id": sheet_id,
        "created": created,
        "months": month_titles,
        "month_counts": counts,
        "rows": len(rows),
        "main_rows": sum(v["Основной"] for v in counts.values()),
        "package_rows": sum(v["Пакет"] for v in counts.values()),
        "status_counts": status_counts,
        "notes_copied": len(row_notes),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
