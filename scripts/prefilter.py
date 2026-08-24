"""AI 판단에 넘기기 전에 걸러내는 1차 필터.

목적 두 가지
  1) 채용 게시판에 섞여 들어오는 '채용공고가 아닌 글' 제거
     (인사발령, 조직도, 지배구조/가치체계 소개, 공지사항, IR 자료 등)
  2) 애초에 지원 대상이 아닌 고용형태 제거 (계약직·신입·인턴 등)

여기서 걸러낸 공고는 Claude API로 보내지 않으므로 그만큼 비용이 줄어든다.
판단 기준은 config/profile.json 의 auto_exclude 에서 사용자가 수정할 수 있다.
"""

DEFAULT_NON_JOB = [
    "인사발령", "임원인사", "인사이동", "조직개편", "조직도", "지배구조",
    "가치체계", "연혁", "경영진", "이사회", "주주총회", "지속가능경영",
    "회사소개", "사업소개", "브랜드", "비전", "인재상", "핵심가치",
    "복리후생", "채용절차", "채용안내", "전형안내", "지원방법 안내",
    "자주 묻는 질문", "faq", "공지사항", "보도자료", "뉴스", "이벤트",
    "합격자 발표", "합격자발표", "면접 안내", "설명회", "채용박람회",
    "개인정보처리방침", "개인정보 처리방침", "이용약관", "윤리강령",
    "사회공헌", "ir 자료", "실적발표", "공시",
]

DEFAULT_EMPLOYMENT_EXCLUDE = [
    "계약직", "신입", "인턴", "인턴십", "체험형", "아르바이트",
    "파트타이머", "파트타임", "단기", "촉탁", "퇴직인력", "청년인턴",
    "설계사", "보험설계사", "fc 모집", "리크루팅",
]

# 제목에 이 단어가 함께 있으면 위 목록에 걸려도 남긴다
DEFAULT_KEEP_IF = ["경력", "정규직", "experienced", "senior", "manager"]

# 진짜 채용공고라면 보통 들어 있는 단어
JOB_SIGNALS_TITLE = ["채용", "모집", "구인", "recruit", "hiring", "job", "position", "career"]
JOB_SIGNALS_BODY = [
    "담당업무", "주요업무", "수행업무", "자격요건", "지원자격", "우대사항",
    "모집분야", "모집부문", "접수기간", "지원기간", "전형절차", "근무지",
    "responsibilities", "qualifications", "requirements",
]


def _cfg(profile, key, default):
    block = (profile or {}).get("auto_exclude") or {}
    value = block.get(key)
    if isinstance(value, list) and value:
        return [str(v).lower() for v in value]
    return [str(v).lower() for v in default]


def _hit(haystack, words):
    for w in words:
        if w and w in haystack:
            return w
    return ""


def check(job, profile=None):
    """반환: (제외할지, 사유). 제외하지 않으면 (False, "")."""
    title = (job.get("title") or "").lower()
    detail_title = (job.get("detail_title") or "").lower()
    body = (job.get("detail_text") or "").lower()
    head = (title + " " + detail_title).strip()
    # 본문 앞부분에 고용형태가 적히는 경우가 많다
    body_head = body[:2000]

    non_job = _cfg(profile, "non_job_posts", DEFAULT_NON_JOB)
    emp_bad = _cfg(profile, "employment_types", DEFAULT_EMPLOYMENT_EXCLUDE)
    keep_if = _cfg(profile, "keep_if_contains", DEFAULT_KEEP_IF)

    # ── ① 채용공고가 맞는가 ──
    bad = _hit(head, non_job)
    if bad and not _hit(head, [s.lower() for s in JOB_SIGNALS_TITLE]):
        return True, f"자동 제외 — 채용공고가 아닌 게시물로 보입니다 ('{bad}')"

    # 제목에도 본문에도 채용공고다운 신호가 전혀 없으면 제외
    if body:
        has_title_signal = bool(_hit(head, [s.lower() for s in JOB_SIGNALS_TITLE]))
        has_body_signal = bool(_hit(body, [s.lower() for s in JOB_SIGNALS_BODY]))
        if not has_title_signal and not has_body_signal:
            return True, "자동 제외 — 채용공고 형식이 아닙니다 (담당업무·자격요건 등 없음)"
        if bad and not has_body_signal:
            return True, f"자동 제외 — 채용공고가 아닌 게시물로 보입니다 ('{bad}')"

    # ── ② 지원 대상이 아닌 고용형태 ──
    kept = _hit(head, keep_if)
    emp = _hit(head, emp_bad) or _hit(body_head, emp_bad)
    if emp and not kept:
        return True, f"자동 제외 — '{emp}' 공고입니다"

    return False, ""
