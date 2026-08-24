#!/usr/bin/env python3
"""채용공고 모니터링 메인 스크립트.

동작 순서
 1) sources.json의 각 목록 페이지를 받아 개별 공고 상세 링크를 추출
 2) 이전 실행에 없던 '신규' 공고에 한해서만 상세 페이지를 직접 방문해 본문 수집
 3) 신규 공고(+이전에 판단 보류된 공고)만 Claude API로 적합도 판단
 4) data/jobs.json (프런트엔드용), data/crawl_report.json (진단용) 저장
"""

import os
import sys
import json
import argparse
import traceback
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fetcher
import extract
import ai_judge
import browser_fetch

KST = timezone(timedelta(hours=9))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
DATA_DIR = os.path.join(ROOT, "data")

# 한 번 실행에서 허용할 최대 AI 호출 수 (비용 안전장치)
MAX_AI_CALLS = int(os.environ.get("MAX_AI_CALLS", "40"))
# 마지막으로 발견된 지 이 일수가 지난 공고는 정리
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "45"))


def now_kst():
    return datetime.now(KST)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        print(f"[경고] {path} JSON 파싱 실패: {e}. 기본값 사용", file=sys.stderr)
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _get_html(session, url, source, renderer, entry, stage):
    """일반 요청 → 필요하면 브라우저 렌더링 순서로 HTML을 가져온다.
    반환: (html, final_url, method, error)"""
    mode = source.get("render_mode", "auto")

    if mode != "always":
        res = fetcher.fetch(session, url)
        fetcher.polite_sleep()
        if res.ok:
            return res.text, res.final_url or url, "requests", ""
        plain_error = res.error or "접속 실패"
        if mode == "never":
            return None, url, "requests", plain_error
    else:
        plain_error = ""

    # 브라우저 폴백
    html, err = renderer.render(
        url,
        wait_selector=source.get("render_wait_selector"),
        wait_ms=source.get("render_wait_ms", browser_fetch.DEFAULT_WAIT_MS),
    )
    if html:
        entry["fallback_used"] = True
        return html, url, "browser", ""
    return None, url, "browser", (plain_error or err or "접속 실패")


