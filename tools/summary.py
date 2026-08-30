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
print(f"- 필터 제외: 채용공고 아님 **{s.get('excluded_notjob', 0)}건** / "
      f"고용형태 **{s.get('excluded_employment', 0)}건** / "
      f"마감 **{s.get('excluded_expired', 0)}건** / "
      f"AI 부적합 **{s.get('excluded_ai', 0)}건**")
print("")
print("| 사이트 | 목록 | 방식 | 링크 | 신규 | 상세 성공 | 상세 실패 | 아님 | 고용 | 마감 | 비고 |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
for h in d.get("source_health", []):
    if h.get("manual_only"):
        print(f"| {h.get('company')} | – | 수동 확인 전용 | – | – | – | – | – | – | – | 수집 대상 아님 |")
        continue
    ok = "✅" if h.get("list_ok") else "❌"
    how = "브라우저" if h.get("method") == "browser" else "일반"
    f = h.get("filtered") or {}
    note = ((h.get("error") or "") + " " + (h.get("note") or "")).strip()
    print(f"| {h.get('company')} | {ok} | {how} | {h.get('links_found')} | {h.get('new_found')} "
          f"| {h.get('detail_ok')} | {h.get('detail_failed')} "
          f"| {f.get('notjob', 0)} | {f.get('employment', 0)} | {f.get('expired', 0)} | {note} |")

zero = [h for h in d.get("source_health", []) if h.get("probe")]
if zero:
    print("")
    print("### 링크 0건 사이트 — 원인 진단")
    print("")
    print("| 사이트 | requests | 브라우저 | a태그 | 패턴매칭 | 판정 |")
    print("|---|---|---|---|---|---|")
    for h in zero:
        p2 = h["probe"]
        rq = p2.get("requests_status") or p2.get("requests_error") or "실패"
        br = f"OK({p2.get('browser_html_len')}자)" if p2.get("browser_ok") else (p2.get("browser_error") or "실패")
        print(f"| {h.get('company')} | {rq} | {br} | {p2.get('browser_anchor_count')} "
              f"| {p2.get('matched_by_pattern')} | {p2.get('verdict')} |")
    print("")
    print("#### 각 사이트의 실제 링크 형태 (패턴 수정용)")
    for h in zero:
        links = (h["probe"].get("unique_links_sample") or [])[:10]
        if not links:
            continue
        print(f"- **{h.get('company')}** (현재 패턴: `{h['probe'].get('link_include')}`)")
        for l in links:
            print(f"  - {l.get('text', '')[:40]} → `{l.get('url')}`")

print("")
print("### 사이트별로 실제 잡힌 링크 (앞 3건)")
for h in d.get("source_health", []):
    samples = h.get("sample_links") or []
    if not samples:
        continue
    print(f"- **{h.get('company')}**")
    for sl in samples[:3]:
        print(f"  - {sl.get('title', '')[:50]} → `{sl.get('url', '')}`")
