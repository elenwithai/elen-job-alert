"""Claude API(Haiku)로 공고 적합도를 판단한다.

API 키는 환경변수 ANTHROPIC_API_KEY 로만 읽는다. 코드에 절대 넣지 않는다.
호출 실패 시 예외를 밖으로 던지지 않고 status='error'를 돌려주어
전체 자동화가 멈추지 않게 한다.
"""

import os
import re
import json
import time
import random

import requests

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
API_VERSION = "2023-06-01"
MAX_TOKENS = 400
TIMEOUT = 60

SYSTEM_PROMPT = """당신은 채용공고 스크리너입니다.
주어진 지원자 프로필과 채용공고를 대조해 적합 여부를 판단합니다.

반드시 아래 형식의 JSON 객체 하나만 출력하세요. 설명, 인사말,
마크다운 코드펜스 없이 JSON만 출력합니다.

{
  "fit": "yes" 또는 "no",
  "reason": "판단 이유 한 줄. 60자 이내 한국어. 적합이면 왜 맞는지, 부적합이면 왜 아닌지 구체적으로.",
  "role": "직무명을 짧게 정리 (예: FSI 리스크 컨설팅 매니저). 모르면 빈 문자열",
  "deadline": "마감일이 본문에 있으면 YYYY-MM-DD, 상시면 '상시', 없으면 빈 문자열",
  "confidence": "high" 또는 "low"
}

주의: 본문이 채용공고가 아니라 목록/메뉴/오류 페이지로 보이면
fit은 "no", confidence는 "low", reason에 "공고 본문 확인 불가"라고 적으세요."""


def _as_text(value):
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value or "")


def build_user_prompt(profile, job):
    profile_text = _as_text(profile.get("profile_text"))
    rules = _as_text(profile.get("judging_rules"))

    body = job.get("detail_text") or ""
    if body:
        body_block = f"[공고 본문 - 상세 페이지에서 수집]\n{body}"
    else:
        body_block = (
            "[공고 본문 없음 - 상세 페이지 접근 실패. 목록 정보만으로 판단]\n"
            "본문이 없으므로 confidence는 반드시 low로 하세요."
        )

    return f"""[지원자 프로필]
{profile_text}

[판단 기준]
{rules}

[채용공고]
회사: {job.get('company', '')}
목록에 표시된 제목: {job.get('title', '')}
상세 페이지 제목: {job.get('detail_title', '')}
URL: {job.get('url', '')}

{body_block}

위 공고가 이 지원자에게 적합한지 JSON으로 판단하세요."""


def _parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def judge(job, profile, api_key, retries=2):
    """반환: dict(status, fit, reason, role, deadline, confidence)
    status는 'ok' 또는 'error'. error면 화면에 '판단 보류'로 표시된다."""
    if not api_key:
        return {
            "status": "error",
            "fit": "pending",
            "reason": "API 키 미설정 (GitHub Secrets 확인 필요)",
            "role": "", "deadline": "", "confidence": "low",
        }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": build_user_prompt(profile, job)}],
    }

    last_err = "알 수 없는 오류"
    for attempt in range(retries + 1):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                chunks = [
                    b.get("text", "")
                    for b in data.get("content", [])
                    if b.get("type") == "text"
                ]
                parsed = _parse_json("\n".join(chunks))
                if not parsed:
                    last_err = "AI 응답 JSON 파싱 실패"
                    break
                fit = str(parsed.get("fit", "")).strip().lower()
                if fit not in ("yes", "no"):
                    fit = "no"
                return {
                    "status": "ok",
                    "fit": fit,
                    "reason": str(parsed.get("reason", "")).strip()[:200] or "이유 없음",
                    "role": str(parsed.get("role", "")).strip()[:100],
                    "deadline": str(parsed.get("deadline", "")).strip()[:40],
                    "confidence": str(parsed.get("confidence", "")).strip().lower() or "low",
                }
            if resp.status_code in (429, 500, 502, 503, 529):
                last_err = f"API {resp.status_code} (일시적)"
                if attempt < retries:
                    time.sleep((2 ** attempt) * 3 + random.random() * 2)
                    continue
            elif resp.status_code == 401:
                last_err = "API 키 인증 실패(401)"
                break
            elif resp.status_code == 400:
                last_err = "요청 형식 오류(400)"
                break
            else:
                last_err = f"API {resp.status_code}"
                break
        except requests.exceptions.Timeout:
            last_err = "API 타임아웃"
            if attempt < retries:
                time.sleep(3)
                continue
        except requests.exceptions.RequestException as e:
            last_err = f"네트워크 오류: {type(e).__name__}"
            if attempt < retries:
                time.sleep(3)
                continue
        except Exception as e:  # noqa: BLE001 - 자동화가 멈추면 안 됨
            last_err = f"예외: {type(e).__name__}"
            break

    return {
        "status": "error",
        "fit": "pending",
        "reason": f"판단 보류 — {last_err}",
        "role": "", "deadline": "", "confidence": "low",
    }
