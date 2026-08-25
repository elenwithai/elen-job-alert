"""HTTP 요청 담당. 한국 사이트의 EUC-KR 인코딩과 일시적 실패를 다룬다."""

import time
import random
import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}

# 서버에 부담 주지 않도록 요청 사이 최소 대기 (초)
REQUEST_DELAY = 1.2


class FetchResult:
    def __init__(self, ok, status=None, text="", error=None, final_url=None):
        self.ok = ok
        self.status = status
        self.text = text
        self.error = error
        self.final_url = final_url

    def __repr__(self):
        return f"<FetchResult ok={self.ok} status={self.status} len={len(self.text)}>"


def make_session():
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s


def _fix_encoding(resp):
    """requests는 charset 미선언 HTML을 ISO-8859-1로 가정한다.
    한국 사이트는 EUC-KR/CP949가 흔해서 그대로 두면 한글이 깨진다."""
    declared = (resp.encoding or "").lower()
    if not declared or declared in ("iso-8859-1", "ascii"):
        guessed = resp.apparent_encoding
        if guessed:
            resp.encoding = guessed
    # 본문 meta charset이 EUC-KR로 명시된 경우 우선 적용
    head = resp.content[:2048].lower()
    for enc in (b"euc-kr", b"ks_c_5601-1987", b"cp949"):
        if enc in head:
            resp.encoding = "cp949"
            break
    return resp


def fetch(session, url, timeout=25, retries=2):
    """GET 요청. 성공하면 FetchResult(ok=True, text=...)"""
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = session.get(url, timeout=timeout, allow_redirects=True)
            if resp.status_code >= 500 and attempt < retries:
                last_err = f"HTTP {resp.status_code}"
                time.sleep(2 ** attempt + random.random())
                continue
            if resp.status_code != 200:
                return FetchResult(
                    False,
                    status=resp.status_code,
                    error=f"HTTP {resp.status_code}",
                    final_url=resp.url,
                )
            _fix_encoding(resp)
            return FetchResult(True, status=200, text=resp.text, final_url=resp.url)
        except requests.exceptions.Timeout:
            last_err = "타임아웃"
        except requests.exceptions.SSLError as e:
            return FetchResult(False, error=f"SSL 오류: {e}")
        except requests.exceptions.RequestException as e:
            last_err = f"요청 실패: {type(e).__name__}"
        if attempt < retries:
            time.sleep(2 ** attempt + random.random())
    return FetchResult(False, error=last_err or "알 수 없는 오류")


def polite_sleep():
    time.sleep(REQUEST_DELAY + random.random() * 0.5)
