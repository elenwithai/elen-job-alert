"""목록 페이지에서 개별 공고 링크를 뽑고, 상세 페이지에서 본문을 뽑는다."""

import re
import hashlib
from urllib.parse import urljoin, urlparse, urldefrag

from bs4 import BeautifulSoup

import deadline

# 상세 본문에서 잘라낼 최대 길이 (AI 입력 비용 통제)
MAX_DETAIL_CHARS = 6000

NOISE_TAGS = [
    "script", "style", "noscript", "iframe", "svg", "form",
    "nav", "header", "footer", "aside", "button", "select",
]

# 공고 링크일 가능성이 낮은 흔한 경로
GENERIC_EXCLUDE = [
    "javascript:", "mailto:", "tel:",
    "/login", "/logout", "/privacy", "/terms", "/sitemap",
    "facebook.com", "twitter.com", "linkedin.com/company",
    "instagram.com", "youtube.com", ".pdf", ".zip", ".hwp",
]

# 페이지네이션/정렬 링크에 흔히 쓰이는 쿼리 키
PAGING_KEYS = (
    "page=", "pageno=", "pageindex=", "pagenum=", "currentpage=", "curpage=",
    "p=", "offset=", "start=", "pageunit=", "sort=", "order=",
)

MAIN_SELECTORS = [
    "main", "article", "[role=main]",
    "#content", "#contents", "#container", ".content", ".contents",
    ".job-description", ".jobDescription", ".job-detail", ".recruit-view",
    ".board-view", ".view-content", ".detail", "#jobDescriptionText",
]


def normalize_url(url):
    url, _ = urldefrag(url)
    return url.rstrip("/") if url.endswith("/") and url.count("/") > 3 else url


def job_id(url, company, title):
    """공고 고유 ID. URL이 있으면 URL 기준, 없으면 회사+제목."""
    basis = normalize_url(url) if url else f"{company}::{title}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def clean_text(s):
    s = re.sub(r"[ \t\u00a0]+", " ", s or "")
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def extract_links(html, base_url, source):
    """목록 페이지 HTML에서 개별 공고 상세 링크 후보를 추출한다."""
    soup = BeautifulSoup(html, "html.parser")
    include = [p.lower() for p in source.get("link_include", []) if p]
    exclude = [p.lower() for p in source.get("link_exclude", []) if p]
    min_len = source.get("min_title_len", 4)
    same_host_only = source.get("same_host_only", True)
    base_host = urlparse(base_url).netloc.lower()

    # 목록 페이지 자신을 공고로 오인하지 않기 위한 기준값
    list_norm = normalize_url(base_url)
    list_path = urlparse(list_norm).path.rstrip("/")

    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if low.startswith("#") or not href:
            continue
        if any(g in low for g in GENERIC_EXCLUDE):
            continue
        full = normalize_url(urljoin(base_url, href))
        if not full.startswith("http"):
            continue
        full_low = full.lower()
        parts = urlparse(full)
        if same_host_only and parts.netloc.lower() != base_host:
            continue
        if any(e in full_low for e in exclude):
            continue

        # ① 목록 페이지 그 자체는 공고가 아니다
        if full == list_norm:
            continue
        # ② 도메인 루트도 공고가 아니다
        if not parts.path.strip("/"):
            continue

        # ③ 목록과 같은 경로인데 쿼리만 페이지 번호류 → 페이지네이션이므로 제외
        #    (삼성처럼 같은 경로에 ?no=123 으로 상세를 주는 사이트는 걸리지 않는다)
        if parts.path.rstrip("/") == list_path and parts.query:
            q = parts.query.lower()
            if any(k in q for k in PAGING_KEYS):
                continue

        if include:
            if not any(i in full_low for i in include):
                continue
        else:
            # 패턴 미지정 시 휴리스틱
            path = parts.path
            # ④ 패턴이 없으면 목록과 같은 경로는 전부 제외
            if path.rstrip("/") == list_path:
                continue
            # ⑤ 숫자 ID가 들어간 깊은 경로만 채택
            if not re.search(r"\d{3,}", full) or path.count("/") < 2:
                continue
        title = clean_text(a.get_text(" ", strip=True))
        if len(title) < min_len:
            # 링크 텍스트가 비면 부모 영역 제목을 시도
            parent = a.find_parent(["li", "tr", "div"])
            if parent:
                title = clean_text(parent.get_text(" ", strip=True))[:150]
        if len(title) < min_len:
            continue
        if full not in found or len(title) > len(found[full]):
            found[full] = title[:200]

    return [{"url": u, "title": t} for u, t in found.items()]


def extract_detail(html):
    """상세 페이지에서 제목과 본문 텍스트를 추출한다."""
    soup = BeautifulSoup(html, "html.parser")

    page_title = ""
    if soup.title and soup.title.string:
        page_title = clean_text(soup.title.string)[:200]
    h1 = soup.find(["h1", "h2"])
    if h1:
        ht = clean_text(h1.get_text(" ", strip=True))
        if 3 < len(ht) < 200:
            page_title = ht

    for tag in soup(NOISE_TAGS):
        tag.decompose()

    node = None
    for sel in MAIN_SELECTORS:
        try:
            candidate = soup.select_one(sel)
        except Exception:
            candidate = None
        if candidate and len(candidate.get_text(strip=True)) > 200:
            node = candidate
            break
    if node is None:
        node = soup.body or soup

    text = clean_text(node.get_text("\n", strip=True))
    # 한 줄짜리 메뉴 잔여물 제거
    lines = [ln for ln in text.split("\n") if len(ln.strip()) > 1]
    text = "\n".join(lines)

    truncated = len(text) > MAX_DETAIL_CHARS
    if truncated:
        text = text[:MAX_DETAIL_CHARS]

    return {"title": page_title, "text": text, "truncated": truncated}


def guess_deadline(text, title="", extra_patterns=None):
    """본문에서 마감일을 추정한다. 실제 파싱은 deadline 모듈이 담당한다."""
    value, _why = deadline.find_deadline(text, title, extra_patterns=extra_patterns)
    return value
