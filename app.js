/* 채용공고 모니터 — 클라이언트 로직
   읽음/숨김/모니터링 페이지 편집 내용은 이 브라우저의 localStorage에만
   저장됩니다. 서버 자동수집(GitHub Actions)은 config/sources.json 을 보므로,
   편집 후에는 "sources.json 복사" 로 파일에 반영해야 수집에도 적용됩니다. */

(function () {
  "use strict";

  var K_SEEN = "eja_seen_v1";
  var K_HIDDEN = "eja_hidden_v1";
  var K_FILTER = "eja_filter_v1";
  var K_SRC = "eja_srcpatch_v1";
  var K_TAB = "eja_tab_v1";
  var K_DELETED = "eja_deleted_v1";

  // 마감일을 못 읽은 공고는 발견 후 이 일수가 지나면 '마감'으로 본다 (서버와 동일 기준)
  var STALE_DAYS = 30;

  var DEBUG = /[?&]debug=1/.test(location.search);

  var state = {
    data: null,
    tab: "jobs",
    filter: "unseen",
    seen: loadSet(K_SEEN),
    hidden: loadSet(K_HIDDEN),
    deleted: loadSet(K_DELETED),
    patch: loadPatch(),
    editingKey: null
  };

  /* ── 저장소 ─────────────────────────────────────────── */

  function loadSet(key) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? new Set(JSON.parse(raw)) : new Set();
    } catch (e) { return new Set(); }
  }

  function saveSet(key, set) {
    try { localStorage.setItem(key, JSON.stringify(Array.from(set))); } catch (e) { /* 무시 */ }
  }

  function emptyPatch() { return { add: [], edit: {}, del: [] }; }

  function loadPatch() {
    try {
      var raw = localStorage.getItem(K_SRC);
      if (!raw) return emptyPatch();
      var p = JSON.parse(raw);
      return {
        add: Array.isArray(p.add) ? p.add : [],
        edit: p.edit && typeof p.edit === "object" ? p.edit : {},
        del: Array.isArray(p.del) ? p.del : []
      };
    } catch (e) { return emptyPatch(); }
  }

  function savePatch() {
    try { localStorage.setItem(K_SRC, JSON.stringify(state.patch)); } catch (e) { /* 무시 */ }
  }

  function patchCount() {
    return state.patch.add.length + Object.keys(state.patch.edit).length + state.patch.del.length;
  }

  /* ── 유틸 ───────────────────────────────────────────── */

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function byId(id) { return document.getElementById(id); }

  var ICONS = {
    edit: '<path d="M12.5 2.6a1.6 1.6 0 0 1 2.3 2.3l-.9.9-2.3-2.3.9-.9Z"/>' +
          '<path d="M10.6 4.5 3.2 11.9 2.4 15l3.1-.8 7.4-7.4-2.3-2.3Z"/>',
    del:  '<path d="M4.2 4.2 13.8 13.8M13.8 4.2 4.2 13.8" stroke="currentColor" ' +
          'stroke-width="1.9" stroke-linecap="round" fill="none"/>'
  };

  function iconBtn(kind, label) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "act-btn";
    b.title = label;
    b.setAttribute("aria-label", label);
    b.innerHTML = '<svg viewBox="0 0 18 18" width="17" height="17" aria-hidden="true" ' +
                  'fill="currentColor">' + ICONS[kind] + '</svg>';
    return b;
  }

  function toast(msg, opts) {
    opts = opts || {};
    var t = byId("toast");
    t.textContent = "";
    t.appendChild(el("span", "toast-msg", msg));
    if (opts.actionLabel) {
      var a = el("button", "toast-action", opts.actionLabel);
      a.type = "button";
      a.addEventListener("click", function () {
        t.hidden = true;
        clearTimeout(toast._t);
        if (opts.onAction) opts.onAction();
      });
      t.appendChild(a);
    }
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { t.hidden = true; }, opts.ms || 3200);
  }

  /* 네이티브 confirm()은 아이프레임·일부 모바일 환경에서 차단되면
     자동으로 '취소'가 되어 동작이 통째로 무시된다. 직접 만든 확인창을 쓴다. */
  function askConfirm(title, body, okLabel, onOk) {
    var wrap = el("div", "sheet");
    var bd = el("div", "sheet-backdrop");
    var panel = el("div", "sheet-panel confirm-panel");
    panel.appendChild(el("h2", "sheet-title", title));
    if (body) panel.appendChild(el("p", "sync-body", body));

    var acts = el("div", "sheet-actions");
    var ok = el("button", "danger-btn", okLabel || "확인");
    ok.type = "button";
    var cancel = el("button", "ghost-btn", "취소");
    cancel.type = "button";
    acts.appendChild(ok);
    acts.appendChild(cancel);
    panel.appendChild(acts);

    wrap.appendChild(bd);
    wrap.appendChild(panel);
    document.body.appendChild(wrap);

    function close() { if (wrap.parentNode) document.body.removeChild(wrap); }
    ok.addEventListener("click", function () { close(); onOk(); });
    cancel.addEventListener("click", close);
    bd.addEventListener("click", close);
    setTimeout(function () { ok.focus(); }, 40);
  }

  function staleDays() {
    var s = state.data && state.data.stats;
    return (s && s.stale_days) || STALE_DAYS;
  }

  /* 한국시간 기준 '오늘'. 휴대폰 시간대가 무엇이든 KST 날짜로 맞춘다. */
  function kstTodayUTC() {
    var now = new Date();
    var k = new Date(now.getTime() + (9 * 60 + now.getTimezoneOffset()) * 60000);
    return Date.UTC(k.getFullYear(), k.getMonth(), k.getDate());
  }

  function ymdToUTC(dateStr) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dateStr || "")) return null;
    var p = dateStr.split("-");
    var t = Date.UTC(+p[0], +p[1] - 1, +p[2]);
    return isNaN(t) ? null : t;
  }

  function daysSince(dateStr) {
    var t = ymdToUTC(dateStr);
    if (t === null) return null;
    return Math.round((kstTodayUTC() - t) / 86400000);
  }

  /* 마감 여부. 마감일을 읽었으면 그 날짜로, 못 읽었으면
     발견일로부터 staleDays 경과 여부로 판단한다. (서버 로직과 동일) */
  function isExpired(job) {
    var left = daysUntil(job.deadline);
    if (left !== null) return left < 0;
    var since = daysSince(job.first_seen);
    return since !== null && since > staleDays();
  }

  /* 카드 상단 배지에 쓸 남은 일수 라벨 */
  function deadlineBadge(job) {
    var left = daysUntil(job.deadline);
    if (left !== null) {
      if (left < 0) return { text: "마감", cls: "d-over" };
      if (left === 0) return { text: "D-DAY", cls: "d-urgent" };
      if (left <= 3) return { text: "D-" + left, cls: "d-urgent" };
      if (left <= 7) return { text: "D-" + left, cls: "d-soon" };
      return { text: "D-" + left, cls: "d-far" };
    }
    if (/상시|수시|채용시/.test(job.deadline || "")) {
      return { text: "상시", cls: "d-open" };
    }
    var since = daysSince(job.first_seen);
    if (since !== null && since > staleDays()) return { text: "기한 경과", cls: "d-over" };
    return { text: "마감일 미확인", cls: "d-none" };
  }

  /* 마감 임박순 → 같으면 최신 발견순 */
  function sortJobs(list) {
    return list.slice().sort(function (a, b) {
      var la = daysUntil(a.deadline);
      var lb = daysUntil(b.deadline);
      if (la === null && lb !== null) return 1;
      if (lb === null && la !== null) return -1;
      if (la !== null && lb !== null && la !== lb) return la - lb;
      return String(b.first_seen || "").localeCompare(String(a.first_seen || ""));
    });
  }

  /* 남은 일수를 '달력 날짜 차이'로 계산한다.
     밀리초 차이로 재면 마감 당일 자정을 넘긴 공고가 하루 더 D-DAY로 남는다. */
  function daysUntil(dateStr) {
    var t = ymdToUTC(dateStr);
    if (t === null) return null;
    return Math.round((t - kstTodayUTC()) / 86400000);
  }

  /* 공고 URL이 모니터링 목록의 회사 URL과 같으면 잘못 매핑된 것이다.
     정상이라면 항상 개별 상세 페이지 URL이어야 한다. */
  function isListUrl(u) {
    if (!u) return false;
    var norm = String(u).replace(/#.*$/, "").replace(/\/+$/, "");
    var d = state.data || {};
    var list = (d.sources || []).concat(
      (d.sources_config && d.sources_config.sources) || []);
    for (var i = 0; i < list.length; i++) {
      if (String(list[i].url || "").replace(/#.*$/, "").replace(/\/+$/, "") === norm) return true;
    }
    return false;
  }

  function gradeOf(job) {
    if (job.fit === "yes") return "fit";
    if (job.fit === "pending" || job.fit === "unjudged") return "pend";
    return "rej";
  }

  function slugKey(company) {
    var base = (company || "src").toLowerCase()
      .replace(/[^a-z0-9가-힣]+/g, "_").replace(/^_|_$/g, "").slice(0, 20);
    if (!/^[a-z0-9_]+$/.test(base)) base = "src";
    return base + "_" + Date.now().toString(36).slice(-5);
  }

  /* ── 모니터링 페이지: 서버 설정 + 로컬 편집 병합 ────── */

  var NEW_SOURCE_DEFAULTS = {
    enabled: true,
    manual_only: false,
    detail_fetch: true,
    render_mode: "auto",
    min_expected_links: 1,
    link_include: [],
    link_exclude: [],
    max_new_details: 15
  };

  function baseConfig() {
    var d = state.data || {};
    if (d.sources_config && Array.isArray(d.sources_config.sources)) return d.sources_config;
    return { sources: (d.sources || []).map(function (s) {
      var o = {}; for (var k in NEW_SOURCE_DEFAULTS) o[k] = NEW_SOURCE_DEFAULTS[k];
      o.key = s.key; o.company = s.company; o.url = s.url; o.memo = s.memo || "";
      o.manual_only = !!s.manual_only;
      return o;
    }) };
  }

  /* 화면·내보내기 양쪽이 쓰는 최종 목록 */
  function mergedSources() {
    var cfg = baseConfig();
    var out = [];
    (cfg.sources || []).forEach(function (s) {
      if (state.patch.del.indexOf(s.key) !== -1) return;
      var patch = state.patch.edit[s.key];
      var merged = {};
      for (var k in s) merged[k] = s[k];
      if (patch) {
        for (var p in patch) merged[p] = patch[p];
        merged._flag = "edited";
      }
      out.push(merged);
    });
    state.patch.add.forEach(function (s) {
      var copy = {};
      for (var k in s) copy[k] = s[k];
      copy._flag = "added";
      out.push(copy);
    });
    return out;
  }

  function exportConfig() {
    var cfg = baseConfig();
    var out = {};
    for (var k in cfg) if (k !== "sources") out[k] = cfg[k];
    out.sources = mergedSources().map(function (s) {
      var c = {};
      for (var k in s) if (k !== "_flag") c[k] = s[k];
      return c;
    });
    return JSON.stringify(out, null, 2) + "\n";
  }

  function ghEditUrl() {
    var m = location.hostname.match(/^([^.]+)\.github\.io$/);
    if (!m) return "";
    var seg = location.pathname.split("/").filter(Boolean);
    var repo = seg.length ? seg[0] : (m[1] + ".github.io");
    return "https://github.com/" + m[1] + "/" + repo + "/edit/main/config/sources.json";
  }

  /* ── 공고 카드 ──────────────────────────────────────── */

  function buildCard(job) {
    var card = el("article", "card grade-" + gradeOf(job));
    card.dataset.id = job.id;
    if (state.seen.has(job.id)) card.classList.add("is-read");

    var top = el("div", "card-top");
    top.appendChild(el("span", "company", job.company || "―"));
    top.appendChild(el("span", "spacer"));

    var badge = deadlineBadge(job);
    top.appendChild(el("span", "dday " + badge.cls, badge.text));

    var delBtn = iconBtn("del", (job.title || "이 공고") + " 삭제");
    delBtn.className = "act-btn card-del";
    delBtn.addEventListener("click", function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      askConfirm("이 공고를 삭제할까요?",
        (job.title || "") + "\n\n목록에서 완전히 사라지며, 내일 다시 수집되더라도 " +
        "이 공고는 다시 나타나지 않습니다.",
        "삭제", function () { deleteJob(job.id); });
    });
    top.appendChild(delBtn);
    card.appendChild(top);

    var link = el("a", "job-title", job.title || "(제목 없음)");
    link.href = job.url || "#";
    if (isListUrl(job.url)) card.dataset.listUrl = "1";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.addEventListener("click", function () { markSeen(job.id, card); });
    card.appendChild(link);

    var meta = el("div", "meta");
    if (job.role) meta.appendChild(el("span", null, job.role));
    if (job.deadline) meta.appendChild(el("span", null, "마감 " + job.deadline));
    if (job.first_seen) meta.appendChild(el("span", null, "발견 " + job.first_seen));
    if (meta.childNodes.length) card.appendChild(meta);

    if (job.reason) card.appendChild(el("p", "reason", job.reason));

    var chips = el("div", "chips");
    if (job.fit === "unjudged" && job.has_detail) {
      chips.appendChild(el("span", "chip read", "본문 수집 완료"));
    }
    if (job.has_detail === false && job.fit !== "pending" && job.fit !== "unjudged") {
      chips.appendChild(el("span", "chip warn", "목록 정보만으로 판단"));
    }
    if (job.confidence === "low" && job.fit === "yes") {
      chips.appendChild(el("span", "chip warn", "확신 낮음"));
    }
    var readChip = el("span", "chip read", "읽음");
    readChip.hidden = !state.seen.has(job.id);
    chips.appendChild(readChip);
    chips.appendChild(el("span", "spacer"));

    var hideBtn = el("button", "ghost-btn", "숨기기");
    hideBtn.type = "button";
    hideBtn.addEventListener("click", function () {
      state.hidden.add(job.id);
      saveSet(K_HIDDEN, state.hidden);
      render();
    });
    chips.appendChild(hideBtn);
    card.appendChild(chips);
    return card;
  }

  /* 링크를 누른 즉시 읽음 처리하되, 읽는 도중 카드가 사라지지 않도록
     목록에서 바로 빼지 않고 흐리게만 표시한다. */
  function deleteJob(id) {
    state.deleted.add(id);
    saveSet(K_DELETED, state.deleted);
    render();
    toast("공고를 삭제했습니다", {
      actionLabel: "실행취소", ms: 5000,
      onAction: function () {
        state.deleted.delete(id);
        saveSet(K_DELETED, state.deleted);
        render();
      }
    });
  }

  function markSeen(id, card) {
    if (state.seen.has(id)) return;
    state.seen.add(id);
    saveSet(K_SEEN, state.seen);
    if (card) {
      card.classList.add("is-read");
      var chip = card.querySelector(".chip.read");
      if (chip) chip.hidden = false;
    }
    updateCounts();
  }

  /* ── 렌더 ───────────────────────────────────────────── */

  function visibleJobs(fitValue) {
    if (!state.data) return [];
    return sortJobs((state.data.jobs || []).filter(function (j) {
      if (state.deleted.has(j.id)) return false;   // 삭제는 전체 보기에서도 제외
      if (state.hidden.has(j.id)) return false;
      if (isExpired(j)) return false;              // 마감 건은 마감 섹션으로
      if (j.fit !== fitValue) return false;
      if (fitValue === "yes" && state.filter === "unseen" && state.seen.has(j.id)) return false;
      return true;
    }));
  }

  /* 마감된 공고 — 지워지지 않고 접힌 섹션에 남는다 */
  function expiredJobs() {
    if (!state.data) return [];
    return sortJobs((state.data.jobs || []).filter(function (j) {
      if (state.deleted.has(j.id)) return false;
      if (!isExpired(j)) return false;
      return j.fit !== "no";
    }));
  }

  function fillList(node, jobs, emptyText) {
    node.textContent = "";
    if (!jobs.length) {
      node.appendChild(el("p", "empty", emptyText));
      return;
    }
    jobs.forEach(function (j) { node.appendChild(buildCard(j)); });
  }

  function updateCounts() {
    if (!state.data) return;
    var all = (state.data.jobs || []).filter(function (j) {
      return !state.hidden.has(j.id) && !state.deleted.has(j.id) && !isExpired(j);
    });
    var yes = all.filter(function (j) { return j.fit === "yes"; });
    var unseenYes = yes.filter(function (j) { return !state.seen.has(j.id); });
    byId("recCount").textContent = state.filter === "unseen"
      ? unseenYes.length + "건"
      : unseenYes.length + " / " + yes.length + "건";

    var badge = byId("tabBadge");
    badge.textContent = unseenYes.length > 99 ? "99+" : String(unseenYes.length);
    badge.hidden = unseenYes.length === 0;
  }

  function render() {
    var d = state.data;
    if (!d) return;

    byId("updatedAt").textContent = "마지막 업데이트: " + (d.updated_at || "―") + " KST";

    var emptyMsg;
    if (d.stats && d.stats.crawl_only) {
      emptyMsg = "아직 AI 판단을 하지 않아 추천 공고가 없습니다. 아래 'AI 판단 전' 섹션을 보세요.";
    } else {
      emptyMsg = state.filter === "unseen"
        ? "안 본 추천 공고가 없습니다. '전체'를 눌러 지난 공고를 볼 수 있습니다."
        : "AI가 적합하다고 판단한 공고가 아직 없습니다.";
    }
    fillList(byId("recList"), visibleJobs("yes"), emptyMsg);

    var unjudged = visibleJobs("unjudged");
    byId("unjudgedSection").hidden = unjudged.length === 0;
    byId("unjCount").textContent = unjudged.length + "건";
    if (unjudged.length) {
      byId("unjNote").textContent = (d.stats && d.stats.crawl_only)
        ? "수집은 끝났지만 아직 AI 판단을 하지 않은 공고입니다. 상세 본문까지 받아두었으므로, "
          + "ANTHROPIC_API_KEY 를 등록하고 다시 실행하면 이 본문 그대로 판단합니다."
        : "AI 호출 한도를 넘겨 다음 실행으로 넘긴 공고입니다.";
      fillList(byId("unjList"), unjudged, "");
    }

    var notice = byId("crawlOnlyNotice");
    if (d.stats && d.stats.crawl_only) {
      notice.hidden = false;
      notice.textContent = "수집 전용으로 실행된 결과입니다 — API 키가 없어 AI 판단을 건너뛰었습니다. "
        + "수집된 공고는 아래 'AI 판단 전'에서 확인할 수 있습니다.";
    } else {
      notice.hidden = true;
    }

    var pending = visibleJobs("pending");
    byId("pendingSection").hidden = pending.length === 0;
    byId("pendCount").textContent = pending.length + "건";
    if (pending.length) fillList(byId("pendList"), pending, "");

    var expired = expiredJobs();
    byId("expCount").textContent = expired.length;
    byId("expNote").textContent =
      "마감일이 지났거나, 마감일을 못 읽은 채 발견 후 " + staleDays() +
      "일이 지난 공고입니다. 삭제되지 않고 여기 남습니다.";
    fillList(byId("expList"), expired, "마감된 공고가 없습니다.");

    var rejected = visibleJobs("no");
    byId("rejCount").textContent = rejected.length;
    fillList(byId("rejList"), rejected, "제외된 공고가 없습니다.");

    renderSources();
    renderHealth(d.source_health || []);

    var hiddenLine = byId("hiddenLine");
    hiddenLine.textContent = "";
    var anyLine = false;
    if (state.hidden.size) {
      anyLine = true;
      hiddenLine.appendChild(document.createTextNode("숨긴 공고 " + state.hidden.size + "건 · "));
      var restore = el("button", "link-btn", "모두 복구");
      restore.type = "button";
      restore.addEventListener("click", function () {
        state.hidden.clear();
        saveSet(K_HIDDEN, state.hidden);
        render();
      });
      hiddenLine.appendChild(restore);
    }
    if (state.deleted.size) {
      if (anyLine) hiddenLine.appendChild(el("br"));
      anyLine = true;
      hiddenLine.appendChild(document.createTextNode("삭제한 공고 " + state.deleted.size + "건 · "));
      var undel = el("button", "link-btn", "모두 복구");
      undel.type = "button";
      undel.addEventListener("click", function () {
        state.deleted.clear();
        saveSet(K_DELETED, state.deleted);
        render();
        toast("삭제한 공고를 모두 복구했습니다");
      });
      hiddenLine.appendChild(undel);
    }
    hiddenLine.hidden = !anyLine;

    var s = d.stats || {};
    byId("footMeta").textContent =
      "수집 " + (s.total || 0) + "건 · 이번 실행 신규 " + (s.new_this_run || 0) +
      "건 · AI 호출 " + (s.ai_calls || 0) + "회" +
      (s.unjudged ? " · 판단 전 " + s.unjudged + "건" : "") +
      (s.browser_pages ? " · 브라우저 " + s.browser_pages + "p" : "");

    updateCounts();
    runDebug();
  }

  function renderSources() {
    var list = byId("srcList");
    var sources = mergedSources().filter(function (s) { return s.enabled !== false; });
    list.textContent = "";
    byId("srcCount").textContent = sources.length + "곳";

    if (!sources.length) {
      list.appendChild(el("p", "empty", "등록된 채용 페이지가 없습니다. '+ 추가'로 등록하세요."));
    }

    sources.forEach(function (s, idx) {
      var li = el("li", "src-item");

      // No. — 배열 순서로 매번 다시 계산하므로 추가/삭제 후 자동 재정렬된다
      li.appendChild(el("span", "src-no", String(idx + 1)));

      // 이동 영역: 한 번 누르면 곧바로 새 탭으로 이동
      var a = el("a", "src-link");
      a.href = s.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.appendChild(el("span", "src-name", s.company));
      if (s.manual_only) a.appendChild(el("span", "chip warn", "수동 확인 전용"));
      if (s._flag === "added") a.appendChild(el("span", "src-flag added", "추가됨"));
      if (s._flag === "edited") a.appendChild(el("span", "src-flag edited", "수정됨"));
      a.appendChild(el("span", "src-arrow", "↗"));
      if (s.memo) a.appendChild(el("span", "src-memo", s.memo));
      li.appendChild(a);

      // 조작 영역: 이동 영역과 겹치지 않는 별도 버튼
      var acts = el("div", "src-actions");

      var edit = iconBtn("edit", s.company + " 수정");
      edit.addEventListener("click", function (ev) {
        ev.preventDefault(); ev.stopPropagation();
        openSheet(s);
      });
      acts.appendChild(edit);

      var del = iconBtn("del", s.company + " 삭제");
      del.addEventListener("click", function (ev) {
        ev.preventDefault(); ev.stopPropagation();
        removeSource(s.key, s.company);
      });
      acts.appendChild(del);

      li.appendChild(acts);
      list.appendChild(li);
    });

    renderSyncBanner();
  }

  function renderSyncBanner() {
    var n = patchCount();
    var banner = byId("syncBanner");
    byId("tabDot").hidden = n === 0;
    if (!n) {
      banner.hidden = true;
      byId("cfgOut").hidden = true;
      return;
    }
    banner.hidden = false;
    byId("syncTitle").textContent =
      "이 휴대폰에서만 반영된 변경 " + n + "건 — 자동 수집에는 아직 적용되지 않았습니다";

    var link = byId("ghEditLink");
    var url = ghEditUrl();
    if (url) { link.href = url; link.hidden = false; } else { link.hidden = true; }
  }

  function renderHealth(rows) {
    var box = byId("healthList");
    box.textContent = "";
    rows.forEach(function (h) {
      var row = el("div", "health-row");
      row.appendChild(el("span", "health-name", h.company));
      if (h.manual_only) {
        row.appendChild(el("span", "health-dim", "수동 확인 전용"));
      } else {
        row.appendChild(el("span", h.list_ok ? "health-ok" : "health-bad",
          h.list_ok ? "접속 OK" : "접속 실패"));
        if (h.method === "browser") {
          row.appendChild(el("span", "chip warn",
            h.fallback_used ? "브라우저 폴백" : "브라우저 렌더링"));
        }
        row.appendChild(el("span", "health-nums",
          "링크 " + h.links_found + " · 신규 " + h.new_found +
          " · 본문 " + h.detail_ok + "/" + (h.detail_ok + h.detail_failed)));
      }
      var note = [h.error, h.note].filter(Boolean).join(" ");
      if (note) row.appendChild(el("span", "health-note", note));
      box.appendChild(row);
    });
    if (!rows.length) box.appendChild(el("p", "empty", "아직 수집 기록이 없습니다."));
  }

  /* ── 모니터링 페이지 편집 ───────────────────────────── */

  function openSheet(source) {
    state.editingKey = source ? source.key : null;
    byId("sheetTitle").textContent = source ? "채용 페이지 수정" : "채용 페이지 추가";
    byId("fCompany").value = source ? (source.company || "") : "";
    byId("fUrl").value = source ? (source.url || "") : "";
    byId("fMemo").value = source ? (source.memo || "") : "";
    byId("fPattern").value = source && source.link_include ? source.link_include.join(", ") : "";
    byId("fManual").checked = source ? !!source.manual_only : false;
    byId("sheetDelete").hidden = !source;
    byId("sheetError").hidden = true;
    byId("sheet").hidden = false;
    setTimeout(function () { byId("fCompany").focus(); }, 50);
  }

  function closeSheet() {
    byId("sheet").hidden = true;
    state.editingKey = null;
  }

  function saveSheet() {
    var company = byId("fCompany").value.trim();
    var url = byId("fUrl").value.trim();
    var memo = byId("fMemo").value.trim();
    var pattern = byId("fPattern").value.trim();
    var manual = byId("fManual").checked;
    var err = byId("sheetError");

    if (!company) { err.textContent = "회사명을 입력하세요."; err.hidden = false; return; }
    if (!/^https?:\/\/.+/i.test(url)) {
      err.textContent = "주소는 http:// 또는 https:// 로 시작해야 합니다.";
      err.hidden = false; return;
    }

    var includes = pattern ? pattern.split(",").map(function (x) { return x.trim(); })
      .filter(Boolean) : [];

    var fields = {
      company: company, url: url, memo: memo,
      manual_only: manual, link_include: includes
    };

    if (state.editingKey) {
      var addIdx = -1;
      state.patch.add.forEach(function (a, i) { if (a.key === state.editingKey) addIdx = i; });
      if (addIdx >= 0) {
        for (var k in fields) state.patch.add[addIdx][k] = fields[k];
      } else {
        state.patch.edit[state.editingKey] = fields;
      }
      toast(company + " 수정됨");
    } else {
      var item = {};
      for (var d in NEW_SOURCE_DEFAULTS) item[d] = NEW_SOURCE_DEFAULTS[d];
      item.key = slugKey(company);
      for (var f in fields) item[f] = fields[f];
      state.patch.add.push(item);
      toast(company + " 추가됨");
    }

    savePatch();
    closeSheet();
    renderSources();
    runDebug();
  }

  function removeSource(key, label) {
    var addIdx = -1;
    state.patch.add.forEach(function (a, i) { if (a.key === key) addIdx = i; });

    var undo;
    if (addIdx >= 0) {
      var removed = state.patch.add[addIdx];
      state.patch.add.splice(addIdx, 1);
      undo = function () { state.patch.add.splice(addIdx, 0, removed); };
    } else {
      var hadEdit = state.patch.edit[key];
      var wasDeleted = state.patch.del.indexOf(key) !== -1;
      if (!wasDeleted) state.patch.del.push(key);
      delete state.patch.edit[key];
      undo = function () {
        var i = state.patch.del.indexOf(key);
        if (i !== -1 && !wasDeleted) state.patch.del.splice(i, 1);
        if (hadEdit) state.patch.edit[key] = hadEdit;
      };
    }

    savePatch();
    renderSources();
    runDebug();
    toast((label ? label + " 삭제됨" : "삭제됨"), {
      actionLabel: "실행취소",
      ms: 5000,
      onAction: function () {
        undo();
        savePatch();
        renderSources();
        runDebug();
        toast("삭제를 취소했습니다");
      }
    });
  }

  function copyConfig() {
    var text = exportConfig();
    var out = byId("cfgOut");
    out.value = text;

    function fallback() {
      out.hidden = false;
      out.focus();
      out.setSelectionRange(0, out.value.length);
      toast("자동 복사가 막혀 있습니다. 아래 상자의 내용을 길게 눌러 복사하세요.", 5000);
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        toast("sources.json 내용을 복사했습니다. GitHub에서 파일 전체를 지우고 붙여넣으세요.", 4200);
      }).catch(fallback);
    } else {
      fallback();
    }
  }

  /* ── 탭 전환 ────────────────────────────────────────── */

  var TAB_TITLE = { jobs: "AI 추천 공고", sources: "모니터링 페이지" };

  function setTab(name) {
    state.tab = name;
    try { localStorage.setItem(K_TAB, name); } catch (e) { /* 무시 */ }

    byId("panel-jobs").hidden = name !== "jobs";
    byId("panel-sources").hidden = name !== "sources";
    byId("brandTitle").textContent = TAB_TITLE[name] || "채용공고 모니터";

    Array.prototype.forEach.call(document.querySelectorAll(".tabbtn"), function (b) {
      var on = b.dataset.tab === name;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", String(on));
    });

    window.scrollTo(0, 0);
    runDebug();
  }

  /* ── 자가진단 (?debug=1) ────────────────────────────── */

  function runDebug() {
    if (!DEBUG) return;
    var panel = byId("debugPanel");
    panel.hidden = false;

    var de = document.documentElement;
    var vw = de.clientWidth;
    var offenders = [];
    var nodes = document.querySelectorAll("body *");
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (n.closest && n.closest("#debugPanel")) continue;
      var r = n.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      if (r.right > vw + 1 || r.left < -1) {
        offenders.push("<" + n.tagName.toLowerCase() + " class=\"" +
          ((n.className && n.className.toString()) || "") + "\"> " +
          Math.round(r.left) + "→" + Math.round(r.right));
      }
      if (offenders.length >= 10) break;
    }

    var overflow = de.scrollWidth - de.clientWidth;
    var storageOk = true;
    try { localStorage.setItem("__t", "1"); localStorage.removeItem("__t"); }
    catch (e) { storageOk = false; }

    panel.textContent = "";
    panel.appendChild(el("h3", null, "자가진단 (?debug=1 로 켜짐)"));

    var lines = [
      ["scrollWidth / clientWidth", de.scrollWidth + " / " + de.clientWidth,
        overflow <= 0],
      ["가로 초과", overflow + "px", overflow <= 0],
      ["화면 폭 · DPR", window.innerWidth + "px · " + (window.devicePixelRatio || 1), true],
      ["현재 탭", state.tab, true],
      ["localStorage", storageOk ? "사용 가능" : "차단됨(설정 저장 안 됨)", storageOk],
      ["공고 수", ((state.data && state.data.jobs) || []).length, true],
      ["마감 처리", expiredJobs().length + "건", true],
      ["삭제됨", state.deleted.size + "건", true],
      ["초과 요소", offenders.length + "개", offenders.length === 0],
      ["목록URL이 걸린 카드", document.querySelectorAll('[data-list-url="1"]').length + "건",
        document.querySelectorAll('[data-list-url="1"]').length === 0]
    ];

    var hrefs = [];
    Array.prototype.forEach.call(document.querySelectorAll(".job-title"), function (a) {
      hrefs.push(a.getAttribute("href"));
    });

    lines.forEach(function (l) {
      var p = el("div", l[2] ? "ok" : "bad", l[0] + ": " + l[1]);
      panel.appendChild(p);
    });

    if (offenders.length) {
      var ul = el("ul", "bad");
      offenders.forEach(function (o) { ul.appendChild(el("li", null, o)); });
      panel.appendChild(ul);
    }

    if (hrefs.length) {
      panel.appendChild(el("div", null, "카드 링크 " + hrefs.length + "건:"));
      var ul2 = el("ul", null);
      hrefs.slice(0, 8).forEach(function (h) {
        ul2.appendChild(el("li", isListUrl(h) ? "bad" : "ok", h));
      });
      panel.appendChild(ul2);
    }
  }

  /* ── 데이터 로드 ────────────────────────────────────── */

  function dataFile() {
    if (/[?&]demo=crawl/.test(location.search)) return "data/sample-crawl.json";
    if (/[?&]demo=1/.test(location.search)) return "data/sample-jobs.json";
    return "data/jobs.json";
  }

  function load() {
    var btn = byId("refreshBtn");

    // 미리보기(preview.html)에서는 네트워크 없이 내장 데이터를 씁니다.
    if (window.__EJA_PREVIEW_DATA__) {
      state.data = window.__EJA_PREVIEW_DATA__;
      state.data.jobs = state.data.jobs || [];
      render();
      return;
    }

    btn.classList.add("is-spinning");
    fetch(dataFile() + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (json) {
        json.jobs = Array.isArray(json.jobs) ? json.jobs : [];
        state.data = json;
        render();
      })
      .catch(function (err) {
        state.data = state.data || { jobs: [], sources: [], source_health: [], stats: {} };
        byId("recList").textContent = "";
        byId("recList").appendChild(el("p", "empty",
          "공고 데이터를 불러오지 못했습니다 (" + err.message + "). " +
          "GitHub의 Actions 탭에서 '채용공고 모니터링'을 한 번 실행하면 data/jobs.json이 만들어집니다."));
        byId("updatedAt").textContent = "데이터 없음";
        renderSources();
        runDebug();
      })
      .then(function () { btn.classList.remove("is-spinning"); });
  }

  /* ── 초기화 ─────────────────────────────────────────── */

  function init() {
    try {
      var sf = localStorage.getItem(K_FILTER);
      if (sf === "all" || sf === "unseen") state.filter = sf;
      var st = localStorage.getItem(K_TAB);
      if (st === "jobs" || st === "sources") state.tab = st;
    } catch (e) { /* 무시 */ }

    Array.prototype.forEach.call(document.querySelectorAll(".seg"), function (b) {
      var active = b.dataset.filter === state.filter;
      b.classList.toggle("is-active", active);
      b.setAttribute("aria-pressed", String(active));
      b.addEventListener("click", function () {
        state.filter = b.dataset.filter;
        try { localStorage.setItem(K_FILTER, state.filter); } catch (e) { /* 무시 */ }
        Array.prototype.forEach.call(document.querySelectorAll(".seg"), function (o) {
          var on = o.dataset.filter === state.filter;
          o.classList.toggle("is-active", on);
          o.setAttribute("aria-pressed", String(on));
        });
        render();
      });
    });

    Array.prototype.forEach.call(document.querySelectorAll(".tabbtn"), function (b) {
      b.addEventListener("click", function () { setTab(b.dataset.tab); });
    });

    byId("refreshBtn").addEventListener("click", load);

    byId("resetSeen").addEventListener("click", function () {
      askConfirm("읽음 기록 지우기",
        "읽음 표시를 모두 지웁니다. 숨긴 공고와 모니터링 페이지 설정은 그대로 유지됩니다.",
        "지우기", function () {
          state.seen.clear();
          saveSet(K_SEEN, state.seen);
          render();
          toast("읽음 기록을 지웠습니다");
        });
    });

    byId("addSrcBtn").addEventListener("click", function () { openSheet(null); });
    byId("sheetCancel").addEventListener("click", closeSheet);
    byId("sheetBackdrop").addEventListener("click", closeSheet);
    byId("sheetSave").addEventListener("click", saveSheet);
    byId("sheetDelete").addEventListener("click", function () {
      var key = state.editingKey;
      if (!key) return;
      var label = byId("fCompany").value.trim();
      closeSheet();
      removeSource(key, label);
    });
    byId("copyCfgBtn").addEventListener("click", copyConfig);
    byId("revertBtn").addEventListener("click", function () {
      askConfirm("변경 되돌리기",
        "화면에서 추가·수정·삭제한 내용을 모두 되돌려 config/sources.json 상태로 되돌립니다.",
        "되돌리기", function () {
          state.patch = emptyPatch();
          savePatch();
          renderSources();
          runDebug();
          toast("변경을 되돌렸습니다");
        });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !byId("sheet").hidden) closeSheet();
    });

    window.addEventListener("resize", runDebug);

    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible" && state.data && !window.__EJA_PREVIEW_DATA__) load();
    });

    setTab(state.tab);
    load();

    if ("serviceWorker" in navigator) {
      window.addEventListener("load", function () {
        navigator.serviceWorker.register("sw.js").catch(function () { /* 무시 */ });
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
