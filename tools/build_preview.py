#!/usr/bin/env python3
"""index.html + styles.css + app.js + sample-jobs.json 을 합쳐
네트워크 없이 열리는 단일 미리보기 파일을 만든다.

실제 배포 파일을 그대로 인라인하므로, 미리보기에서 보이는 화면은
배포 후 화면과 같은 코드로 그려진다.
"""

import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def main():
    html = read("index.html")
    css = read("styles.css")
    js = read("app.js")
    data = json.loads(read("data", "sample-jobs.json"))
    data.pop("_readme", None)

    # 외부 참조 제거 후 인라인
    html = html.replace(
        '<link rel="stylesheet" href="styles.css">',
        "<style>\n" + css + "\n</style>",
    )
    html = re.sub(r'\s*<link rel="manifest"[^>]*>', "", html)
    html = re.sub(r'\s*<link rel="icon"[^>]*>', "", html)
    html = re.sub(r'\s*<link rel="apple-touch-icon"[^>]*>', "", html)

    payload = (
        "<script>window.__EJA_PREVIEW_DATA__ = "
        + json.dumps(data, ensure_ascii=False)
        + ";</script>\n<script>\n"
        + js
        + "\n</script>"
    )
    html = html.replace('<script src="app.js"></script>', payload)

    # 미리보기에서는 서비스워커를 등록하지 않는다
    html = html.replace('navigator.serviceWorker.register("sw.js")',
                        'Promise.resolve()')

    html = html.replace("<title>채용공고 모니터</title>",
                        "<title>채용공고 모니터 — 화면 미리보기</title>")

    out = os.path.join(ROOT, "preview.html")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("preview.html 생성 (%d bytes)" % os.path.getsize(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
