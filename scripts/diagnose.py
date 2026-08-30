"""링크 0건인 사이트의 원인을 '구체적 증거'로 남긴다.

이 모듈이 답하려는 질문:
  · 일반 요청(requests)은 애초에 성공했나? 응답 코드는?
  · 브라우저 렌더링은 성공했나? HTML 길이는 얼마나 되나?
  · 페이지 안에 <a> 태그가 몇 개나 있나? (0개면 렌더링 실패,
    많은데 0건이면 link_include 패턴 문제)
  · 실제 <a> 링크들이 어떻게 생겼나? (패턴을 맞추려면 이게 필요)

원인 구분표
  requests 4xx/5xx + 브라우저 실패      → 접근 차단 또는 URL 오류
  requests 200인데 a 태그 0~소수        → JS 렌더링 필요
  브라우저 성공 + a 태그 많음 + 매칭 0  → link_include 패턴 불일치
  브라우저 자체 실패(타임아웃)          → 렌더링 실패
"""

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import fetcher


def _anchors(html, base_url, limit=25):
    """페이지의 모든 <a href> 를 뽑아 형태를 보여준다."""
    if not html:
        return [], 0
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001
        return [], 0
    out = []
    seen = set()
    total = 0
    for a in soup.find_all("a", href=True):
        total += 1
        href = a["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        full = urljoin(base_url, href)
        if full in seen:
            continue
        seen.add(full)
        if len(out) < limit:
            text = " ".join(a.get_text(" ", strip=True).split())[:60]
            out.append({"text": text, "url": full})
    return out, total


def probe(session, source, renderer, url):
    """링크가 0건인 소스에 대해 원인 증거를 수집한다."""
    include = [p.lower() for p in source.get("link_include", []) if p]

    result = {
        "requests_status": None,
        "requests_error": "",
        "requests_html_len": 0,
        "requests_anchor_count": 0,
        "browser_ok": False,
        "browser_error": "",
        "browser_html_len": 0,
        "browser_anchor_count": 0,
        "unique_links_sample": [],
        "matched_by_pattern": 0,
        "link_include": source.get("link_include", []),
        "verdict": "",
    }

    # ── 1) 일반 요청으로 응답 코드부터 확인 ──
    res = fetcher.fetch(session, url, retries=0)
    fetcher.polite_sleep()
    result["requests_status"] = res.status
    if res.ok:
        result["requests_html_len"] = len(res.text)
        _, total = _anchors(res.text, url)
        result["requests_anchor_count"] = total
    else:
        result["requests_error"] = res.error or ""

    # ── 2) 브라우저 렌더링 결과 확인 ──
    html, err = renderer.render(
        url,
        wait_selector=source.get("render_wait_selector"),
        wait_ms=source.get("render_wait_ms", 4000),
    )
    if html:
        result["browser_ok"] = True
        result["browser_html_len"] = len(html)
        links, total = _anchors(html, url)
        result["browser_anchor_count"] = total
        result["unique_links_sample"] = links
        result["matched_by_pattern"] = sum(
            1 for l in links if any(i in l["url"].lower() for i in include)
        ) if include else 0
    else:
        result["browser_error"] = err or "렌더링 실패"

    # ── 3) 원인 판정 ──
    status = result["requests_status"]

    # 응답 코드가 4xx/5xx 면 브라우저가 '열렸다'고 해도 오류 페이지를 연 것이다.
    # (브라우저는 403 페이지도 정상 로드로 취급하므로 먼저 걸러야 한다)
    if status and status >= 400:
        kind = "접근 차단" if status in (401, 403, 429) else "URL 오류/서버 오류"
        result["verdict"] = (f"{kind} — requests 응답 {status}"
                             + (f", 브라우저는 열렸으나 링크 {result['browser_anchor_count']}개"
                                if result["browser_ok"] else ", 브라우저도 실패"))
    elif not result["browser_ok"] and status is None:
        result["verdict"] = (f"접속 실패 — requests {result['requests_error']}, "
                             f"브라우저 {result['browser_error']}")
    elif not result["browser_ok"]:
        result["verdict"] = f"브라우저 렌더링 실패 — {result['browser_error']} (requests는 {status})"
    elif result["browser_anchor_count"] == 0:
        result["verdict"] = ("페이지는 열렸으나 링크(<a>)가 0개 — 목록을 JS로 그리는데 "
                             "대기 시간이 부족하거나 로그인이 필요할 수 있음")
    elif include and result["matched_by_pattern"] == 0:
        result["verdict"] = (f"link_include 패턴 불일치 — 링크는 "
                             f"{result['browser_anchor_count']}개 있으나 패턴에 맞는 것 0개")
    elif not include:
        result["verdict"] = (f"link_include 미지정 + 휴리스틱 미통과 — 링크 "
                             f"{result['browser_anchor_count']}개 중 공고로 인정된 것 없음")
    else:
        result["verdict"] = "원인 미상 — unique_links_sample 을 확인하세요"

    return result
