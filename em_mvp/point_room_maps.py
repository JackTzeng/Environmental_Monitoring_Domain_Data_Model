"""Point-to-room references with an explicit site, method, and year scope."""

# Evidence: 2026 user reference workbook, sheet "三廠｜落菌法", rows 41–50 and 52–56.
ROOM_MAP_EVIDENCE = "2026 參考活頁簿「三廠｜落菌法」第 41–50、52–56 列"
ROOM_MAP_SCOPE = {"site": "三廠", "method": "落菌法", "year": 2026}
POINT_ROOMS = {
    **{f"BSC07-01-{index}": "C17" for index in range(1, 6)},
    **{f"BSC07-02-{index}": "C17" for index in range(1, 6)},
    **{f"BSC08-{index}": "C18" for index in range(1, 6)},
}