def crawl_source(session, source, known_ids, report, renderer, diagnose=False):
    """한 소스에 대해 목록 크롤 + 신규 건 상세 크롤.
    (신규 job dict 리스트, 이번에 발견된 id 집합) 반환"""
    key = source["key"]
    company = source["company"]
    url = source["url"]

    entry = {
        "key": key,
        "company": company,
        "url": url,
        "list_ok": False,
        "method": "",
        "fallback_used": False,
        "links_found": 0,
        "new_found": 0,
        "detail_ok": 0,
        "detail_failed": 0,
        "detail_fetch_enabled": source.get("detail_fetch", True),
        "deferred": 0,
        "manual_only": False,
        "self_links_skipped": 0,
        "error": "",
        "note": "",
    }

    # 수동 확인 전용 사이트는 아예 수집하지 않는다
    if source.get("manual_only"):
        entry["manual_only"] = True
        entry["note"] = "수동 확인 전용. 수집·AI 판단 대상이 아니며 목록에서 직접 눌러 확인합니다."
        report.append(entry)
        return [], set()

    min_links = source.get("min_expected_links", 1)
    mode = source.get("render_mode", "auto")

    html, final_url, method, err = _get_html(session, url, source, renderer, entry, "list")
    entry["method"] = method
    if not html:
        entry["error"] = err
        entry["note"] = "URL이 바뀌었거나 차단됐을 수 있습니다. sources.json의 url을 확인하세요."
        report.append(entry)
        return [], set()

    entry["list_ok"] = True
    try:
        links = extract.extract_links(html, final_url, source)
    except Exception as e:  # noqa: BLE001
        entry["error"] = f"링크 추출 실패: {type(e).__name__}"
        report.append(entry)
        return [], set()

    # 링크가 없거나 비정상적으로 적으면 브라우저로 한 번 더 시도
    if len(links) < min_links and method == "requests" and mode == "auto":
        print(f"    링크 {len(links)}건 — 브라우저 렌더링으로 재시도")
        rendered, rerr = renderer.render(
            url,
            wait_selector=source.get("render_wait_selector"),
            wait_ms=source.get("render_wait_ms", browser_fetch.DEFAULT_WAIT_MS),
        )
        if rendered:
            try:
                relinks = extract.extract_links(rendered, final_url, source)
            except Exception:  # noqa: BLE001
                relinks = []
            if len(relinks) > len(links):
                links = relinks
                html = rendered
                method = "browser"
                entry["method"] = "browser"
                entry["fallback_used"] = True
                print(f"    브라우저 렌더링 후 링크 {len(links)}건")
        elif rerr:
            entry["note"] = f"브라우저 재시도 실패: {rerr}. "

    entry["links_found"] = len(links)
    if not links:
        entry["note"] += (
            "링크 0건. 일반 요청과 브라우저 렌더링 모두 실패했습니다. "
            "link_include 패턴이나 url을 확인하거나, manual_only: true 로 전환하세요."
        )
        if diagnose:
            entry["sample_html_head"] = (html or "")[:3000]
        report.append(entry)
        return [], set()

    use_browser_for_detail = (method == "browser") or mode == "always"

    seen_ids = set()
    new_jobs = []
    detail_budget = source.get("max_new_details", 15)

    list_norm = extract.normalize_url(url)
    for link in links:
        # 최종 방어선: 어떤 경우에도 목록 페이지 자체를 공고로 저장하지 않는다
        if extract.normalize_url(link["url"]) == list_norm:
            entry["self_links_skipped"] = entry.get("self_links_skipped", 0) + 1
            continue
        jid = extract.job_id(link["url"], company, link["title"])
        seen_ids.add(jid)
        if jid in known_ids:
            continue

        job = {
            "id": jid,
            "source_key": key,
            "company": company,
            "title": link["title"],
            "url": link["url"],
            "detail_title": "",
            "detail_text": "",
            "detail_status": "skipped",
            "deadline_guess": "",
        }

        if source.get("detail_fetch", True) and detail_budget > 0:
            detail_budget -= 1
            dhtml = None
            derr = ""
            if not use_browser_for_detail:
                dres = fetcher.fetch(session, link["url"])
                fetcher.polite_sleep()
                if dres.ok:
                    dhtml = dres.text
                else:
                    derr = dres.error or "접속 실패"
            if dhtml is None:
                dhtml, rerr = renderer.render(
                    link["url"],
                    wait_selector=source.get("detail_wait_selector"),
                    wait_ms=source.get("render_wait_ms", browser_fetch.DEFAULT_WAIT_MS),
                    scroll=False,
                )
                if dhtml is None:
                    derr = derr or rerr

            if dhtml:
                try:
                    parsed = extract.extract_detail(dhtml)
                    if len(parsed["text"]) < 150:
                        job["detail_status"] = "thin"
                        entry["detail_failed"] += 1
                    else:
                        job["detail_status"] = "ok"
                        entry["detail_ok"] += 1
                    job["detail_title"] = parsed["title"]
                    job["detail_text"] = parsed["text"]
                    job["deadline_guess"] = extract.guess_deadline(parsed["text"])
                except Exception:  # noqa: BLE001
                    job["detail_status"] = "parse_error"
                    entry["detail_failed"] += 1
            else:
                job["detail_status"] = f"fetch_error({derr})"
                entry["detail_failed"] += 1
        elif not source.get("detail_fetch", True):
            # 설정에서 명시적으로 상세 수집을 끈 경우에만 목록 정보로 판단한다
            job["detail_status"] = "disabled_by_config"
        else:
            # 상세 방문 한도를 넘긴 신규 공고는 판단하지 않고 다음 실행으로 넘긴다.
            # 본문 없이 제목만으로 AI에 넘기면 안 되기 때문이다.
            entry["deferred"] = entry.get("deferred", 0) + 1
            continue

        new_jobs.append(job)

    entry["new_found"] = len(new_jobs)
    if entry.get("deferred"):
        entry["note"] += (
            f"신규 {entry['deferred']}건은 상세 방문 한도를 넘겨 다음 실행으로 넘겼습니다 "
            "(제목만으로 판단하지 않습니다). max_new_details 를 올리면 한 번에 처리됩니다. "
        )
    if entry["detail_ok"] == 0 and entry["detail_failed"] > 0:
        entry["note"] += "상세 본문을 한 건도 못 가져왔습니다. 이 회사는 목록 정보만으로 판단됩니다."
    report.append(entry)
    return new_jobs, seen_ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnose", action="store_true",
                        help="링크 0건인 소스의 HTML 앞부분을 리포트에 저장")
    parser.add_argument("--dry-run", action="store_true",
                        help="AI 호출 없이 크롤링만 수행")
    args = parser.parse_args()

    sources_cfg = load_json(os.path.join(CONFIG_DIR, "sources.json"), {"sources": []})
    profile = load_json(os.path.join(CONFIG_DIR, "profile.json"), {})
    state = load_json(os.path.join(DATA_DIR, "jobs.json"), {"jobs": []})

    existing = {j["id"]: j for j in state.get("jobs", []) if j.get("id")}
    known_ids = set(existing.keys())

    sources = [s for s in sources_cfg.get("sources", []) if s.get("enabled", True)]
    crawlable = [s for s in sources if not s.get("manual_only")]
    manual = [s for s in sources if s.get("manual_only")]
    print(f"[i] 활성 소스 {len(sources)}개 (수집 {len(crawlable)} / 수동 확인 전용 {len(manual)}), "
          f"기존 공고 {len(existing)}건")

    session = fetcher.make_session()
    renderer = browser_fetch.Renderer()
    report = []
    all_new = []
    today = now_kst()

    for source in sources:
        print(f"[>] {source['company']} 크롤링...")
        try:
            new_jobs, seen_ids = crawl_source(
                session, source, known_ids, report, renderer, args.diagnose)
        except Exception as e:  # noqa: BLE001
            print(f"[!] {source['key']} 예외: {e}", file=sys.stderr)
            traceback.print_exc()
            report.append({
                "key": source["key"], "company": source["company"], "url": source["url"],
                "list_ok": False, "method": "", "fallback_used": False,
                "links_found": 0, "new_found": 0,
                "detail_ok": 0, "detail_failed": 0, "manual_only": False,
                "error": f"예외: {type(e).__name__}", "note": "",
            })
            continue

        for jid in seen_ids:
            if jid in existing:
                existing[jid]["last_seen"] = today.strftime("%Y-%m-%d")
        all_new.extend(new_jobs)

    renderer.close()
    if renderer.pages_rendered:
        print(f"[i] 브라우저 렌더링 {renderer.pages_rendered}페이지 사용")
    print(f"[i] 신규 공고 {len(all_new)}건")

    # 이전에 판단 보류된 건도 재시도 대상에 포함
    retry = [j for j in existing.values() if j.get("ai_status") == "error"]
    if retry:
        print(f"[i] 이전 판단 보류 {len(retry)}건 재시도 대상")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        print("[!] ANTHROPIC_API_KEY 없음 — 모든 신규 공고는 '판단 보류' 처리됩니다.", file=sys.stderr)

    queue = all_new + retry
    calls = 0
    ai_errors = 0

    for job in queue:
        if args.dry_run:
            verdict = {"status": "error", "fit": "pending", "reason": "dry-run",
                       "role": "", "deadline": "", "confidence": "low"}
        elif calls >= MAX_AI_CALLS:
            verdict = {"status": "error", "fit": "pending",
                       "reason": "판단 보류 — 이번 실행 AI 호출 한도 초과, 다음 실행에서 재시도",
                       "role": "", "deadline": "", "confidence": "low"}
        else:
            verdict = ai_judge.judge(job, profile, api_key)
            calls += 1
            if verdict["status"] == "error":
                ai_errors += 1

        job["fit"] = verdict["fit"]
        job["reason"] = verdict["reason"]
        job["role"] = verdict["role"]
        job["confidence"] = verdict["confidence"]
        job["ai_status"] = verdict["status"]
        job["deadline"] = verdict["deadline"] or job.get("deadline_guess", "")
        job["judged_at"] = today.strftime("%Y-%m-%d %H:%M")
        job.setdefault("first_seen", today.strftime("%Y-%m-%d"))
        job["last_seen"] = today.strftime("%Y-%m-%d")

    print(f"[i] AI 호출 {calls}회 (실패 {ai_errors}회)")

    # 병합
    for job in all_new:
        existing[job["id"]] = job

    # 오래된 공고 정리 + 프런트엔드에 불필요한 본문 제거
    cutoff = today - timedelta(days=RETENTION_DAYS)
    output_jobs = []
    for j in existing.values():
        try:
            last = datetime.strptime(j.get("last_seen", "1970-01-01"), "%Y-%m-%d").replace(tzinfo=KST)
        except ValueError:
            last = today
        if last < cutoff:
            continue
        slim = {k: v for k, v in j.items() if k not in ("detail_text",)}
        slim["has_detail"] = j.get("detail_status") == "ok"
        output_jobs.append(slim)

    output_jobs.sort(key=lambda j: (j.get("first_seen", ""), j.get("company", "")), reverse=True)

    fit_yes = sum(1 for j in output_jobs if j.get("fit") == "yes")
    pending = sum(1 for j in output_jobs if j.get("fit") == "pending")

    payload = {
        "updated_at": today.strftime("%Y-%m-%d %H:%M"),
        "updated_at_iso": today.isoformat(),
        "stats": {
            "total": len(output_jobs),
            "fit_yes": fit_yes,
            "pending": pending,
            "new_this_run": len(all_new),
            "ai_calls": calls,
            "ai_errors": ai_errors,
            "browser_pages": renderer.pages_rendered,
        },
        "sources": [
            {
                "key": s["key"], "company": s["company"], "url": s["url"],
                "memo": s.get("memo", ""),
                "manual_only": bool(s.get("manual_only", False)),
            }
            for s in sources_cfg.get("sources", []) if s.get("enabled", True)
        ],
        # 앱 화면에서 sources.json 을 무손실로 다시 만들 수 있도록 설정 원본을 싣는다
        "sources_config": sources_cfg,
        "source_health": [
            {k: v for k, v in r.items() if k != "sample_html_head"} for r in report
        ],
        "jobs": output_jobs,
    }

    save_json(os.path.join(DATA_DIR, "jobs.json"), payload)
    save_json(os.path.join(DATA_DIR, "crawl_report.json"), {
        "generated_at": today.strftime("%Y-%m-%d %H:%M"),
        "sources": report,
    })

    print(f"[✓] 완료 — 전체 {len(output_jobs)}건 / 추천 {fit_yes}건 / 보류 {pending}건")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        # 자동화 자체가 죽는 것보다 로그를 남기고 정상 종료하는 편이 낫다
        sys.exit(0)
