#!/usr/bin/env python3
"""Actions 실행 결과를 GitHub Step Summary용 마크다운으로 출력한다."""

import json
import os
import sys

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "jobs.json")

try:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
except Exception as e:  # noqa: BLE001
    print(f"결과 파일을 읽지 못했습니다: {e}")
    sys.exit(0)

s = d.get("stats", {})
print(f"### 마지막 업데이트: {d.get('updated_at')}")
print("")
if s.get("crawl_only"):
    print("> **수집 전용 실행** — API 키가 없거나 dry_run 을 켜서 AI 판단을 건너뛰었습니다.")
    print("> 상세 본문까지 받아두었으므로, 키를 등록하고 다시 실행하면 그 본문으로 판단합니다.")
    print("")
print(f"- 전체 **{s.get('total')}건** / AI 추천 **{s.get('fit_yes')}건** / "
      f"판단 보류 **{s.get('pending')}건** / AI 판단 전 **{s.get('unjudged', 0)}건**")
print(f"- 이번 실행 신규 {s.get('new_this_run')}건, AI 호출 {s.get('ai_calls')}회 (실패 {s.get('ai_errors')}회)")
print("")
print("| 사이트 | 목록 | 방식 | 링크 | 신규 | 상세 성공 | 상세 실패 | 비고 |")
print("|---|---|---|---|---|---|---|---|")
for h in d.get("source_health", []):
    if h.get("manual_only"):
        print(f"| {h.get('company')} | – | 수동 확인 전용 | – | – | – | – | 수집 대상 아님 |")
        continue
    ok = "✅" if h.get("list_ok") else "❌"
    how = "브라우저" if h.get("method") == "browser" else "일반"
    note = ((h.get("error") or "") + " " + (h.get("note") or "")).strip()
    print(f"| {h.get('company')} | {ok} | {how} | {h.get('links_found')} | {h.get('new_found')} "
          f"| {h.get('detail_ok')} | {h.get('detail_failed')} | {note} |")
