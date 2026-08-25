"""채용공고 본문에서 마감일을 뽑아낸다.

국내 채용 사이트의 실제 표기가 제각각이라 정규식 하나로는 안 된다.
확인된 형식들:

  접수기간 2026.07.30 00:00 ~ 2026.08.10 23:59 (접수마감)
  접수기간 2025.10.13(월) ~ 2025.10.22(수)
  접수기간 : 24.10.10(목) ~ 24.10.20(일) 23:59까지        ← 두 자리 연도
  접수기간 : 2025년 10월 13일(월) 00시 ~ 10월 22일(수) 18시  ← 끝 날짜에 연도 없음
  모집기간 : '20.4.6 (월) ~ '20.4.13 (월) 17:00 까지        ← 작은따옴표 연도
  마감일은 2024년 10월 20일 (일) 23:59까지
  [제목] 2024 하반기 신입채용 (~10/20)                      ← 제목의 축약 표기
  상시채용 / 채용시 마감 / 수시채용

핵심 규칙 세 가지
  1) 기간 범위에서는 **끝 날짜**를 쓴다 (시작일을 쓰면 항상 이미 마감이 된다)
  2) 연도가 빠진 날짜는 같은 문장의 다른 날짜에서, 없으면 오늘 기준으로 채운다
  3) "접수마감", "모집이 종료" 같은 문구가 있으면 날짜와 무관하게 마감으로 본다
"""

import re
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# 마감일이 적혀 있을 만한 자리를 알려주는 단어
CONTEXT_KEYWORDS = [
    "접수기간", "접수 기간", "지원기간", "지원 기간", "모집기간", "모집 기간",
    "채용기간", "원서접수", "서류접수", "접수일정",
    "마감일시", "마감일자", "마감일", "서류마감", "지원마감", "접수마감", "모집마감",
    "마감", "까지",
    "deadline", "closing date", "closes", "apply by", "application period",
]

# 이 문구가 있으면 이미 끝난 공고로 본다
CLOSED_MARKERS = [
    "접수마감", "접수 마감", "모집마감", "모집 마감", "채용마감", "채용 마감",
    "마감되었습니다", "마감 되었습니다", "마감된 공고", "종료되었습니다",
    "종료된 공고", "지원기간이 종료", "접수가 종료", "모집이 종료",
    "마감된 채용", "지원이 마감", "closed", "no longer accepting",
]

# 기한이 따로 없는 상시 채용
ALWAYS_OPEN = ["상시채용", "상시 채용", "수시채용", "수시 채용",
               "채용시 마감", "채용 시 마감", "충원시 마감", "상시모집", "상시 모집"]

# 2026.09.01 / 2026-09-01 / 2026년 9월 1일 / 2026/9/1
RE_FULL = re.compile(
    r"(?<![\d])(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*일?"
)
# '24.10.20 / 24.10.20 (두 자리 연도)
RE_SHORT_YEAR = re.compile(
    r"(?<![\d.])['\u2018\u2019]?(\d{2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})(?![\d])"
)
# 10월 22일 / 10/22 / 10.22 (연도 없음)
RE_MONTH_DAY = re.compile(
    r"(?<![\d.])(\d{1,2})\s*[./월]\s*(\d{1,2})\s*일?(?![\d])"
)

RE_TIME = re.compile(r"\d{1,2}\s*[:시]\s*\d{2}")
# 구분자가 공백뿐인 표기 ("2020 2 16"). 오탐이 날 수 있어 마지막에만 쓴다.
RE_SPACED = re.compile(r"(?<![\d])(20\d{2})\s+(\d{1,2})\s+(\d{1,2})(?!\s*[명원개%])")


def _norm(text):
    text = re.sub(r"[\u00a0\t]+", " ", text or "")
    return re.sub(r"[ ]{2,}", " ", text)


def _valid(y, m, d):
    try:
        return datetime(y, m, d, tzinfo=KST)
    except ValueError:
        return None


