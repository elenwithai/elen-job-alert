"""자바스크립트로 목록을 그리는 사이트용 폴백 렌더러.

일반 requests 방식으로 링크가 안 잡히는 사이트(삼성·한화 등 대기업
채용포털)를 헤드리스 크로미움으로 실제 렌더링한 뒤 HTML을 가져온다.

Playwright가 설치돼 있지 않거나 브라우저 바이너리가 없으면
available=False 가 되고, 호출 측은 조용히 일반 방식 결과를 그대로 쓴다.
로컬에서 Playwright 없이 돌려도 스크립트가 죽지 않게 하기 위함이다.
"""

import sys

DEFAULT_TIMEOUT_MS = 35000
DEFAULT_WAIT_MS = 2500

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class Renderer:
    """필요할 때만 브라우저를 띄우고, 실행이 끝나면 닫는다."""

    def __init__(self):
        self._pw = None
        self._browser = None
        self._ctx = None
        self.available = None      # None=아직 시도 안 함, True/False=시도 결과
        self.error = ""
        self.pages_rendered = 0

    def _ensure(self):
        if self._ctx is not None:
            return True
        if self.available is False:
            return False
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.available = False
            self.error = "Playwright 미설치"
            print("[i] Playwright 없음 — 브라우저 폴백 건너뜀", file=sys.stderr)
            return False
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                args=["--disable-dev-shm-usage", "--no-sandbox"]
            )
            self._ctx = self._browser.new_context(
                user_agent=UA,
                locale="ko-KR",
                viewport={"width": 1280, "height": 1600},
                extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"},
            )
            self._ctx.set_default_timeout(DEFAULT_TIMEOUT_MS)
            self.available = True
            print("[i] 브라우저 렌더러 시작")
            return True
        except Exception as e:  # noqa: BLE001
            self.available = False
            self.error = f"브라우저 실행 실패: {type(e).__name__}"
            print(f"[!] {self.error} — 브라우저 폴백 건너뜀", file=sys.stderr)
            return False

    def render(self, url, wait_selector=None, wait_ms=DEFAULT_WAIT_MS, scroll=True):
        """페이지를 실제로 렌더링한 뒤 HTML 문자열을 돌려준다.
        실패하면 (None, 사유) 를 돌려준다."""
        if not self._ensure():
            return None, self.error or "브라우저 사용 불가"

        page = None
        try:
            page = self._ctx.new_page()
            # 이미지/폰트는 받지 않는다 (속도·트래픽 절약)
            page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("image", "media", "font")
                else route.continue_(),
            )
            page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)

            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=15000)
                except Exception:  # noqa: BLE001
                    pass  # 못 찾아도 일단 현재 HTML을 본다

            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:  # noqa: BLE001
                pass

            if scroll:
                # 무한스크롤/지연로딩 목록 대응
                try:
                    for _ in range(3):
                        page.mouse.wheel(0, 4000)
                        page.wait_for_timeout(600)
                except Exception:  # noqa: BLE001
                    pass

            page.wait_for_timeout(wait_ms)
            html = page.content()
            self.pages_rendered += 1
            return html, ""
        except Exception as e:  # noqa: BLE001
            return None, f"렌더링 실패: {type(e).__name__}"
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass

    def close(self):
        for obj in (self._ctx, self._browser):
            try:
                if obj:
                    obj.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._ctx = self._browser = self._pw = None
