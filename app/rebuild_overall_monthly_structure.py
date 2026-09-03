#!/usr/bin/env python3
"""Rebuild `Общее` with the same two-block structure as monthly reports.

Monthly tabs in the main spreadsheet are the only data source. YCLIENTS and
local audit checkpoints are intentionally not read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from build_overall_sheet import (
    SID,
    TOKEN,
    TARGET,
    MONTH_RE,
    monthly_sort_key,
    combine,
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
ROOT = Path(os.environ.get("YCLIENTS_OPS_HOME", Path(__file__).resolve().parents[1]))
SUMMARY_PATH = ROOT / "runtime/overall_monthly_structure_summary.json"
MAIN_HEADERS = [
    "Месяц",
    "Почта",
    "Курс",
    "Дата покупки",
    "Дата окончания абонемента",
    "Статус",
    "Групп",
    "Инди",
    "Отходили Групп",
    "Отходили Инди",
    "Осталось Групп",
    "Осталось Инди",
    "Просрочилось групп",
    "Просрочилось инди",
    "Уменьшили групп",
    "Прибавили групп",
    "Уменьшили инди",
    "Прибавили инди",
]
PACKAGE_HEADERS = [
    "Месяц",
    "Почта",
    "Курс",
    "Дата покупки",
    "Дата окончания абонемента",
    "Статус",
    "Инди",
    "Отходили",
    "Осталось",
    "Просрочилось",
]


def ensure_target(service, required_rows):
    metadata = service.spreadsheets().get(
        spreadsheetId=SID, fields="sheets(properties,basicFilter)"
    ).execute()["sheets"]
    target_sheet = next(s for s in metadata if s["properties"]["title"] == TARGET)
    prop = target_sheet["properties"]
    sheet_id = prop["sheetId"]
    row_count = max(required_rows + 100, 1200)
    requests = []
    # Clear the old flat-table filter before shrinking from 19 to 18 columns.
    if target_sheet.get("basicFilter"):
        requests.append({"clearBasicFilter": {"sheetId": sheet_id}})
    if prop.get("gridProperties", {}).get("rowCount", 0) < row_count or prop.get("gridProperties", {}).get("columnCount") != len(MAIN_HEADERS):
        requests.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {
                        "rowCount": row_count,
                        "columnCount": len(MAIN_HEADERS),
                        "frozenRowCount": 1,
                    },
                },
                "fields": "gridProperties(rowCount,columnCount,frozenRowCount)",
            }
        })
    else:
        requests.append({
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        })

    requests.extend([
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id},
                "cell": {"note": "", "userEnteredFormat": {}},
                "fields": "note,userEnteredFormat",
            }
        },
    ])
    service.spreadsheets().batchUpdate(
        spreadsheetId=SID, body={"requests": requests}
    ).execute()
    service.spreadsheets().values().clear(
        spreadsheetId=SID, range=f"'{TARGET}'!A:Z", body={}
    ).execute()
    return sheet_id


def formulas_for(main_total, package_first, package_total):
    # Numeric columns shifted one place to the right because the aggregate keeps
    # a visible Month column but removes the flat Type column.
    main_total_formulas = [[f"=SUM({col}2:{col}{main_total - 1})" for col in "GHIJKLMNOPQR"]]
    main_analytics = [
        [f"=I{main_total}/G{main_total}"],
        [f"=J{main_total}/H{main_total}"],
        [f"=K{main_total}/G{main_total}"],
        [f"=L{main_total}/H{main_total}"],
        [f"=M{main_total}/G{main_total}"],
        [f"=N{main_total}/H{main_total}"],
        [f"=G{main_total}-M{main_total}-I{main_total}"],
        [f"=H{main_total}-N{main_total}-J{main_total}"],
    ]
    package_total_formulas = [[f"=SUM({col}{package_first}:{col}{package_total - 1})" for col in "GHIJ"]]
    package_rates = [
        [f"=H{package_total}/G{package_total}"],
        [f"=I{package_total}/G{package_total}"],
        [f"=J{package_total}/G{package_total}"],
    ]
    return main_total_formulas, main_analytics, package_total_formulas, package_rates


def write_values(service, rows, flat_notes):
    records = [
        {"row": row, "note": flat_notes.get(flat_row)}
        for flat_row, row in enumerate(rows, 2)
    ]
    main_records = [record for record in records if record["row"][1] == "Основной"]
    package_records = [record for record in records if record["row"][1] == "Пакет"]

    # Remove `Тип блока`. The main block keeps Month plus the approved monthly
    # A:Q schema; the package block keeps Month plus approved package A:I.
    main_rows = [[r[0]] + r[2:] for r in (record["row"] for record in main_records)]
    package_rows = [
        [r[0], r[2], r[3], r[4], r[5], r[6], r[8], r[10], r[12], r[14]]
        for r in (record["row"] for record in package_records)
    ]

    main_total = 2 + len(main_rows)
    analytics_first = main_total + 1
    blank_first = main_total + 9
    package_title = main_total + 11
    package_header = package_title + 1
    package_first = package_header + 1
    package_total = package_first + len(package_rows)
    package_rates_first = package_total + 1
    last_row = package_total + 3

    values = [MAIN_HEADERS]
    values.extend(main_rows)
    values.append(["Итого"] + [""] * 17)
    values.extend([
        ["% отхаживания", "групп", ""],
        ["% отхаживания", "инди", ""],
        ["% осталось", "групп", ""],
        ["% осталось", "инди", ""],
        ["% просрочилось", "групп", ""],
        ["% просрочилось", "инди", ""],
        ["Нереализованные консультации", "групп", ""],
        ["Нереализованные консультации", "инди", ""],
        [],
        [],
        ["пакет конс"],
        PACKAGE_HEADERS,
    ])
    values.extend(package_rows)
    values.append(["Итого"] + [""] * 9)
    values.extend([
        ["% отхаживания", "инди", ""],
        ["% осталось", "инди", ""],
        ["% просрочилось", "инди", ""],
    ])
    assert len(values) == last_row

    service.spreadsheets().values().update(
        spreadsheetId=SID,
        range=f"'{TARGET}'!A1:R{last_row}",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    mtf, maf, ptf, prf = formulas_for(main_total, package_first, package_total)
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SID,
        body={
            "valueInputOption": "USER_ENTERED",
            "data": [
                {"range": f"'{TARGET}'!G{main_total}:R{main_total}", "values": mtf},
                {"range": f"'{TARGET}'!C{analytics_first}:C{analytics_first + 7}", "values": maf},
                {"range": f"'{TARGET}'!G{package_total}:J{package_total}", "values": ptf},
                {"range": f"'{TARGET}'!C{package_rates_first}:C{package_rates_first + 2}", "values": prf},
            ],
        },
    ).execute()

    # Remap copied source notes to the new vertical blocks and common Status col F.
    notes = {}
    for index, record in enumerate(main_records, 2):
        if record["note"]:
            notes[index] = record["note"]
    for index, record in enumerate(package_records, package_first):
        if record["note"]:
            notes[index] = record["note"]

    return {
        "main_rows": main_rows,
        "package_rows": package_rows,
        "notes": notes,
        "main_total": main_total,
        "analytics_first": analytics_first,
        "blank_first": blank_first,
        "package_title": package_title,
        "package_header": package_header,
        "package_first": package_first,
        "package_total": package_total,
        "package_rates_first": package_rates_first,
        "last_row": last_row,
    }


def format_sheet(service, sheet_id, layout):
    main_rows = layout["main_rows"]
    package_rows = layout["package_rows"]
    main_total = layout["main_total"]
    analytics_first = layout["analytics_first"]
    blank_first = layout["blank_first"]
    package_title = layout["package_title"]
    package_header = layout["package_header"]
    package_first = layout["package_first"]
    package_total = layout["package_total"]
    package_rates_first = layout["package_rates_first"]
    last_row = layout["last_row"]

    white = {"red": 1, "green": 1, "blue": 1}
    blue_header = {"red": 0.84705883, "green": 0.8980392, "blue": 0.96862745}
    green_header = {"red": 0.8980392, "green": 0.95686275, "blue": 0.8784314}
    gray = {"red": 0.91764706, "green": 0.91764706, "blue": 0.91764706}
    yellow = {"red": 1, "green": 0.949, "blue": 0.6}
    red = {"red": 1, "green": 0.8, "blue": 0.8}

    requests = [
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": last_row, "startColumnIndex": 0, "endColumnIndex": len(MAIN_HEADERS)}, "cell": {"userEnteredFormat": {"backgroundColor": white, "textFormat": {"fontFamily": "Arial", "fontSize": 10, "foregroundColor": {"red": 0, "green": 0, "blue": 0}}, "verticalAlignment": "MIDDLE"}}, "fields": "userEnteredFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": len(MAIN_HEADERS)}, "cell": {"userEnteredFormat": {"backgroundColor": blue_header, "textFormat": {"fontFamily": "Arial", "fontSize": 10, "bold": True}, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}}, "fields": "userEnteredFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": main_total - 1, "startColumnIndex": 3, "endColumnIndex": 5}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "dd.MM.yyyy"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": main_total - 1, "startColumnIndex": 6, "endColumnIndex": 18}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.##"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": main_total - 1, "endRowIndex": main_total, "startColumnIndex": 0, "endColumnIndex": len(MAIN_HEADERS)}, "cell": {"userEnteredFormat": {"backgroundColor": gray, "textFormat": {"bold": True}}}, "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.bold"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": analytics_first - 1, "endRowIndex": analytics_first + 5, "startColumnIndex": 2, "endColumnIndex": 3}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.00%"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": analytics_first + 5, "endRowIndex": analytics_first + 7, "startColumnIndex": 2, "endColumnIndex": 3}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": package_title - 1, "endRowIndex": package_title, "startColumnIndex": 0, "endColumnIndex": len(MAIN_HEADERS)}, "cell": {"userEnteredFormat": {"backgroundColor": white, "textFormat": {"bold": True}}}, "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.bold"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": package_header - 1, "endRowIndex": package_header, "startColumnIndex": 0, "endColumnIndex": len(PACKAGE_HEADERS)}, "cell": {"userEnteredFormat": {"backgroundColor": green_header, "textFormat": {"bold": True}, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}}, "fields": "userEnteredFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": package_first - 1, "endRowIndex": package_total - 1, "startColumnIndex": 3, "endColumnIndex": 5}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "dd.MM.yyyy"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": package_first - 1, "endRowIndex": package_total - 1, "startColumnIndex": 6, "endColumnIndex": 10}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.##"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": package_total - 1, "endRowIndex": package_total, "startColumnIndex": 0, "endColumnIndex": len(PACKAGE_HEADERS)}, "cell": {"userEnteredFormat": {"backgroundColor": gray, "textFormat": {"bold": True}}}, "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.bold"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": package_rates_first - 1, "endRowIndex": package_rates_first + 2, "startColumnIndex": 2, "endColumnIndex": 3}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.00%"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 42}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": package_header - 1, "endIndex": package_header}, "properties": {"pixelSize": 42}, "fields": "pixelSize"}},
    ]

    widths = [115, 230, 190, 105, 125, 135] + [105] * 12
    for col, width in enumerate(widths):
        requests.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1}, "properties": {"pixelSize": width}, "fields": "pixelSize"}})

    for output_row, row in enumerate(main_rows, 2):
        status = row[5]
        if status == "Обнулен":
            color = yellow
        elif status == "Абонемента нет":
            color = red
        else:
            continue
        requests.append({"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": output_row - 1, "endRowIndex": output_row, "startColumnIndex": 0, "endColumnIndex": len(MAIN_HEADERS)}, "cell": {"userEnteredFormat": {"backgroundColor": color}}, "fields": "userEnteredFormat.backgroundColor"}})
    for output_row, row in enumerate(package_rows, package_first):
        status = row[5]
        if status == "Обнулен":
            color = yellow
        elif status == "Абонемента нет":
            color = red
        else:
            continue
        requests.append({"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": output_row - 1, "endRowIndex": output_row, "startColumnIndex": 0, "endColumnIndex": len(PACKAGE_HEADERS)}, "cell": {"userEnteredFormat": {"backgroundColor": color}}, "fields": "userEnteredFormat.backgroundColor"}})
    for output_row, note in layout["notes"].items():
        requests.append({"updateCells": {"range": {"sheetId": sheet_id, "startRowIndex": output_row - 1, "endRowIndex": output_row, "startColumnIndex": 5, "endColumnIndex": 6}, "rows": [{"values": [{"note": note}]}], "fields": "note"}})

    for start in range(0, len(requests), 300):
        service.spreadsheets().batchUpdate(
            spreadsheetId=SID, body={"requests": requests[start:start + 300]}
        ).execute()


def main():
    credentials = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    sheets = service.spreadsheets().get(
        spreadsheetId=SID, fields="sheets.properties"
    ).execute()["sheets"]
    month_titles = sorted(
        [s["properties"]["title"] for s in sheets if MONTH_RE.fullmatch(s["properties"]["title"])],
        key=monthly_sort_key,
    )
    rows, flat_notes, counts, status_counts = combine(service, month_titles)
    # Calculate final row count before resetting the grid.
    main_count = sum(v["Основной"] for v in counts.values())
    package_count = sum(v["Пакет"] for v in counts.values())
    required_rows = 1 + main_count + 1 + 8 + 2 + 1 + 1 + package_count + 1 + 3
    sheet_id = ensure_target(service, required_rows)
    layout = write_values(service, rows, flat_notes)
    assert layout["last_row"] == required_rows
    format_sheet(service, sheet_id, layout)

    summary = {
        "sheet_id": sheet_id,
        "months": month_titles,
        "main_rows": main_count,
        "main_total": layout["main_total"],
        "analytics_rows": [layout["analytics_first"], layout["analytics_first"] + 7],
        "blank_rows": [layout["blank_first"], layout["blank_first"] + 1],
        "package_title": layout["package_title"],
        "package_header": layout["package_header"],
        "package_rows": package_count,
        "package_data_rows": [layout["package_first"], layout["package_total"] - 1],
        "package_total": layout["package_total"],
        "package_rate_rows": [layout["package_rates_first"], layout["package_rates_first"] + 2],
        "last_row": layout["last_row"],
        "status_counts": status_counts,
        "notes_copied": len(layout["notes"]),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
