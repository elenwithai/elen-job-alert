#!/usr/bin/env python3
"""실제 Chromium으로 가로 스크롤 발생 여부를 측정한다.

한계: 헤드리스 Chromium은 실제 폰(iOS Safari, 안드로이드 크롬)과
폰트 메트릭·주소창 높이·safe-area가 다르다. 여기서 통과해도
실기기 확인은 별도로 필요하다.
"""

import sys
import threading
import functools
import http.server
import socketserver

from playwright.sync_api import sync_playwright

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
PORT = 8931

# (라벨, CSS 폭, DPR)
# 320px / DPR 3.375 가 사용자 실기기 진단으로 실측된 값이다.
# 360px, 412px 는 기종 편차 대비용 보조 검증이며 실측값이 아니다.
VIEWPORTS = [
    ("실측 기준 320px (DPR 3.375)", 320, 3.375),
    ("기종 편차 대비 360px", 360, 3.0),
    ("기종 편차 대비 412px", 412, 2.625),
    ("태블릿 768px", 768, 2.0),
]


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


PROBE = """() => {
  const de = document.documentElement;
  const offenders = [];
  const vw = de.clientWidth;
  document.querySelectorAll('*').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return;
    if (r.right > vw + 1 || r.left < -1) {
      offenders.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.className && el.className.toString().slice(0, 40)) || '',
        left: Math.round(r.left),
        right: Math.round(r.right),
        text: (el.textContent || '').trim().slice(0, 40)
      });
    }
  });
  return {
    scrollWidth: de.scrollWidth,
    clientWidth: de.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
    overflow: de.scrollWidth - de.clientWidth,
    offenders: offenders.slice(0, 8)
  };
}"""


def run_page(page, url, label, width):
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(400)
    res = page.evaluate(PROBE)
    ok = res["overflow"] <= 0
    status = "통과" if ok else "가로 스크롤 발생"
    print(f"  [{status}] {label}")
    print(f"      scrollWidth={res['scrollWidth']} clientWidth={res['clientWidth']} "
          f"초과={res['overflow']}px")
    if not ok:
        for o in res["offenders"]:
            print(f"      · <{o['tag']} class=\"{o['cls']}\"> "
                  f"left={o['left']} right={o['right']} :: {o['text']}")
    return ok


def main():
    serve()
    base = f"http://127.0.0.1:{PORT}"
    targets = [
        ("데모 데이터 (카드 5장)", f"{base}/index.html?demo=1"),
        ("빈 데이터 (최초 배포 직후)", f"{base}/index.html"),
    ]

    all_ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for scheme in ("light", "dark"):
            for label, width, dpr in VIEWPORTS:
                ctx = browser.new_context(
                    viewport={"width": width, "height": 850},
                    device_scale_factor=dpr,
                    is_mobile=True,
                    has_touch=True,
                    color_scheme=scheme,
                )
                page = ctx.new_page()
                for tname, url in targets:
                    print(f"\n{scheme} / {tname}")
                    if not run_page(page, url, label, width):
                        all_ok = False
                ctx.close()

        # 스크린샷 (412px, 데모, 라이트/다크)
        for scheme in ("light", "dark"):
            ctx = browser.new_context(
                viewport={"width": 412, "height": 900},
                device_scale_factor=2,
                is_mobile=True, has_touch=True, color_scheme=scheme,
            )
            pg = ctx.new_page()
            pg.goto(f"{base}/index.html?demo=1", wait_until="networkidle")
            pg.wait_for_timeout(400)
            pg.screenshot(path=f"/tmp/shot-{scheme}.png", full_page=True)
            ctx.close()
        browser.close()

    print("\n" + ("=== 모든 폭에서 가로 스크롤 없음 ===" if all_ok
                  else "=== 가로 스크롤 발견 — 위 요소 확인 ==="))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