def _find_dates(chunk, today):
    """문자열에서 날짜를 등장 순서대로 뽑는다.
    연도가 없는 날짜는 year=None 으로 표시해 나중에 채운다."""
    found = []          # (위치, 연도 or None, 월, 일)
    consumed = []       # 이미 먹은 구간 (겹침 방지)

    def overlaps(a, b):
        return any(not (b <= s or a >= e) for s, e in consumed)

    for m in RE_FULL.finditer(chunk):
        if overlaps(m.start(), m.end()):
            continue
        consumed.append((m.start(), m.end()))
        found.append((m.start(), int(m.group(1)), int(m.group(2)), int(m.group(3))))

    for m in RE_SHORT_YEAR.finditer(chunk):
        if overlaps(m.start(), m.end()):
            continue
        yy = int(m.group(1))
        # 두 자리 연도는 2000년대로 본다
        consumed.append((m.start(), m.end()))
        found.append((m.start(), 2000 + yy, int(m.group(2)), int(m.group(3))))

    for m in RE_MONTH_DAY.finditer(chunk):
        if overlaps(m.start(), m.end()):
            continue
        # 시각 표기(18:00, 18시 00분)를 날짜로 오인하지 않게 거른다
        if RE_TIME.match(chunk[m.start():m.end() + 2] or ""):
            continue
        mm, dd = int(m.group(1)), int(m.group(2))
        if not (1 <= mm <= 12 and 1 <= dd <= 31):
            continue
        consumed.append((m.start(), m.end()))
        found.append((m.start(), None, mm, dd))

    if not found:
        for m in RE_SPACED.finditer(chunk):
            found.append((m.start(), int(m.group(1)), int(m.group(2)), int(m.group(3))))

    found.sort(key=lambda x: x[0])

    # 연도 채우기: 같은 구간의 앞선 날짜 연도를 물려받고, 없으면 오늘 기준
    out = []
    last_year = None
    for _pos, y, mm, dd in found:
        if y is None:
            if last_year is not None:
                y = last_year
            else:
                y = today.year
                cand = _valid(y, mm, dd)
                # 이미 반년 넘게 지난 날짜면 내년 것으로 본다
                if cand and (today - cand).days > 180:
                    y += 1
        else:
            last_year = y
        dt = _valid(y, mm, dd)
        if dt:
            out.append(dt)
    return out


def _windows(text):
    """마감 관련 단어 주변 구간을 모두 모은다."""
    low = text.lower()
    spans = []
    for kw in CONTEXT_KEYWORDS:
        start = 0
        while True:
            idx = low.find(kw.lower(), start)
            if idx == -1:
                break
            spans.append((max(0, idx - 60), min(len(text), idx + 120)))
            start = idx + 1
            if len(spans) > 40:
                break
    if not spans:
        return []
    spans.sort()
    merged = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [text[s:e] for s, e in merged]


def is_closed_text(text):
    """본문에 '마감되었습니다' 류의 문구가 있는지. 파싱 실패 시의 안전장치."""
    if not text:
        return False, ""
    low = _norm(text).lower()
    for marker in CLOSED_MARKERS:
        if marker.lower() in low:
            return True, marker
    return False, ""


def find_deadline(text, title="", today=None, extra_patterns=None):
    """반환: (값, 근거설명)
    값은 'YYYY-MM-DD' / '상시' / '마감' / '' 중 하나."""
    today = today or datetime.now(KST)
    text = _norm(text)
    title = _norm(title)
    blob = (title + "\n" + text) if title else text

    # ① 사이트별 개별 규칙 (sources.json 의 deadline_patterns)
    for pat in (extra_patterns or []):
        try:
            m = re.search(pat, blob, re.IGNORECASE)
        except re.error:
            continue
        if m:
            groups = [g for g in m.groups() if g] or [m.group(0)]
            dates = _find_dates(" ".join(str(g) for g in groups), today)
            if dates:
                return dates[-1].strftime("%Y-%m-%d"), f"개별 규칙: {pat}"

    # ② 제목의 축약 표기: (~10/20), ~ 9월 1일
    tm = re.search(r"~\s*(\d{1,2})\s*[./월]\s*(\d{1,2})\s*일?\s*\)?", title)
    if tm:
        dates = _find_dates(tm.group(0), today)
        if dates:
            return dates[-1].strftime("%Y-%m-%d"), "제목의 마감 표기"

    # ③ 마감 관련 단어 주변에서 찾기 — 범위면 끝 날짜
    for win in _windows(blob):
        dates = _find_dates(win, today)
        if dates:
            return dates[-1].strftime("%Y-%m-%d"), "마감 문구 주변 날짜"

    # ④ 이미 끝났다는 문구
    closed, marker = is_closed_text(blob)
    if closed:
        return "마감", f"'{marker}' 문구"

    # ⑤ 상시 채용
    low = blob.lower()
    for kw in ALWAYS_OPEN:
        if kw in low:
            return "상시", f"'{kw}' 표기"

    return "", ""
