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
    "복리후생", "채용절차", "채용안내", "전형안내", "지원방법",
    "자주 묻는 질문", "faq", "공지사항", "보도자료", "뉴스", "이벤트",
    "합격자 발표", "합격자발표", "면접 안내", "설명회", "채용박람회",
    "개인정보처리방침", "개인정보 처리방침", "이용약관", "윤리강령",
    "ir 자료", "실적발표", "공시",
    # 실측(DB손보) 확인: 채용 사이트 메뉴/안내 페이지가 링크 패턴 없이
    # 휴리스틱만으로 걸러질 때 실제로 섞여 들어온 것들
    "채용관홈", "채용관", "인사제도", "신고센터", "모집분야별",
]

DEFAULT_EMPLOYMENT_EXCLUDE = [
    "계약직", "신입", "인턴", "인턴십", "체험형", "아르바이트",
    "파트타이머", "파트타임", "단기", "촉탁", "퇴직인력", "청년인턴",
    "설계사", "보험설계사", "fc 모집", "리크루팅",
]

# 제목에 이 단어가 함께 있으면 위 목록에 걸려도 남긴다
DEFAULT_KEEP_IF = ["경력", "정규직", "experienced", "senior", "manager"]

# 이 단어들은 실제 채용공고 '제목'에 쓰이는 일이 사실상 없다(안내/메뉴 전용).
# "채용"/"모집" 같은 흔한 글자가 "채용관홈"/"모집분야별"처럼 복합어 일부로
# 들어 있어도 채용 신호로 오인하지 않도록, 이 목록은 본문에 실제 채용
# 항목(자격요건 등)이 없는 한 무조건 제외한다.
DEFAULT_ALWAYS_NONJOB = [
    "지원방법", "신고센터", "채용관홈", "채용관", "인사제도", "faq",
    "공지사항", "이용약관", "개인정보처리방침", "모집분야별", "사이트맵",
]

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


def _hits(haystack, words):
    return [w for w in words if w and w in haystack]


def check(job, profile=None):
    """반환: (제외할지, 사유, 단계).
    단계는 'notjob'(채용공고 아님) 또는 'employment'(고용형태).
    제외하지 않으면 (False, "", "")."""
    title = (job.get("title") or "").lower()
    detail_title = (job.get("detail_title") or "").lower()
    body = (job.get("detail_text") or "").lower()
    head = (title + " " + detail_title).strip()
    # 본문 앞부분에 고용형태가 적히는 경우가 많다
    body_head = body[:2000]

    non_job = _cfg(profile, "non_job_posts", DEFAULT_NON_JOB)
    always_nonjob = _cfg(profile, "always_nonjob_titles", DEFAULT_ALWAYS_NONJOB)
    emp_bad = _cfg(profile, "employment_types", DEFAULT_EMPLOYMENT_EXCLUDE)
    keep_if = _cfg(profile, "keep_if_contains", DEFAULT_KEEP_IF)

    has_title_signal = bool(_hit(head, [s.lower() for s in JOB_SIGNALS_TITLE]))
    has_body_signal = bool(_hit(body, [s.lower() for s in JOB_SIGNALS_BODY])) if body else False

    # ── ① 채용공고가 맞는가 ──

    # 실측(DB손보) 확인: "채용관홈", "모집분야별 지원방법" 처럼 안내/메뉴
    # 전용 단어는 "채용"/"모집" 글자를 우연히 포함해도 실제 공고 제목에
    # 쓰이지 않는다. 본문에 진짜 채용 항목이 없는 한 무조건 제외한다.
    always_hit = _hit(head, always_nonjob)
    if always_hit and not has_body_signal:
        return True, f"채용공고 아님 — 제목에 '{always_hit}' 포함, 안내/메뉴성 페이지로 추정", "notjob"

    # non_job 단어가 제목에 2개 이상 겹치면 메뉴를 통째로 긁어온 것으로 본다
    # (예: "채용관 채용관홈 인재상 인사제도 복리후생 모집분야 …").
    # 이 경우 "채용"/"모집" 글자가 우연히 섞여 있어도 신뢰하지 않는다.
    nonjob_hits = _hits(head, non_job) + _hits(head, always_nonjob)
    if len(set(nonjob_hits)) >= 2 and not has_body_signal:
        return True, (f"채용공고 아님 — 제목에 안내성 단어 {len(set(nonjob_hits))}개 "
                      f"({', '.join(sorted(set(nonjob_hits))[:3])} 등) 포함, 메뉴 페이지로 추정"), "notjob"

    # 중요: 제목에 채용/모집 신호가 있으면 non_job 단어가 함께 있어도
    # 제외하지 않는다. "조직문화∙사회공헌 체험형 인턴 모집"처럼 실제 공고
    # 제목에 회사 활동을 나타내는 단어가 섞여 있을 수 있기 때문이다.
    bad = _hit(head, non_job)
    if bad and not has_title_signal:
        return True, f"채용공고 아님 — 제목에 '{bad}' 포함, 채용/모집 표현 없음", "notjob"

    # 제목에도 본문에도 채용공고다운 신호가 전혀 없으면 제외
    if body:
        if not has_title_signal and not has_body_signal:
            return True, ("채용공고 아님 — 제목에 채용/모집 표현이 없고 "
                          "본문에도 담당업무·자격요건·접수기간이 없음"), "notjob"

    # ── ② 지원 대상이 아닌 고용형태 ──
    kept = _hit(head, keep_if)
    emp = _hit(head, emp_bad) or _hit(body_head, emp_bad)
    if emp and not kept:
        where = "제목" if _hit(head, emp_bad) else "본문 앞부분"
        return True, f"고용형태 제외 — {where}에서 '{emp}' 발견 (경력/정규직 표현 없음)", "employment"

    return False, "", ""
