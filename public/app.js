(() => {
const state = {
    needs2fa: false,
    isLoading: false,
    account: null,
    isDeletingCareer: false,
    isFetchingFriends: false,
    isStartingCareer: false,
    presets: [],
    selectedPreset: "",
    runnerTimer: 0,
    isSavingPreset: false,
    raceData: [],
    selectedRaces: [],
    goalInfo: {},
    racesDirty: false,
    scenarioType: "Mant",
    burnClocks: false,
    displayedClocksUsed: 0,
    devEnabled: false,
    finishCareer: false,
    runCount: 1,
    consecutiveRunnerFails: 0
};
const els = {
    loadingScreen: document.getElementById('loading-screen'),
    navbar: document.querySelector('.navbar'),
    themeToggle: document.getElementById('theme-toggle'),
    brandMark: document.querySelector('.title span'),
    loginBtn: document.getElementById('login-btn'),
    logoutBtn: document.getElementById('logout-btn'),
    refreshBtn: document.getElementById('refresh-btn'),
    historyBtn: document.getElementById('history-btn'),
    historyModal: document.getElementById('history-modal'),
    historyList: document.getElementById('history-list'),
    historyClose: document.getElementById('history-close'),
    setupWorkspace: document.getElementById('setup-workspace'),
    setupWorkspaceClose: document.getElementById('setup-workspace-close'),
    turnDelayMin: document.getElementById('turn-delay-min'),
    turnDelayMax: document.getElementById('turn-delay-max'),
    temptFateBtn: document.getElementById('tempt-fate-btn'),
    burnClocksBtn: document.getElementById('burn-clocks-btn'),
    finishCareerBtn: document.getElementById('finish-career-btn'),
    scheduleBtn: document.getElementById('schedule-btn'),
    scenarioBtn: document.getElementById('scenario-btn'),
    devBtn: document.getElementById('dev-career-btn'),
    runCountInput: document.getElementById('run-count-input'),
    runCountHint: document.getElementById('run-count-hint'),
    loginView: document.getElementById('login-view'),
    dashboardView: document.getElementById('dashboard-view'),
    errorMsg: document.getElementById('error-msg'),
    standardFields: document.getElementById('standard-fields'),
    faFields: document.getElementById('2fa-fields'),
    umaGrid: document.getElementById('uma-grid'),
    cardGrid: document.getElementById('card-grid'),
    cardGridWrapper: document.getElementById('card-grid-wrapper'),
    cardsToggle: document.getElementById('cards-toggle'),
    cardsChevron: document.getElementById('cards-chevron'),
    parentGrid: document.getElementById('parent-grid'),
    parentSearch: document.getElementById('parent-search'),
    parentStatChips: document.getElementById('parent-stat-chips'),
    parentSort: document.getElementById('parent-sort'),
    parentDeleteToggle: document.getElementById('parent-delete-toggle'),
    parentDeleteBtn: document.getElementById('parent-delete-btn'),
    parentDeleteClear: document.getElementById('parent-delete-clear'),
    parentDeleteHint: document.getElementById('parent-delete-hint'),
    parentDeleteStatus: document.getElementById('parent-delete-status'),
    guestSearch: document.getElementById('guest-search'),
    guestStatChips: document.getElementById('guest-stat-chips'),
    guestSort: document.getElementById('guest-sort'),
    friendGrid: document.getElementById('friend-grid'),
    deckList: document.getElementById('deck-list'),
    umaCount: document.getElementById('uma-count'),
    cardCount: document.getElementById('card-count'),
    parentCount: document.getElementById('parent-count'),
    friendCount: document.getElementById('friend-count'),
    friendStatus: document.getElementById('friend-status'),
    friendRefreshBtn: document.getElementById('friend-refresh-btn'),
    friendSearch: document.getElementById('friend-search'),
    friendTypeChips: document.getElementById('friend-type-chips'),
    guestGrid: document.getElementById('guest-grid'),
    guestStatus: document.getElementById('guest-status'),
    guestRefreshBtn: document.getElementById('guest-refresh-btn'),
    guestCount: document.getElementById('guest-count'),
    presetSelect: document.getElementById('preset-select'),
    startCareerBtn: document.getElementById('start-career-btn'),
    navRunBtn: document.getElementById('nav-run-btn'),
    navPauseBtn: document.getElementById('nav-pause-btn'),
    navStopBtn: document.getElementById('nav-stop-btn'),
    startStatus: document.getElementById('start-status'),
    accountStrip: document.getElementById('account-strip'),
    careerModal: document.getElementById('career-modal'),
    careerModalCopy: document.getElementById('career-modal-copy'),
    careerCancelBtn: document.getElementById('career-cancel-btn'),
    careerDeleteBtn: document.getElementById('career-delete-btn'),
    runConfirmModal: document.getElementById('run-confirm-modal'),
    runConfirmCopy: document.getElementById('run-confirm-copy'),
    runConfirmOk: document.getElementById('run-confirm-ok'),
    runConfirmCancel: document.getElementById('run-confirm-cancel'),
    raceToggle: document.getElementById('race-toggle'),
    raceChevron: document.getElementById('race-chevron'),
    raceBody: document.getElementById('race-body'),
    saveRacesBtn: document.getElementById('save-races-btn'),
    raceSaveStatus: document.getElementById('race-save-status'),
    raceOptionsContent: document.getElementById('race-options-content'),
    racePopupOverlay: document.getElementById('race-slot-popup-overlay'),
    racePopupTitle: document.getElementById('race-slot-popup-title'),
    racePopupBody: document.getElementById('race-slot-popup-body'),
    racePopupClose: document.getElementById('race-slot-popup-close'),
    masterDataPath: document.getElementById('master-data-path'),
    masterDataSaveBtn: document.getElementById('master-data-save-btn'),
    masterDataRefreshBtn: document.getElementById('master-data-refresh-btn'),
    masterDataStatus: document.getElementById('master-data-status'),
    discordWebhookUrl: document.getElementById('discord-webhook-url'),
    discordWebhookSaveBtn: document.getElementById('discord-webhook-save-btn'),
    discordWebhookTestBtn: document.getElementById('discord-webhook-test-btn'),
    discordWebhookStatus: document.getElementById('discord-webhook-status'),
    discordNotifyForecast: document.getElementById('discord-notify-forecast'),
    presetSection: document.getElementById('preset-section'),
    presetAddBtn: document.getElementById('preset-add-btn'),
    presetDelBtn: document.getElementById('preset-del-btn'),
    presetRunningStyle: document.getElementById('preset-running-style'),
    presetEditSkillsBtn: document.getElementById('preset-edit-skills-btn'),
    skillModal: document.getElementById('skill-modal'),
    skillSearch: document.getElementById('skill-search'),
    skillList: document.getElementById('skill-list'),
    skillTiersContainer: document.getElementById('skill-tiers-container'),
    skillBlacklistContainer: document.getElementById('skill-blacklist-container'),
    skillGoalContainer: document.getElementById('skill-goal-container'),
    skillAddTierBtn: document.getElementById('skill-add-tier-btn'),
    skillModalClose: document.getElementById('skill-modal-close')
};
        const delaySettingsStorageKey = 'uma_career_minutes_settings';   // was per-turn seconds; new key so an old tab can't push 7-11 as minutes
        const burnClocksStorageKey = 'uma_burn_clocks';
        const devStorageKey = 'uma_dev_career';
        function syncDevControls() {
            if (!els.devBtn) return;
            els.devBtn.classList.toggle('is-active', state.devEnabled);
            els.devBtn.innerText = `DEV: ${state.devEnabled ? 'ON' : 'OFF'}`;
        }
        function setDevEnabled(value, options = {}) {
            state.devEnabled = Boolean(value);
            syncDevControls();
            if (options.persist) {
                localStorage.setItem(devStorageKey, String(state.devEnabled));
            }
        }

        window.addEventListener('storage', event => {
            if (event.key === devStorageKey && event.newValue !== null) {
                setDevEnabled(event.newValue === 'true', { persist: false });
            }
        });
        const storedDev = localStorage.getItem(devStorageKey);
        if (storedDev !== null) setDevEnabled(storedDev === 'true', { persist: false });

        // FINISH toggle: ON = play a single career to its natural turn-78 finish;
        // OFF = stop at turn 77 (career left unfinished). Sent to the backend with the
        // run request. Loops (RUNS != 1) always finish regardless of this toggle.
        const finishCareerStorageKey = 'uma_finish_career';
        function syncFinishCareerControls() {
            if (!els.finishCareerBtn) return;
            els.finishCareerBtn.classList.toggle('is-active', state.finishCareer);
            els.finishCareerBtn.innerText = `FINISH ${state.finishCareer ? '✓' : '✕'}`;
        }
        function setFinishCareer(value, options = {}) {
            state.finishCareer = Boolean(value);
            syncFinishCareerControls();
            if (options.persist) {
                localStorage.setItem(finishCareerStorageKey, String(state.finishCareer));
            }
        }
        window.addEventListener('storage', event => {
            if (event.key === finishCareerStorageKey && event.newValue !== null) {
                setFinishCareer(event.newValue === 'true', { persist: false });
            }
        });
        if (els.finishCareerBtn) {
            els.finishCareerBtn.addEventListener('click', () => {
                setFinishCareer(!state.finishCareer, { persist: true });
            });
        }
        const storedFinish = localStorage.getItem(finishCareerStorageKey);
        setFinishCareer(storedFinish === 'true', { persist: false });

        // Race Schedule opt-in (non-MANT), stored PER PRESET (on preset.use_race_schedule, right
        // beside its extra_race_list) so a preset that has a schedule remembers to run it -- no
        // session-global toggle that silently ends up off while a saved schedule sits unused. ON =
        // run the preset's extra_race_list ON TOP of career goals; OFF = career goals only. Hidden
        // for MANT (which always uses the schedule). The backend reads it off the saved preset.
        // Effective schedule state (mirrors backend RacePlanner._use_schedule): the explicit toggle
        // wins both ways; when UNSET, a populated extra_race_list defaults to ON (a schedule you built
        // should run without a separate opt-in you keep forgetting).
        function scheduleEffectiveOn(preset) {
            if (!preset) return false;
            const v = preset.use_race_schedule;
            if (v !== undefined && v !== null) return Boolean(v);
            return Boolean((preset.extra_race_list || []).length);
        }
        function syncScheduleControls() {
            if (!els.scheduleBtn) return;
            const field = document.getElementById('schedule-field');   // hide the whole field for MANT (no orphan label)
            if (field) field.style.display = state.scenarioType === 'Mant' ? 'none' : '';
            const on = scheduleEffectiveOn(getCurrentPreset());
            els.scheduleBtn.classList.toggle('is-active', on);
            els.scheduleBtn.innerText = on ? '✓ SCHEDULE ON' : '✕ SCHEDULE OFF';
        }
        function toggleUseRaceSchedule() {
            const current = getCurrentPreset();
            if (!current) return;
            // flip the EFFECTIVE state and store it EXPLICITLY, so turning a defaulted-ON schedule OFF
            // sets use_race_schedule:false (and it stays off) rather than no-opping.
            current.use_race_schedule = !scheduleEffectiveOn(current);
            syncScheduleControls();
            savePresetConfig();
        }
        if (els.scheduleBtn) {
            els.scheduleBtn.addEventListener('click', toggleUseRaceSchedule);
        }

        // Scenario is CHOSEN at terminal startup and FROZEN for the session. This is a READ-ONLY
        // shower -- it just displays the active scenario (restart the terminal to choose again). No
        // toggle. state.scenarioType is kept in sync because the deck UI + start-request read it.
        const SCENARIO_ID_TO_TYPE = { 2: 'Unity', 4: 'Mant', 1: 'Ura', 3: 'GrandLive' };
        const SCENARIO_TYPE_TO_ID = { Unity: 2, Ura: 1, GrandLive: 3, Mant: 4 };
        function currentScenarioId() { return SCENARIO_TYPE_TO_ID[state.scenarioType] || 4; }

        function syncScenarioControls(lock) {
            state.scenarioType = SCENARIO_ID_TO_TYPE[lock.locked_scenario_id] || 'Mant';
            syncScheduleControls();   // show the SCHEDULE toggle for non-MANT, hide it for MANT
            if (!els.scenarioBtn) return;
            const name = lock.locked_name || 'MANT';
            els.scenarioBtn.classList.toggle('is-active', lock.locked_scenario_id === 2);
            els.scenarioBtn.innerText = `Scenario: ${name}`;
            els.scenarioBtn.title = `Scenario is ${name} for this session. Chosen at terminal startup; restart the terminal to choose again.`;
            els.scenarioBtn.disabled = true;   // read-only shower, not a toggle
            els.scenarioBtn.style.cursor = 'default';
        }
        async function loadScenarioLock() {
            let lock = { locked_scenario_id: 4, locked_name: 'MANT' };
            try { lock = await apiJson('/api/scenario'); } catch (e) { /* keep default */ }
            syncScenarioControls(lock);
        }
        loadScenarioLock();

        const runCountStorageKey = 'uma_run_count';
        function readRunCount() {
            const v = parseInt(els.runCountInput && els.runCountInput.value, 10);
            return (Number.isInteger(v) && v >= 0) ? v : 1;
        }
        function updateRunCountHint() {
            if (!els.runCountHint) return;
            const n = state.runCount;
            els.runCountHint.textContent = n === 0 ? '∞ infinite' : (n === 1 ? '1 career (once)' : `${n} careers`);
            els.runCountHint.classList.toggle('infinite', n === 0);
        }
        const storedRunCount = localStorage.getItem(runCountStorageKey);
        if (storedRunCount !== null && els.runCountInput) els.runCountInput.value = storedRunCount;
        state.runCount = readRunCount();
        updateRunCountHint();
        if (els.runCountInput) {
            els.runCountInput.addEventListener('input', () => {
                state.runCount = readRunCount();
                localStorage.setItem(runCountStorageKey, String(state.runCount));
                updateRunCountHint();
            });
        }

        function setLoadingScreen(visible) {
            // Loading splash ("Girls are preparing...") disabled -- always keep it hidden.
            // (Re-enable by restoring: els.loadingScreen.classList.toggle('hidden', !visible);)
            if (!els.loadingScreen) return;
            els.loadingScreen.classList.add('hidden');
        }
        function hideNavbar() {
            document.body.classList.add('pre-login');
            if (els.brandMark) els.brandMark.classList.remove('is-entrance');
        }
        function showNavbar() {
            document.body.classList.remove('pre-login');
        }
        function playBrandIntro() {
            if (!els.brandMark) return;
            els.brandMark.classList.remove('is-entrance');
            void els.brandMark.offsetWidth;
            els.brandMark.classList.add('is-entrance');
            window.setTimeout(() => els.brandMark.classList.remove('is-entrance'), 950);
        }
        hideNavbar();
        function syncDashboardHeight() {
            const navbar = document.querySelector('.navbar');
            const navbarHeight = navbar ? navbar.getBoundingClientRect().height : 0;
            const availableHeight = Math.max(360, Math.floor(window.innerHeight - navbarHeight));
            document.documentElement.style.setProperty('--dashboard-height', `${availableHeight}px`);
            syncDashboardCollapseState(false);
        }
        window.addEventListener('resize', syncDashboardHeight);
        window.addEventListener('orientationchange', syncDashboardHeight);
        syncDashboardHeight();
        const panelToggleSyncers = [];
        const dashboardMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
        let dashboardLayoutAnimation = 0;
        const dashboardAnimationMs = 420;
        function isCompactDashboard() {
            return window.matchMedia('(max-width: 850px)').matches;
        }
        function getPanelLayoutTarget(setupCollapsed, contentCollapsed) {
            const compact = isCompactDashboard();
            const gutter = document.querySelector('.split-gutter-controls');
            const dashboardRect = els.dashboardView.getBoundingClientRect();
            const gutterRect = gutter.getBoundingClientRect();
            const gutterSize = compact ? gutterRect.height : gutterRect.width;
            const available = Math.max(0, (compact ? dashboardRect.height : dashboardRect.width) - gutterSize);
            if (compact) {
                const setupSize = setupCollapsed ? 0 : contentCollapsed ? available : available * 0.34;
                const contentSize = contentCollapsed ? 0 : setupCollapsed ? available : Math.max(340, available - setupSize);
                return { compact, gutterSize, setupSize, contentSize };
            }
            const setupSize = setupCollapsed ? 0 : contentCollapsed ? available : Math.min(available * 0.62, available - 340);
            const contentSize = contentCollapsed ? 0 : setupCollapsed ? available : Math.max(340, available - setupSize);
            return { compact, gutterSize, setupSize, contentSize };
        }
        function setDashboardTemplate(layout, setupSize, contentSize) {
            const safeSetup = Math.max(0, setupSize);
            const safeContent = Math.max(0, contentSize);
            if (layout.compact) {
                els.dashboardView.style.gridTemplateColumns = '';
                els.dashboardView.style.gridTemplateRows = `${safeSetup}px ${layout.gutterSize}px ${safeContent}px`;
            } else {
                els.dashboardView.style.gridTemplateRows = '';
                els.dashboardView.style.gridTemplateColumns = `${safeSetup}px ${layout.gutterSize}px ${safeContent}px`;
            }
        }
        function easeDashboardLayout(t) {
            return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        }
        function syncDashboardCollapseState(animate = false) {
            const setupPanel = document.getElementById('setup-panel');
            const contentPanel = document.getElementById('content-panel');
            if (!setupPanel || !contentPanel || !els.dashboardView) return;
            if (setupPanel.classList.contains('collapsed') && contentPanel.classList.contains('collapsed')) {
                contentPanel.classList.remove('collapsed');
            }
            const setupCollapsed = setupPanel.classList.contains('collapsed');
            const contentCollapsed = contentPanel.classList.contains('collapsed');
            els.dashboardView.classList.toggle('setup-collapsed', setupCollapsed);
            els.dashboardView.classList.toggle('content-collapsed', contentCollapsed);
            if (!els.dashboardView.classList.contains('active')) return;
            const layout = getPanelLayoutTarget(setupCollapsed, contentCollapsed);
            if (dashboardLayoutAnimation) {
                cancelAnimationFrame(dashboardLayoutAnimation);
                dashboardLayoutAnimation = 0;
            }
            els.dashboardView.style.transition = 'none';
            if (!animate || dashboardMotion.matches) {
                setDashboardTemplate(layout, layout.setupSize, layout.contentSize);
                return;
            }
            const compact = layout.compact;
            const setupRect = setupPanel.getBoundingClientRect();
            const contentRect = contentPanel.getBoundingClientRect();
            const startSetup = compact ? setupRect.height : setupRect.width;
            const startContent = compact ? contentRect.height : contentRect.width;
            const targetSetup = layout.setupSize;
            const targetContent = layout.contentSize;
            if (Math.abs(startSetup - targetSetup) < 0.5 && Math.abs(startContent - targetContent) < 0.5) {
                setDashboardTemplate(layout, targetSetup, targetContent);
                return;
            }
            const startedAt = performance.now();
            const step = now => {
                const t = Math.min(1, (now - startedAt) / dashboardAnimationMs);
                const eased = easeDashboardLayout(t);
                setDashboardTemplate(
                    layout,
                    startSetup + (targetSetup - startSetup) * eased,
                    startContent + (targetContent - startContent) * eased
                );
                if (t < 1) {
                    dashboardLayoutAnimation = requestAnimationFrame(step);
                } else {
                    setDashboardTemplate(layout, targetSetup, targetContent);
                    dashboardLayoutAnimation = 0;
                }
            };
            setDashboardTemplate(layout, startSetup, startContent);
            dashboardLayoutAnimation = requestAnimationFrame(step);
        }
        function syncPanelToggleButtons() {
            panelToggleSyncers.forEach(sync => sync());
        }
        function makePanelToggle(panelId, btnId, collapseIcon, expandIcon) {
            const panel = document.getElementById(panelId);
            const btn = document.getElementById(btnId);
            const label = (btn.dataset.panelLabel || 'panel').toLowerCase();
            const renderChevrons = icon => `
                <span class="panel-collapse-btn-chevron-stack" aria-hidden="true">
                    <span>${icon}</span>
                    <span>${icon}</span>
                    <span>${icon}</span>
                </span>
            `;
            const syncButton = () => {
                const isCollapsed = panel.classList.contains('collapsed');
                const icon = isCollapsed ? expandIcon : collapseIcon;
                btn.classList.toggle('is-collapsed', isCollapsed);
                btn.innerHTML = renderChevrons(icon);
                btn.setAttribute('title', `${isCollapsed ? 'Expand' : 'Collapse'} ${label}`);
                btn.setAttribute('aria-label', `${isCollapsed ? 'Expand' : 'Collapse'} ${label}`);
                btn.setAttribute('aria-expanded', String(!isCollapsed));
            };
            panelToggleSyncers.push(syncButton);
            btn.addEventListener('click', () => {
                panel.classList.toggle('collapsed');
                syncDashboardCollapseState(true);
                syncPanelToggleButtons();
            });
            syncDashboardCollapseState(false);
            syncButton();
        }
        makePanelToggle('setup-panel',   'setup-collapse-btn',   '&lt;', '&gt;');
        makePanelToggle('content-panel', 'content-collapse-btn', '&gt;', '&lt;');
        function makeSectionToggle(toggleId, chevronId, bodyId, startExpanded) {
            const toggle  = document.getElementById(toggleId);
            const chevron = document.getElementById(chevronId);
            const body    = document.getElementById(bodyId);
            if (!toggle || !body) return;
            const setInitial = () => {
                const expanded = body.classList.contains('expanded');
                body.style.height = expanded ? 'auto' : '0px';
                chevron.classList.toggle('expanded', expanded);
            };
            const expand = () => {
                body.classList.add('expanded');
                chevron.classList.add('expanded');
                body.style.height = '0px';
                body.offsetHeight;
                body.style.height = `${body.scrollHeight}px`;
            };
            const collapse = () => {
                body.style.height = `${body.scrollHeight}px`;
                body.offsetHeight;
                body.classList.remove('expanded');
                chevron.classList.remove('expanded');
                body.style.height = '0px';
            };
            body.addEventListener('transitionend', event => {
                if (event.propertyName === 'height' && body.classList.contains('expanded')) body.style.height = 'auto';
            });
            toggle.addEventListener('click', () => {
                if (body.classList.contains('expanded')) collapse();
                else expand();
            });
            setInitial();
        }
        makeSectionToggle('events-toggle',   'events-chevron',   'events-body',       true);

        const CHOICE_STAT_LABELS = {
            speed: 'SPD', stamina: 'STA', power: 'POW', guts: 'GUT', wiz: 'WIT',
            skill_point: 'SP', vital: 'Energy', motivation: 'Mood'
        };
        function describeChoice(ci) {
            // Human description of a choice from the bot's OBSERVED outcomes (avg stat deltas).
            const obs = ci && ci.observed;
            if (!obs) return '';
            return Object.keys(CHOICE_STAT_LABELS)
                .map(k => ({ k, v: Math.round((obs[k] || 0) * 10) / 10 }))
                .filter(e => e.v !== 0)
                .map(e => `${CHOICE_STAT_LABELS[e.k]} ${e.v > 0 ? '+' : ''}${e.v}`)
                .join(', ');
        }
        function truncate(s, max) {
            s = String(s || '');
            return s.length > max ? s.slice(0, max - 1) + '…' : s;
        }
        async function loadEvents() {
            const list = document.getElementById('events-list');
            const countEl = document.getElementById('events-count');
            if (!list) return;
            // The server resolves the deck from the ACTIVE career (the support cards you
            // actually brought) and returns their events from master.mdb + card metadata.
            try {
                const data = await apiJson('/api/events');
                const events = (data && data.events) || [];
                const cardsMeta = {};
                ((data && data.cards) || []).forEach(c => { cardsMeta[String(c.id)] = c; });
                if (countEl) countEl.textContent = events.length ? `(${events.length})` : '';
                if (!events.length) {
                    list.innerHTML = '<div class="events-empty">No events yet. Start or resume a career, then hit REFRESH — the events of every support card you brought show up here.</div>';
                    return;
                }
                let html = '';
                let lastCard;
                events.forEach(ev => {
                    const cardId = ev.support_card_id || 0;
                    if (cardId !== lastCard) {
                        lastCard = cardId;
                        const meta = cardsMeta[String(cardId)];
                        const label = meta ? `${meta.name} — ${meta.type}${meta.rarity && meta.rarity !== '?' ? ' · ' + meta.rarity : ''}`
                            : (cardId ? ('Support ' + cardId) : 'Other / scenario events');
                        html += `<div class="event-group-head">${escapeHtml(label)}</div>`;
                    }
                    // Trust the server's per-choice rows when present (it knows the observed
                    // option count); only fall back to 3 generic rows for never-seen events.
                    const n = Math.max(ev.num_choices || 0, (ev.choices || []).length) || 3;
                    const name = ev.event_name || `Event ${ev.story_id}`;
                    const autoTxt = (ev.auto_pick == null) ? 'auto'
                        : `auto: #${ev.auto_pick + 1}${ev.auto_source ? ' (' + ev.auto_source + ')' : ''}`;
                    const seenTxt = ev.count ? `seen ${ev.count}×` : 'not seen yet';
                    const choiceInfo = {};
                    (ev.choices || []).forEach(c => { choiceInfo[c.index] = c; });
                    let opts = `<option value="-1"${ev.override == null ? ' selected' : ''}>Auto</option>`;
                    let detailLines = '';
                    for (let i = 0; i < n; i++) {
                        const ci = choiceInfo[i] || {};
                        const desc = describeChoice(ci);
                        opts += `<option value="${i}"${ev.override === i ? ' selected' : ''}>Choice ${i + 1}${desc ? ' — ' + escapeHtml(truncate(desc, 36)) : ''}</option>`;
                        if (desc || ci.label || ci.seen) {
                            const mark = ci.label === 'good' ? '<span class="choice-good">✓</span>'
                                : (ci.label === 'bad' ? '<span class="choice-bad">✗</span>' : '');
                            const text = desc
                                || (ci.label === 'good' ? 'known good pick'
                                    : ci.label === 'bad' ? 'known bad pick'
                                    : 'no stat change observed');
                            const seenN = ci.seen ? ` <span class="choice-seen">(×${escapeHtml(String(ci.seen))})</span>` : '';
                            detailLines += `<div class="event-choice-line">${i + 1} · ${mark} ${escapeHtml(text)}${seenN}</div>`;
                        }
                    }
                    html += `
                        <div class="event-row${ev.override != null ? ' has-override' : ''}">
                            <div class="event-row-main">
                                <span class="event-name">${escapeHtml(name)}</span>
                                <span class="event-meta">${escapeHtml(seenTxt)} &middot; ${escapeHtml(autoTxt)}</span>
                                ${detailLines ? `<div class="event-choice-details">${detailLines}</div>` : ''}
                            </div>
                            <select class="event-override" data-sid="${escapeAttr(ev.story_id)}">${opts}</select>
                        </div>`;
                });
                list.innerHTML = html;
                list.querySelectorAll('.event-override').forEach(sel => {
                    let lastValue = sel.value;
                    sel.addEventListener('change', async () => {
                        const sid = sel.getAttribute('data-sid');
                        const choice = parseInt(sel.value, 10);
                        const row = sel.closest('.event-row');
                        try {
                            const res = await apiJson('/api/events/override', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ story_id: sid, choice })
                            });
                            if (res && res.success === false) throw new Error('save rejected');
                            lastValue = sel.value;
                            if (row) row.classList.toggle('has-override', choice >= 0);
                        } catch (e) {
                            // Save failed: revert the dropdown so the UI never lies about
                            // which choice the bot will actually use.
                            sel.value = lastValue;
                            if (row) {
                                row.classList.add('save-failed');
                                setTimeout(() => row.classList.remove('save-failed'), 1500);
                            }
                        }
                    });
                });
            } catch (e) {
                list.innerHTML = '<div class="events-empty">Could not load events.</div>';
            }
        }
        const eventsRefreshBtn = document.getElementById('events-refresh-btn');
        if (eventsRefreshBtn) eventsRefreshBtn.addEventListener('click', (e) => { e.stopPropagation(); loadEvents(); });
        // Load when the section is opened (selection/deck is defined by then; avoids
        // touching `selection` during initial setup).
        const eventsToggleEl = document.getElementById('events-toggle');
        if (eventsToggleEl) eventsToggleEl.addEventListener('click', () => {
            const body = document.getElementById('events-body');
            if (body && body.classList.contains('expanded')) loadEvents();
        });
        const applyTheme = theme => {
            const nextTheme = theme === 'blue' ? 'blue' : 'pink';
            document.documentElement.dataset.theme = nextTheme;
            document.documentElement.classList.toggle('theme-blue', nextTheme === 'blue');
            document.body.classList.toggle('theme-blue', nextTheme === 'blue');
            return nextTheme;
        };
        applyTheme(localStorage.getItem('theme'));
        localStorage.removeItem('saved_password');   // purge any plaintext password from the old code
        const savedUsername = localStorage.getItem('saved_username');
        if (savedUsername) document.getElementById('username').value = savedUsername;
        // Server-side saved login: prefills the username + shows a "password stored" hint. The
        // password lives in the OS vault and is NEVER sent to the browser (the old localStorage
        // password is gone). Overrides the localStorage username above when a server login exists.
        loadSavedCredential();
        let themeToggleClicks = 0;
        els.themeToggle.addEventListener('click', () => {
            const nextTheme = document.body.classList.contains('theme-blue') ? 'pink' : 'blue';
            applyTheme(nextTheme);
            localStorage.setItem('theme', nextTheme);
        });
        const sleep = ms => new Promise(resolve => window.setTimeout(resolve, ms));
        const nextFrame = () => new Promise(resolve => requestAnimationFrame(resolve));
        async function waitForDomPaint(frames = 2) {
            for (let i = 0; i < frames; i++) await nextFrame();
        }
        async function apiJson(url, options = {}) {
            const res = await fetch(url, options);
            return res.json();
        }
        function setMasterDataStatus(message, stateName = '') {
            if (!els.masterDataStatus) return;
            els.masterDataStatus.textContent = message || '';
            els.masterDataStatus.className = `master-data-status ${stateName}`.trim();
        }
        function applyMasterDataStatus(data) {
            if (!data) return;
            if (els.masterDataPath && data.master_mdb_path) {
                els.masterDataPath.value = data.master_mdb_path;
            }
            if (els.masterDataPath) {
                els.masterDataPath.classList.toggle('needs-action', !data.exists);
            }
            if (data.exists) {
                if (data.generation_error) {
                    setMasterDataStatus(data.generation_error, 'needs-action');
                } else if (data.generated) {
                    setMasterDataStatus('master.mdb found; data generated', 'ok');
                } else {
                    setMasterDataStatus('master.mdb found', 'ok');
                }
            } else {
                setMasterDataStatus(data.access_error || 'master.mdb not found; update the path', 'needs-action');
            }
        }
        async function loadMasterDataStatus() {
            if (!els.masterDataPath) return;
            try {
                applyMasterDataStatus(await apiJson('/api/master-data/status'));
            } catch (e) {
                setMasterDataStatus('Unable to read master data status', 'needs-action');
            }
        }
        async function saveMasterDataPath() {
            if (!els.masterDataPath) return null;
            const master_mdb_path = els.masterDataPath.value.trim();
            if (!master_mdb_path) {
                setMasterDataStatus('Enter the full path to master.mdb', 'needs-action');
                els.masterDataPath.classList.add('needs-action');
                return null;
            }
            if (els.masterDataSaveBtn) els.masterDataSaveBtn.disabled = true;
            setMasterDataStatus('Saving path and generating data...', 'working');
            const data = await apiJson('/api/master-data/path', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ master_mdb_path })
            });
            applyMasterDataStatus(data);
            if (data.exists && !data.generation_error) {
                await refreshGameDataUI();   // races AND skills (not just races)
            }
            if (els.masterDataSaveBtn) els.masterDataSaveBtn.disabled = false;
            return data;
        }
        function bindMasterDataControls() {
            if (!els.masterDataPath) return;
            if (els.masterDataSaveBtn) {
                els.masterDataSaveBtn.addEventListener('click', async () => {
                    try {
                        await saveMasterDataPath();
                    } catch (e) {
                        setMasterDataStatus(e.message || 'Unable to save master.mdb path', 'needs-action');
                        if (els.masterDataPath) els.masterDataPath.classList.add('needs-action');
                    } finally {
                        if (els.masterDataSaveBtn) els.masterDataSaveBtn.disabled = false;
                    }
                });
            }
            if (els.masterDataRefreshBtn) {
                // Re-read master.mdb NOW and refresh races + skills, no path change and no restart.
                els.masterDataRefreshBtn.addEventListener('click', async () => {
                    els.masterDataRefreshBtn.disabled = true;
                    setMasterDataStatus('Refreshing races + skills from master.mdb...', 'working');
                    try {
                        // apiJson resolves on a 400 too, so the failure is in the body ({detail}).
                        const r = await apiJson('/api/master-data/generate', { method: 'POST' });
                        if (!r || !r.success) throw new Error((r && r.detail) || 'Refresh failed (is master.mdb set?)');
                        await refreshGameDataUI();
                        setMasterDataStatus('Races + skills refreshed from master.mdb.', 'ok');
                    } catch (e) {
                        setMasterDataStatus((e && e.message) || 'Refresh failed (is master.mdb set?)', 'needs-action');
                    } finally {
                        els.masterDataRefreshBtn.disabled = false;
                    }
                });
            }
            els.masterDataPath.addEventListener('input', () => {
                els.masterDataPath.classList.remove('needs-action');
            });
            loadMasterDataStatus();
        }
        function setDiscordStatus(message, stateName = '') {
            if (!els.discordWebhookStatus) return;
            els.discordWebhookStatus.textContent = message || '';
            els.discordWebhookStatus.className = `master-data-status ${stateName}`.trim();
        }
        async function loadDiscordWebhook() {
            if (!els.discordWebhookUrl) return;
            try {
                const data = await apiJson('/api/settings/discord-webhook');
                if (data.webhook_url) els.discordWebhookUrl.value = data.webhook_url;
                if (els.discordNotifyForecast) els.discordNotifyForecast.checked = data.notify_forecast === true;
                setDiscordStatus(data.configured ? 'Webhook saved' : 'Not configured', data.configured ? 'ok' : '');
            } catch (e) {
                setDiscordStatus('Could not read webhook status', 'needs-action');
            }
        }
        async function saveDiscordWebhook() {
            if (!els.discordWebhookUrl) return;
            const webhook_url = els.discordWebhookUrl.value.trim();
            const notify_forecast = els.discordNotifyForecast ? els.discordNotifyForecast.checked : false;
            if (els.discordWebhookSaveBtn) els.discordWebhookSaveBtn.disabled = true;
            setDiscordStatus('Saving...', 'working');
            try {
                const data = await apiJson('/api/settings/discord-webhook', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ webhook_url, notify_forecast })
                });
                setDiscordStatus(data.configured ? 'Webhook saved' : 'Webhook cleared', data.configured ? 'ok' : '');
            } catch (e) {
                setDiscordStatus(e.message || 'Failed to save webhook', 'needs-action');
            } finally {
                if (els.discordWebhookSaveBtn) els.discordWebhookSaveBtn.disabled = false;
            }
        }
        async function testDiscordWebhook() {
            if (els.discordWebhookTestBtn) els.discordWebhookTestBtn.disabled = true;
            setDiscordStatus('Sending test message...', 'working');
            try {
                const data = await apiJson('/api/settings/discord-webhook/test', { method: 'POST' });
                setDiscordStatus(
                    data.success ? 'Test message sent — check your Discord channel' : (data.detail || 'Failed to send test'),
                    data.success ? 'ok' : 'needs-action'
                );
            } catch (e) {
                setDiscordStatus(e.message || 'Failed to send test', 'needs-action');
            } finally {
                if (els.discordWebhookTestBtn) els.discordWebhookTestBtn.disabled = false;
            }
        }
        function bindDiscordWebhookControls() {
            if (!els.discordWebhookUrl) return;
            if (els.discordWebhookSaveBtn) els.discordWebhookSaveBtn.addEventListener('click', saveDiscordWebhook);
            if (els.discordWebhookTestBtn) els.discordWebhookTestBtn.addEventListener('click', testDiscordWebhook);
            els.discordWebhookUrl.addEventListener('input', () => setDiscordStatus(''));
            loadDiscordWebhook();
        }
        function writeLocalSetting(key, value) {
            try {
                localStorage.setItem(key, JSON.stringify(value));
            } catch (e) {}
        }
        function readLocalSetting(value, fallback = null) {
            if (!value) return fallback;
            try {
                return JSON.parse(value);
            } catch (e) {
                return fallback;
            }
        }
        function escapeHtml(value) {
            return String(value ?? '').replace(/[&<>"']/g, char => ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            }[char]));
        }
        function escapeAttr(value) {
            return escapeHtml(value);
        }
        function normalizeDelayBounds(min, max, disabled = false, restoreMin = null, restoreMax = null) {
            const fallbackMin = Number.isFinite(Number(restoreMin)) ? Number(restoreMin) : 15;
            const fallbackMax = Number.isFinite(Number(restoreMax)) ? Number(restoreMax) : 16;
            if (disabled) return { min: 0, max: 0, restoreMin: fallbackMin, restoreMax: fallbackMax, disabled: true };
            const left = Math.max(0, Number.isFinite(Number(min)) ? Number(min) : fallbackMin);
            let right = Math.max(0, Number.isFinite(Number(max)) ? Number(max) : fallbackMax);
            if (left > right) right = left;
            return { min: left, max: right, restoreMin: left, restoreMax: right, disabled: false };
        }
        function setDelayControls(settings) {
            if (!els.turnDelayMin || !els.turnDelayMax || !els.temptFateBtn) return;
            const disabled = Boolean(settings.disabled);
            const restoreMin = Number.isFinite(Number(settings.restoreMin)) ? Number(settings.restoreMin) : Number(settings.restore_min);
            const restoreMax = Number.isFinite(Number(settings.restoreMax)) ? Number(settings.restoreMax) : Number(settings.restore_max);
            els.turnDelayMin.value = String(settings.min);
            els.turnDelayMax.value = String(settings.max);
            els.turnDelayMin.dataset.restoreValue = String(Number.isFinite(restoreMin) ? restoreMin : settings.min);
            els.turnDelayMax.dataset.restoreValue = String(Number.isFinite(restoreMax) ? restoreMax : settings.max);
            els.turnDelayMin.disabled = disabled;
            els.turnDelayMax.disabled = disabled;
            els.temptFateBtn.classList.toggle('is-active', disabled);
            els.temptFateBtn.innerText = disabled ? 'NO CD ✓' : 'NO CD';
        }
        async function saveDelaySettings(settings) {
            setDelayControls(settings);
            const data = await apiJson('/api/settings/turn-delay', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            const normalized = normalizeDelayBounds(data.min, data.max, data.disabled, data.restore_min, data.restore_max);
            setDelayControls(normalized);
            writeLocalSetting(delaySettingsStorageKey, normalized);
        }
        async function loadDelaySettings() {
            if (!els.turnDelayMin || !els.turnDelayMax || !els.temptFateBtn) return;
            try {
                const data = await apiJson('/api/settings/turn-delay');
                setDelayControls(normalizeDelayBounds(data.min, data.max, data.disabled, data.restore_min, data.restore_max));
            } catch (e) {
                setDelayControls({ min: 15, max: 16, restoreMin: 15, restoreMax: 16, disabled: false });
            }
        }
        function bindDelayControls() {
            if (!els.turnDelayMin || !els.turnDelayMax || !els.temptFateBtn) return;
            const sync = () => {
                saveDelaySettings(normalizeDelayBounds(els.turnDelayMin.value, els.turnDelayMax.value, false));
            };
            els.turnDelayMin.addEventListener('input', sync);
            els.turnDelayMax.addEventListener('input', sync);
            els.temptFateBtn.addEventListener('click', () => {
                const active = els.temptFateBtn.classList.contains('is-active');
                const restoreMin = Number(els.turnDelayMin.dataset.restoreValue || 15);
                const restoreMax = Number(els.turnDelayMax.dataset.restoreValue || 16);
                saveDelaySettings(active
                    ? normalizeDelayBounds(restoreMin, restoreMax, false)
                    : normalizeDelayBounds(0, 0, true, restoreMin, restoreMax)
                );
            });
            loadDelaySettings();
        }
        window.addEventListener('storage', event => {
            if (event.key !== delaySettingsStorageKey || !event.newValue) return;
            const settings = readLocalSetting(event.newValue);
            if (settings) setDelayControls(normalizeDelayBounds(settings.min, settings.max, settings.disabled, settings.restoreMin, settings.restoreMax));
        });
        window.addEventListener('storage', event => {
            if (event.key !== burnClocksStorageKey || !event.newValue) return;
            setBurnClocks(readLocalSetting(event.newValue, false));
        });
        function resetLoginState() {
            state.isLoading = false;
            els.loginBtn.innerText = state.needs2fa ? 'VALIDATE' : 'LOGIN';
        }
        function showLoginError(message) {
            setLoadingScreen(false);
            els.errorMsg.innerText = String(message || 'FAIL').toUpperCase();
            els.errorMsg.style.display = 'block';
            resetLoginState();
        }
        function showTwoFactorPrompt() {
            setLoadingScreen(false);
            state.needs2fa = true;
            state.isLoading = false;
            els.standardFields.style.display = 'none';
            els.faFields.style.display = 'block';
            els.loginBtn.innerText = 'VALIDATE';
            els.errorMsg.innerText = '2FA REQUIRED';
            els.errorMsg.style.display = 'block';
        }
        function readLoginPayload() {
            return {
                username: document.getElementById('username').value,
                password: document.getElementById('password').value,
                code: document.getElementById('code').value
            };
        }
        // Prefill from the server-side saved login. Password never leaves the vault, so we only
        // learn whether one is stored (has_password) and hint it in the placeholder.
        async function loadSavedCredential() {
            try {
                const cred = await apiJson('/api/steam/credential');
                if (!cred || !cred.saved) return;
                const u = document.getElementById('username');
                const p = document.getElementById('password');
                if (u && cred.username) u.value = cred.username;
                if (p && cred.has_password) { p.value = ''; p.placeholder = '•••••••• saved — leave blank'; }
            } catch (e) { /* no saved login (or old server without the endpoint) -> blank form */ }
        }
        // Saving the Steam login is PERMANENT and unconditional -- the opt-in checkbox and its
        // "Forget" link were removed from the form, so there is nothing to consult. Store whenever a
        // password was actually typed; a blank password means the vaulted one was used, so there is
        // nothing new to save (and we must NOT clear it). The password only ever reaches the OS vault.
        async function persistSteamCredential(payload) {
            if (!payload.username || !payload.password) return;
            try {
                await apiJson('/api/steam/credential', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: payload.username, password: payload.password })
                });
            } catch (e) { /* saving creds must never block a login that already succeeded */ }
        }
        function resetSelection() {
            selection.deck = null;
            selection.friend = null;
            selection.trainee = null;
            selection.veterans = [];
        }
        function hideBrokenImage(img) {
            img.onerror = null;
            img.style.display = 'none';
        }
        function raceImgFallback(img) {
            // No bundled banner for this race (e.g. a newly added dirt race from a game update, whose
            // art isn't shipped) -> render a clean TERRAIN-TINTED placeholder with the grade so it reads
            // as intentional, not broken. data-terrain / data-grade come from the race row.
            img.onerror = null;
            const box = img.parentElement;
            if (!box) { img.style.display = 'none'; return; }
            const terrain = (img.dataset.terrain || '').toLowerCase();
            const grade = img.dataset.grade || '';
            box.classList.add('race-img-fallback');
            if (terrain === 'dirt') box.classList.add('race-img-fallback-dirt');
            else if (terrain === 'turf') box.classList.add('race-img-fallback-turf');
            box.innerHTML = grade
                ? `<span class="race-img-fallback-grade">${grade}</span>`
                : '<span style="font-size:1.3rem;line-height:1;opacity:.7">🏇</span>';
        }
        // Inline onerror="..." handlers resolve in GLOBAL scope, but this file is an IIFE, so these
        // stayed closure-local -> a missing banner/portrait threw a silent ReferenceError and left a
        // broken image. Expose them so the fallback actually fires.
        window.raceImgFallback = raceImgFallback;
        window.hideBrokenImage = hideBrokenImage;

        // (The "Forget" click handler lived here. Removed with the checkbox: the saved login is now
        // permanent. The DELETE /api/steam/credential endpoint still exists server-side for anyone
        // who wants to clear the vault entry deliberately.)
        const loginForm = document.getElementById('login-form');
        loginForm.addEventListener('submit', async event => {
            event.preventDefault();
            if (state.isLoading) return;
            state.isLoading = true;
            setLoadingScreen(true);
            els.loginBtn.innerText = 'WORKING...';
            els.errorMsg.style.display = 'none';
            const payload = readLoginPayload();
            try {
                const data = await apiJson('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (data.needs_2fa) {
                    showTwoFactorPrompt();
                } else if (data.success) {
                    if (payload.username) localStorage.setItem('saved_username', payload.username);
                    await persistSteamCredential(payload);
                    await renderDashboard(data, { animateIntro: false, waitForIntro: false });
                    state.isLoading = false;
                } else {
                    showLoginError(Array.isArray(data.detail) ? data.detail.map(d => d.msg).join('; ') : (data.detail || 'FAIL'));
                }
            } catch (e) {
                showLoginError('NETWORK ERROR');
            }
        });

        if (els.refreshBtn) {
            els.refreshBtn.addEventListener('click', async () => {
                if (els.refreshBtn.disabled) return;
                els.refreshBtn.disabled = true;
                els.refreshBtn.textContent = 'RE-AUTH…';
                try {
                    // Re-capture fresh auth from the game (handles in-game account switches /
                    // stale auth), poll until it finishes, then refresh the session and reload.
                    const start = await apiJson('/api/auth/recapture', { method: 'POST' });
                    if (start && start.success) {
                        let tries = 0;
                        for (;;) {
                            await new Promise(r => setTimeout(r, 2000));
                            let cap = {};
                            try { cap = ((await apiJson('/api/auth/recapture/status')) || {}).capture || {}; } catch (e) {}
                            if (!cap.capturing || ++tries > 120) {
                                els.refreshBtn.textContent = cap.ok ? 'REFRESHING…' : (cap.message || 'AUTH FAILED');
                                break;
                            }
                            els.refreshBtn.textContent = cap.message || 'RE-AUTH…';
                        }
                    } else {
                        els.refreshBtn.textContent = (start && start.detail) || 'AUTH FAILED';
                    }
                    await apiJson('/api/session/refresh', { method: 'POST' });
                } catch (e) {}
                window.location.reload();
            });
        }

        const formatNumber = value => Number(value || 0).toLocaleString();
        function closeCareerModal() {
            els.careerModal.style.display = 'none';
            els.careerModalCopy.innerText = 'This will force-delete the ongoing career.';
            els.careerDeleteBtn.innerText = 'DELETE';
            state.isDeletingCareer = false;
        }
        function openCareerModal() {
            const career = state.account && state.account.career;
            if (!career || !career.active) return;
            els.careerModalCopy.innerText = 'This will force-delete the ongoing career.';
            els.careerModal.style.display = 'flex';
        }
        async function deleteCareer() {
            const career = state.account && state.account.career;
            if (!career || !career.active || state.isDeletingCareer) return;
            state.isDeletingCareer = true;
            els.careerDeleteBtn.innerText = 'DELETING';
            els.careerModalCopy.innerText = 'Deleting ongoing career...';
            try {
                const data = await apiJson('/api/career/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ current_turn: career.turn || 0 })
                });
                if (!data.success) throw new Error(data.detail || 'Delete failed');
                renderAccountStrip(data.account);
                closeCareerModal();
            } catch (e) {
                els.careerModalCopy.innerText = e.message || 'Delete failed';
                els.careerDeleteBtn.innerText = 'RETRY';
                state.isDeletingCareer = false;
            }
        }
        els.careerCancelBtn.addEventListener('click', closeCareerModal);
        els.careerDeleteBtn.addEventListener('click', deleteCareer);
        els.careerModal.addEventListener('click', event => {
            if (event.target === els.careerModal) closeCareerModal();
        });
        function syncBurnClocksControls() {
            if (!els.burnClocksBtn) return;
            const clocks = state.account ? Number(state.account.clocks || 0) : 0;
            const disabled = clocks <= 11;

            if (disabled) {
                state.burnClocks = false;
                els.burnClocksBtn.disabled = true;
                els.burnClocksBtn.classList.remove('is-active');
                els.burnClocksBtn.innerText = `BURN CLOCKS: LOW (${clocks})`;
            } else {
                els.burnClocksBtn.disabled = false;
                els.burnClocksBtn.classList.toggle('is-active', state.burnClocks);
                els.burnClocksBtn.innerText = `BURN CLOCKS: ${state.burnClocks ? 'ON' : 'OFF'}`;
            }
        }
        function setBurnClocks(value, options = {}) {
            state.burnClocks = Boolean(value);
            syncBurnClocksControls();
            if (options.persist) writeLocalSetting(burnClocksStorageKey, state.burnClocks);
        }
        function loadStoredBurnClocks() {
            if (state.runner && state.runner.running) return;
            const stored = readLocalSetting(localStorage.getItem(burnClocksStorageKey));
            if (stored !== null) setBurnClocks(stored);
        }

        function renderAccountStrip(account) {
            state.account = account || null;
            if (!account) {
                els.accountStrip.style.display = 'none';
                els.accountStrip.innerHTML = '';
                return;
            }
            const tp = account.tp || {};
            const carrots = account.carrots || {};
            els.accountStrip.innerHTML = `
                <div class="account-pill pill-tp">
                    <span class="label">TP</span>
                    <strong>${tp.current || 0}/${tp.max || 0}</strong>
                </div>
                <div class="account-pill pill-carrots">
                    <span class="label">CARROTS</span>
                    <strong>${formatNumber(carrots.total)}</strong>
                </div>
                <div class="account-pill pill-gold">
                    <span class="label">GOLD</span>
                    <strong>${formatNumber(account.gold)}</strong>
                </div>
                <div class="account-pill pill-clk">
                    <span class="label">CLOCKS</span>
                    <strong>${formatNumber(account.clocks)}</strong>
                </div>
                <button id="custom-action-btn" class="account-pill pill-custom account-pill-clickable" type="button" title="Open the career setup workspace — pick trainee, parents, deck, friend">
                    <strong>⚙ SETUP</strong>
                </button>
            `;
            els.accountStrip.style.display = 'flex';
            // Custom action button: a placeholder slot for new features (replaced the old
            // CAREER status pill). >>> Wire your new feature here: replace the handler body. <<<
            // The listener is re-attached on every render because the strip's innerHTML is
            // rebuilt each time. To call the backend, add an @app.post("/api/...") in main.py
            // and use apiJson('/api/...') inside this handler.
            const customBtn = document.getElementById('custom-action-btn');
            if (customBtn) customBtn.addEventListener('click', () => {
                if (els.setupWorkspace) els.setupWorkspace.style.display = 'flex';
            });
            loadStoredBurnClocks();
            syncBurnClocksControls();
        }


        const rankMap = {   // tiers 1-18: single-step G..SS+
            1: 'G', 2: 'G+', 3: 'F', 4: 'F+', 5: 'E', 6: 'E+',
            7: 'D', 8: 'D+', 9: 'C', 10: 'C+', 11: 'B', 12: 'B+',
            13: 'A', 14: 'A+', 15: 'S', 16: 'S+', 17: 'SS', 18: 'SS+'
        };
        // tiers 19-98: eight U-grades x 10 sub-levels (UG, UG1..UG9, UF, UF1..UF9, ... US, US1..US9).
        // UG = tier 19; US9 (tier 98) is the top. Matches career_bot/core/notify.rank_letter.
        const U_GRADES = ['UG', 'UF', 'UE', 'UD', 'UC', 'UB', 'UA', 'US'];
        function rankLabel(rank) {
            const r = Number(rank) || 0;
            if (r <= 0) return '??';
            if (rankMap[r]) return rankMap[r];
            if (r >= 19 && r <= 98) {
                const g = U_GRADES[Math.floor((r - 19) / 10)];
                const sub = (r - 19) % 10;
                return sub === 0 ? g : g + sub;
            }
            return 'US9+' + (r - 98);
        }
        let dashData = null;
        const selection = { deck: null, friend: null, trainee: null, veterans: [], guestParent: null };

        async function syncSelectionToServer() {
            try {
                const payload = {
                    deck: selection.deck,
                    friend: selection.friend,
                    trainee: selection.trainee,
                    veterans: selection.veterans,
                    guestParent: selection.guestParent
                };
                await apiJson('/api/selection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ selection: payload })
                });
            } catch (e) {}
        }

        function deselect(action, idx) {
            // With the library pickers removed there is no way to RE-select a cleared slot.
            // The team panel mirrors the active in-game career, so clearing is meaningless --
            // keep the slots read-only instead of stranding the user with an empty slot.
            const activeCareer = state.account && state.account.career && state.account.career.active;
            if (activeCareer) return;
            if (action === 'deck') {
                document.querySelectorAll('.deck-container.selected').forEach(el => el.classList.remove('selected'));
                selection.deck = null;
            } else if (action === 'friend') {
                document.querySelectorAll('#friend-grid .grid-card.selected').forEach(el => el.classList.remove('selected'));
                selection.friend = null;
            } else if (action === 'trainee') {
                document.querySelectorAll('#uma-grid .grid-card.selected').forEach(el => el.classList.remove('selected'));
                selection.trainee = null;
            } else if (action === 'vet') {
                const vet = selection.veterans[idx];
                if (vet != null) {
                    const card = document.querySelectorAll('#parent-grid .grid-card')[vet._gridIdx];
                    if (card) card.classList.remove('selected');
                }
                selection.veterans.splice(idx, 1);
                updateVetSelectability();
            } else if (action === 'guest') {
                selection.guestParent = null;
                updateVetSelectability();
                renderGuestParents();
            }
            renderTeamPanel();
            syncSelectionToServer();
        }
        function getStartMissingReason() {
            const activeCareer = state.account && state.account.career && state.account.career.active;
            if (!state.selectedPreset) return 'Select a preset';
            if (activeCareer) return '';
            // Build-from-scratch via the SETUP workspace: require a complete team before RUN.
            if (!selection.trainee) return 'Pick a trainee in SETUP';
            if (selection.veterans.length < (selection.guestParent ? 1 : 2))
                return selection.guestParent ? 'Pick 1 owned parent in SETUP' : 'Pick 2 parents in SETUP';
            if (!selection.deck) return 'Pick a deck in SETUP';
            if (!selection.friend) return 'Pick a friend support in SETUP';
            const parentErr = getParentSelectionError();
            if (parentErr) return parentErr;
            return '';
        }
        function getParentLineageCards(parent) {
            if (!parent || !parent.tree) return [];
            return ['self', 'p1', 'p2', 'gp1', 'gp2', 'gp3', 'gp4']
                .map(key => Number(parent.tree[key] && parent.tree[key].card_id))
                .filter(Boolean);
        }
        function getParentSelectionError() {
            if (!selection.trainee) return '';
            const traineeId = Number(selection.trainee.id);
            const lineages = selection.veterans.map(getParentLineageCards);
            if (lineages.length < 2) return '';
            if (lineages.some(cards => cards[0] === traineeId)) return 'Direct parent is trainee';
            return '';
        }
        function syncStartButton() {
            const reason = getStartMissingReason();
            els.startCareerBtn.disabled = Boolean(reason) || state.isStartingCareer;
            if (state.isStartingCareer) {
                els.startCareerBtn.innerText = 'RUNNING...';
                els.startStatus.innerText = 'Starting runner...';
                els.startStatus.classList.remove('error');
            } else {
                const activeCareer = state.account && state.account.career && state.account.career.active;
                els.startCareerBtn.innerText = activeCareer ? 'RESUME CAREER' : 'RUN CAREER';
                els.startStatus.innerText = reason;
                els.startStatus.classList.toggle('error', false);
            }
            if (els.navRunBtn) {
                els.navRunBtn.disabled = els.startCareerBtn.disabled;
                const activeCareer = state.account && state.account.career && state.account.career.active;
                els.navRunBtn.innerText = state.isStartingCareer ? 'RUNNING' : (activeCareer ? 'RESUME' : 'RUN');
                els.navRunBtn.title = (!state.isStartingCareer && reason) ? reason : '';
            }
        }
        function renderTeamPanel() {
            document.getElementById('dashboard-view').classList.add('active');
            function setSlot(id, role, content, action, idx, emptyText = 'select') {
                const el = document.getElementById(id);
                el.className = content ? 'team-item filled' : 'team-item';
                el.onclick = content ? () => deselect(action, idx) : null;
                const clear = content ? '<span class="team-item-clear">clear</span>' : '';
                const empty = `<div class="team-item-empty">${emptyText}</div>`;
                el.innerHTML = `
                    <div class="team-item-head">
                        <span class="team-item-role">${role}</span>
                        ${clear}
                    </div>
                    ${content || empty}
                `;
            }
            if (selection.deck) {
                const thumbs = selection.deck.cards.map(c =>
                    `<img class="team-item-thumb" src="/api/images/${c.id || '10001'}.png" onerror="hideBrokenImage(this)">`
                ).join('');
                setSlot('team-slot-deck', 'Deck', `
                    <div class="team-item-body">
                        <div class="team-item-thumbs">${thumbs}</div>
                        <div class="team-item-text">
                            <span class="team-item-name">${selection.deck.name}</span>
                            <span class="team-item-sub">Slot ${selection.deck.id}</span>
                        </div>
                    </div>
                `, 'deck', null, 'select deck');
            } else {
                setSlot('team-slot-deck', 'Deck', null, 'deck', null, 'select deck');
            }
            if (selection.friend) {
                setSlot('team-slot-friend', 'Friend', `
                    <div class="team-item-body">
                        <img class="team-item-portrait" src="/api/images/${selection.friend.support_card_id || '10001'}.png" onerror="hideBrokenImage(this)">
                        <div class="team-item-text">
                            <span class="team-item-name">${selection.friend.support_name || 'Unknown'}</span>
                            <span class="team-item-sub">${selection.friend.type || '?'} | LB${selection.friend.limit_break_count ?? '?'}</span>
                        </div>
                    </div>
                `, 'friend', null, 'select friend');
            } else {
                setSlot('team-slot-friend', 'Friend', null, 'friend', null, 'select friend');
            }
            if (selection.trainee) {
                setSlot('team-slot-trainee', 'Trainee', `
                    <div class="team-item-body">
                        <img class="team-item-portrait" src="/api/images/${selection.trainee.id || '100101'}.png" onerror="hideBrokenImage(this)">
                        <div class="team-item-text">
                            <span class="team-item-name">${selection.trainee.name || 'Unknown'}</span>
                        </div>
                    </div>
                `, 'trainee', null, 'select trainee');
            } else {
                setSlot('team-slot-trainee', 'Trainee', null, 'trainee', null, 'select trainee');
            }
            ['team-slot-vet1', 'team-slot-vet2'].forEach((id, i) => {
                const vet = selection.veterans[i];
                if (vet) {
                    setSlot(id, `Parent ${i + 1}`, `
                        <div class="team-item-body">
                            <img class="team-item-portrait" src="/api/images/${vet.card_id || '100101'}.png" onerror="hideBrokenImage(this)">
                            <div class="team-item-text">
                                <span class="team-item-name">${vet.name || 'Unknown'}</span>
                                <span class="team-item-sub">${rankLabel(vet.rank)}</span>
                            </div>
                        </div>
                    `, 'vet', i, 'select parent');
                } else if (i === 1 && selection.guestParent) {
                    const g = selection.guestParent;
                    setSlot(id, 'Guest ★', `
                        <div class="team-item-body">
                            <img class="team-item-portrait" src="/api/images/${g.card_id || '100101'}.png" onerror="hideBrokenImage(this)">
                            <div class="team-item-text">
                                <span class="team-item-name">${escapeHtml(g.name || ('#' + g.trained_chara_id))}</span>
                                <span class="team-item-sub">borrowed · ${rankLabel(g.rank)}</span>
                            </div>
                        </div>
                    `, 'guest', i, 'select parent');
                } else {
                    setSlot(id, `Parent ${i + 1}`, null, 'vet', i, 'select parent');
                }
            });
            syncStartButton();
            renderCareerSummary();
        }
                function updateVetSelectability() {
            // A guest fills the 2nd parent slot, so only 1 owned parent may be picked alongside it.
            const cap = selection.guestParent ? 1 : 2;
            const full = selection.veterans.length >= cap;
            document.querySelectorAll('#parent-grid .grid-card').forEach(card => {
                if (card.classList.contains('selected')) {
                    card.classList.remove('vet-full');
                } else {
                    card.classList.toggle('vet-full', full);
                }
            });
            syncStartButton();
        }
        function clampValue(value, min, max) {
            return Math.min(Math.max(value, min), max);
        }
        let activeSparkCard = null;
        let activeSparkTooltip = null;
        function positionSparkTooltip(card, tooltip = card.querySelector('.sparks-tooltip')) {
            if (!card || !tooltip) return;
            const rect = card.getBoundingClientRect();
            const tooltipRect = tooltip.getBoundingClientRect();
            const tooltipWidth = Math.min(tooltipRect.width || 620, window.innerWidth - 16);
            const tooltipHeight = tooltipRect.height || 320;
            const x = clampValue(rect.left + rect.width / 2, tooltipWidth / 2 + 8, window.innerWidth - tooltipWidth / 2 - 8);
            const y = Math.max(8, rect.top - tooltipHeight - 10);
            tooltip.style.setProperty('--tooltip-left', `${x}px`);
            tooltip.style.setProperty('--tooltip-top', `${y}px`);
        }
        function bindSparkTooltips(selector = '#parent-grid .grid-card') {
            // Shared by the Parents and Guest Parents grids. Only strays that are currently parked on
            // body (an actively-shown tooltip) get cleaned up; hide() re-homes tooltips into their card,
            // so re-rendering one grid never orphans another grid's tooltip.
            document.querySelectorAll('body > .sparks-tooltip').forEach(tooltip => tooltip.remove());
            document.querySelectorAll(selector).forEach(card => {
                const tooltip = card.querySelector('.sparks-tooltip');
                if (!tooltip) return;
                card.classList.add('has-sparks');
                const show = () => {
                    if (tooltip.parentElement !== document.body) document.body.appendChild(tooltip);
                    activeSparkCard = card;
                    activeSparkTooltip = tooltip;
                    positionSparkTooltip(card, tooltip);
                    tooltip.classList.add('is-visible');
                };
                const hide = () => {
                    if (activeSparkCard === card) {
                        activeSparkCard = null;
                        activeSparkTooltip = null;
                    }
                    tooltip.classList.remove('is-visible');
                    if (tooltip.parentElement === document.body) card.appendChild(tooltip);
                };
                tooltip.addEventListener('click', event => event.stopPropagation());
                tooltip.addEventListener('mousedown', event => event.stopPropagation());
                card.addEventListener('mouseenter', show);
                card.addEventListener('mouseleave', hide);
                card.addEventListener('focusin', show);
                card.addEventListener('focusout', hide);
            });
        }
        document.addEventListener('scroll', () => {
            if (activeSparkCard && activeSparkTooltip) positionSparkTooltip(activeSparkCard, activeSparkTooltip);
        }, true);
        window.addEventListener('resize', () => {
            if (activeSparkCard && activeSparkTooltip) positionSparkTooltip(activeSparkCard, activeSparkTooltip);
        });
        function friendKey(friend) {
            return `${friend.viewer_id}:${friend.support_card_id}`;
        }
        function normalizedCardName(value) {
            return String(value || '').toLowerCase().replace(/\([^)]*\)/g, '').replace(/[^a-z0-9]+/g, '');
        }
        function friendAllowed(friend) {
            if (!friend) return false;
            const friendId = String(friend.support_card_id || '');
            const friendName = normalizedCardName(friend.support_name);
            if (selection.deck) {
                const deckIds = new Set(selection.deck.cards.map(card => String(card.id || '')));
                if (deckIds.has(friendId)) return false;
                const deckNames = new Set(selection.deck.cards.map(card => normalizedCardName(card.name)));
                if (friendName && deckNames.has(friendName)) return false;
            }
            if (selection.trainee && friendName && normalizedCardName(selection.trainee.name) === friendName) return false;
            return true;
        }
        // Friend-support browse filter: by card type (Speed/Stamina/Power/Guts/Wit/Pal/Group,
        // matching friend.type) and by name search. Applied on top of friendAllowed (dedup vs deck).
        const friendFilter = { type: 'all', search: '' };
        // Parent + guest-parent library filters — declared HERE (before the wiring below references
        // them) so they're initialized when the init code runs; the match/apply fns live further down.
        const parentFilter = { search: '', stat: 'all', sort: 'default' };
        // Manual trainee-deletion state: `mode` = the "Delete mode" switch is on; `ids` = the
        // trained_chara_ids the user has picked to release. Locked and configured-parent trainees
        // are rejected client-side (and the backend refuses them too).
        const parentDelete = { mode: false, ids: new Set(), busy: false };
        const guestFilter = { search: '', stat: 'all', sort: 'default' };
        function getVisibleFriends() {
            const friends = (dashData && dashData.friends) || [];
            const q = friendFilter.search.trim().toLowerCase();
            const t = friendFilter.type;
            return friends.filter(friendAllowed).filter(f => {
                if (t !== 'all' && String(f.type || '').toLowerCase() !== t.toLowerCase()) return false;
                if (q && !String(f.support_name || '').toLowerCase().includes(q)) return false;
                return true;
            });
        }
        function clearInvalidFriendSelection() {
            if (selection.friend && !friendAllowed(selection.friend)) {
                selection.friend = null;
            }
        }
        function syncFriendSelection() {
            const visibleFriends = (dashData && dashData.visibleFriends) || [];
            document.querySelectorAll('#friend-grid .grid-card').forEach((el, i) => {
                const friend = visibleFriends[i];
                el.classList.toggle('selected', Boolean(selection.friend && friend && friendKey(selection.friend) === friendKey(friend)));
            });
        }
        function findDeckIndexForCareer(activeCareer) {
            const decks = (dashData && dashData.validDecks) || [];
            if (!activeCareer || !decks.length) return -1;
            if (activeCareer.deck_id) {
                const deckIdx = decks.findIndex(d => Number(d.id) === Number(activeCareer.deck_id));
                if (deckIdx >= 0) return deckIdx;
            }
            const supportIds = (activeCareer.support_card_ids || []).map(id => String(id)).filter(Boolean);
            if (!supportIds.length) return -1;
            const careerSet = new Set(supportIds);
            return decks.findIndex(deck => {
                const deckIds = (deck.cards || []).map(card => String(card.id || '')).filter(Boolean);
                return deckIds.length === careerSet.size && deckIds.every(id => careerSet.has(id));
            });
        }
        function selectCareerDeck(activeCareer) {
            const deckIdx = findDeckIndexForCareer(activeCareer);
            if (deckIdx >= 0) {
                selection.deck = dashData.validDecks[deckIdx];
                const deckEls = document.querySelectorAll('.deck-container');
                if (deckEls[deckIdx]) deckEls[deckIdx].classList.add('selected');
                return;
            }
            const supportCards = (activeCareer && activeCareer.support_cards) || [];
            if (supportCards.length) {
                selection.deck = {
                    id: activeCareer.deck_id || 'active',
                    name: activeCareer.deck_id ? `Deck ${activeCareer.deck_id}` : 'Active career deck',
                    cards: supportCards
                };
            }
        }
        function selectCareerFriend(activeCareer) {
            if (!activeCareer || !activeCareer.friend_viewer_id || !activeCareer.friend_card_id) return;
            state.pendingFriendSelection = {
                viewer_id: String(activeCareer.friend_viewer_id),
                support_card_id: String(activeCareer.friend_card_id)
            };
            if (activeCareer.friend) {
                selection.friend = {
                    ...activeCareer.friend,
                    viewer_id: String(activeCareer.friend_viewer_id),
                    support_card_id: String(activeCareer.friend_card_id)
                };
            }
        }
        async function loadRaceData() {
            try {
                const raceRes = await fetch('/assets/data/uma_race_data.json');
                const data = await raceRes.json();
                state.raceData = Array.isArray(data.races) ? data.races : [];
                syncSelectedPresetRaces();
                renderRaces();
            } catch (e) {}
        }

        // After the server regenerates data/*.json from master.mdb, pull the fresh content into the UI:
        // re-fetch races AND invalidate the skill cache so NEW skills appear in the picker (the skill
        // list is cached once and would otherwise stay stale until a full page reload -- the "skills too"
        // gap). Used by both the master.mdb path-save flow and the REFRESH button.
        async function refreshGameDataUI() {
            skillDataCache = null;      // force /api/skills re-fetch (new skills)
            await loadRaceData();       // re-fetch + re-render the race schedule (new races)
            try { await loadSkillData(); } catch (e) {}   // warm the regenerated skill list
        }

        function getCurrentPreset() {
            return (state.presets || []).find(p => p.name === state.selectedPreset);
        }

        function normalizePresetName(value) {
            return String(value || '').trim().replace(/[^a-zA-Z0-9._ -]+/g, '').replace(/\s+/g, ' ').trim();
        }

        function presetNameExists(name) {
            const normalized = normalizePresetName(name).toLowerCase();
            return Boolean(normalized && (state.presets || []).some(p => p.name.toLowerCase() === normalized));
        }

        function syncSelectedPresetRaces() {
            const current = getCurrentPreset();
            state.selectedRaces = (current?.extra_race_list || [])
                .map(id => parseInt(id, 10))
                .filter(id => Number.isFinite(id));
            state.racesDirty = false;
            updateRaceSaveStatus();
            applyTraineeGoals();
        }

        async function applyTraineeGoals() {
            // URA/Unity: REPLACE the schedule with the SELECTED trainee's career-goal races, live on
            // every trainee change (so you can compare trainees). MANT keeps its manual extra_race_list.
            // Each goal maps to a grid race by (turn, name) -- the two data sources use different
            // program_ids for the same race, so name+turn is the stable key. Renders as normal selected
            // races (the proven path), so they actually appear in the grid.
            state.goalInfo = {};
            const tid = selection.trainee && selection.trainee.id;
            if (!tid || state.scenarioType === "Mant" || !state.raceData.length) { renderRaces(); return; }
            try {
                const data = await apiJson(`/api/career_goals/${tid}`);
                const ids = [];
                const info = {};
                (data.goals || []).forEach(g => {
                    const race = state.raceData.find(r => Number(r.turn) === Number(g.turn) && r.name === g.race);
                    if (race) raceKeys(race).forEach(id => {
                        if (!ids.includes(id)) ids.push(id);
                        info[id] = g.require || 'Goal';   // maps each race key -> the goal's requirement
                    });
                });
                // Do NOT overwrite the user's schedule (state.selectedRaces / the preset's
                // extra_race_list) with the goals -- goals are shown READ-ONLY in renderRaces via
                // goalInfo, so switching trainees never rewrites the saved schedule.
                state.goalInfo = info;
            } catch (e) { /* offline / no goals -> leave the current selection */ }
            renderRaces();
        }

        function getYearSlots(yearIdx) {
            const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
            const periods = ['Early', 'Late'];
            const yearLabels = ['Junior Year', 'Classic Year', 'Senior Year'];
            const slots = [];
            for (const month of months) {
                for (const period of periods) {
                    const label = period + ' ' + month;
                    const datePrefix = yearLabels[yearIdx] + ' ' + label;
                    const races = state.raceData.filter(r => r.date.includes(datePrefix));
                    slots.push({ period: label, races: races, yearIdx: yearIdx });
                }
            }
            return slots;
        }

        function raceKeys(race) {
            const keys = [race.id, ...(race.legacy_ids || [])];
            return keys.map(id => parseInt(id)).filter(id => Number.isFinite(id));
        }

        function raceSelected(race) {
            return raceKeys(race).some(id => state.selectedRaces.includes(id));
        }

        function renderRaces() {
            if (!els.raceOptionsContent) return;
            els.raceOptionsContent.innerHTML = '';

            const yearLabels = ['Junior Year', 'Classic Year', 'Senior Year'];
            yearLabels.forEach((label, yi) => {
                const block = document.createElement('div');
                block.className = 'race-year-block';
                block.innerHTML = `<div class="race-year-title">${label}</div>`;

                const grid = document.createElement('div');
                grid.className = 'race-time-grid';

                const slots = getYearSlots(yi);
                slots.forEach((slot, si) => {
                    const cell = document.createElement('div');
                    cell.className = 'race-time-cell';

                    const slotIds = slot.races.flatMap(r => raceKeys(r));
                    const selectedInSlot = state.selectedRaces.filter(id => slotIds.includes(id));
                    const mainRaceId = selectedInSlot[0];
                    let selected = slot.races.find(r => raceKeys(r).includes(mainRaceId));
                    // No user pick here -> show the trainee's career GOAL race read-only (GOAL-badged),
                    // so goals are visible without ever being written into the saved schedule.
                    if (!selected) {
                        const goalId = slotIds.find(id => state.goalInfo[id]);
                        if (goalId) selected = slot.races.find(r => raceKeys(r).includes(goalId));
                    }

                    let html = `<div class="race-time-label">${slot.period}</div>`;
                    if (selected) {
                        // Is this selected race a CAREER GOAL (vs a manual pick)? -> show a GOAL badge
                        // + its requirement, so goals are distinguishable from your own added races.
                        const goalReq = raceKeys(selected).map(k => state.goalInfo[k]).find(Boolean);
                        const goalBadge = goalReq
                            ? `<span style="position:absolute;top:2px;left:2px;font-size:.5rem;font-weight:700;background:#ffb020;color:#000;padding:0 4px;border-radius:6px;letter-spacing:.5px;z-index:2">GOAL</span>`
                            : '';
                        const goalReqLine = goalReq
                            ? `<div class="race-cell-goal-req" style="font-size:.55rem;font-weight:600;color:#ffb020">◎ ${escapeHtml(goalReq)}</div>`
                            : '';
                        html += `
                            <div class="race-cell-selected-img" style="position:relative;${goalReq ? 'box-shadow:0 0 0 2px #ffb020 inset;border-radius:6px' : ''}">
                                <img src="/races/${encodeURIComponent(selected.name)}.png" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'">
                                <div class="race-image-fallback race-image-fallback-${(selected.terrain || 'turf').toLowerCase()}" style="display:none">${selected.type}</div>
                                <span class="race-cell-selected-grade badge-${selected.type.toLowerCase().replace('-', '')}">${selected.type}</span>
                                ${goalBadge}
                            </div>
                            <div class="race-cell-selected-name">${escapeHtml(selected.name)}</div>
                            ${goalReqLine}
                        `;
                    } else {
                        html += `<div class="race-time-plus">+</div>`;
                    }

                    cell.innerHTML = html;
                    cell.onclick = () => openSlotPopup(slot, yi);
                    grid.appendChild(cell);
                });

                block.appendChild(grid);
                els.raceOptionsContent.appendChild(block);
            });
        }

        // Per-race "what you gain" side note for the picker: fans for finishing 1st (the reward)
        // plus the fan requirement to enter. Baked into uma_race_data.json from master.mdb; empty
        // string when an older JSON lacks the fields so the row just omits the line.
        function raceGainNote(race) {
            const parts = [];
            if (race.win_fans) parts.push(`<span class="gain">🏆 ${Number(race.win_fans).toLocaleString()} fans</span>`);
            if (race.entry_fans) parts.push(`needs ${Number(race.entry_fans).toLocaleString()} fans`);
            return parts.join(' · ');
        }

        function openSlotPopup(slot, yearIdx) {
            const yearLabels = ['Junior Year', 'Classic Year', 'Senior Year'];
            els.racePopupTitle.textContent = `${yearLabels[yearIdx]} - ${slot.period}`;
            els.racePopupBody.innerHTML = '';

            if (slot.races.length === 0) {
                els.racePopupBody.innerHTML = '<div class="race-slot-popup-empty">No races available</div>';
            } else {
                const list = document.createElement('div');
                list.className = 'race-slot-popup-list';

                const slotIds = slot.races.flatMap(r => raceKeys(r));

                slot.races.forEach(race => {
                    const myIds = raceKeys(race);
                    const selectedInSlot = state.selectedRaces.filter(id => slotIds.includes(id));
                    const selIndex = selectedInSlot.findIndex(id => myIds.includes(id));
                    const isSelected = selIndex !== -1;

                    let badgeHtml = '<div class="race-slot-popup-check">✓</div>';
                    if (isSelected && state.scenarioType === "Mant" && selectedInSlot.length > 0) {
                        if (selIndex === 0) {
                            badgeHtml = '<div class="race-slot-popup-check main-race" style="font-size: 0.7rem; font-weight: bold; width: auto; padding: 0 8px; border-radius: 12px; background: rgba(255,255,255,0.2);">MAIN</div>';
                        } else {
                            badgeHtml = `<div class="race-slot-popup-check overwrite-race" style="font-size: 0.7rem; font-weight: bold; width: auto; padding: 0 8px; border-radius: 12px; background: rgba(255,255,255,0.1);">RIVAL OVERWRITE ${selIndex}</div>`;
                        }
                    }

                    const gainNote = raceGainNote(race);
                    const item = document.createElement('div');
                    item.className = `race-slot-popup-item ${isSelected ? 'on' : ''}`;
                    item.innerHTML = `
                        <div class="race-slot-popup-img">
                            <img src="/races/${encodeURIComponent(race.name)}.png" data-terrain="${race.terrain || ''}" data-grade="${race.type || ''}" onerror="raceImgFallback(this)">
                        </div>
                        <div class="race-slot-popup-info">
                            <div class="race-slot-popup-name-row">
                                <span class="race-slot-popup-grade badge-${race.type.toLowerCase().replace('-', '')}">${race.type}</span>
                                <span class="race-slot-popup-name">${escapeHtml(race.name)}</span>
                            </div>
                            <div class="race-slot-popup-meta">
                                <span class="race-slot-popup-terrain ${race.terrain.toLowerCase()}">${race.terrain}</span>
                                <span class="race-slot-popup-distance">${race.distance}</span>
                            </div>
                            ${gainNote ? `<div class="race-slot-popup-note">${gainNote}</div>` : ''}
                        </div>
                        ${badgeHtml}
                    `;
                    item.onclick = async () => {
                        const isMant = state.scenarioType === "Mant";

                        if (isSelected) {
                            state.selectedRaces = state.selectedRaces.filter(id => !myIds.includes(id));
                        } else {
                            if (!isMant) {
                                state.selectedRaces = state.selectedRaces.filter(id => !slotIds.includes(id));
                            }
                            state.selectedRaces.push(parseInt(race.id));
                        }

                        openSlotPopup(slot, yearIdx);
                        renderRaces();
                        markRacesDirty();
                    };
                    list.appendChild(item);
                });
                els.racePopupBody.appendChild(list);
            }
            els.racePopupOverlay.style.display = 'flex';
        }

        function updateRaceSaveStatus() {
            if (!els.raceSaveStatus) return;
            els.raceSaveStatus.textContent = state.racesDirty ? '● Unsaved' : '';
            els.raceSaveStatus.className = state.racesDirty ? 'race-save-status dirty' : 'race-save-status';
        }
        function markRacesDirty() {
            state.racesDirty = true;
            updateRaceSaveStatus();
        }
        async function saveRaces() {
            if (!state.selectedPreset) {
                if (els.raceSaveStatus) { els.raceSaveStatus.textContent = 'Select a preset first'; els.raceSaveStatus.className = 'race-save-status dirty'; }
                return;
            }
            if (els.saveRacesBtn) els.saveRacesBtn.disabled = true;
            if (els.raceSaveStatus) { els.raceSaveStatus.textContent = 'Saving...'; els.raceSaveStatus.className = 'race-save-status'; }
            try {
                const current = getCurrentPreset();
                if (current) current.extra_race_list = [...state.selectedRaces];
                const data = await apiJson('/api/presets/save_races', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ preset_name: state.selectedPreset, races: state.selectedRaces })
                });
                if (data && data.success === false) throw new Error(data.detail || 'save failed');
                state.racesDirty = false;
                if (els.raceSaveStatus) { els.raceSaveStatus.textContent = `✓ Saved (${state.selectedRaces.length} races)`; els.raceSaveStatus.className = 'race-save-status saved'; }
            } catch (e) {
                if (els.raceSaveStatus) { els.raceSaveStatus.textContent = e.message || 'Failed to save'; els.raceSaveStatus.className = 'race-save-status dirty'; }
            } finally {
                if (els.saveRacesBtn) els.saveRacesBtn.disabled = false;
            }
        }

        function getTurnFromDate(dateStr) {
            const match = dateStr.match(/(\d+)年(\d+)月(前|後)半/);
            if (!match) return 0;
            const year = parseInt(match[1]);
            const month = parseInt(match[2]);
            const half = match[3] === '前' ? 0 : 1;
            return (year - 1) * 24 + (month - 1) * 2 + half + 1;
        }

        function bindRaceHandlers() {
            els.racePopupClose?.addEventListener('click', () => {
                els.racePopupOverlay.style.display = 'none';
            });
            els.racePopupOverlay?.addEventListener('click', (e) => {
                if (e.target === els.racePopupOverlay) els.racePopupOverlay.style.display = 'none';
            });
            els.saveRacesBtn?.addEventListener('click', saveRaces);

            makeSectionToggle('race-toggle', 'race-chevron', 'race-body', false);
        }

        let skillDataCache = null;
        let activeEditTier = null;
        let activeSkillFilter = null;
        let activeColorFilter = null;

        const SKILL_FILTERS = [
            { id: 101, label: 'Front' },
            { id: 102, label: 'Pace' },
            { id: 103, label: 'Late' },
            { id: 104, label: 'End' },
            { id: 201, label: 'Short' },
            { id: 202, label: 'Mile' },
            { id: 203, label: 'Medium' },
            { id: 204, label: 'Long' },
            { id: 502, label: 'Dirt' },
            { id: 'turf', label: 'Turf' }
        ];

        const COLOR_FILTERS = [
            { id: 'green', label: 'Green', color: '#4ade80', iconPrefixes: ['1001', '1002', '1003', '1004', '1005', '1006'] },
            { id: 'blue', label: 'Blue', color: '#60a5fa', iconPrefixes: ['2002'] },
            { id: 'yellow', label: 'Yellow', color: '#fbbf24', iconPrefixes: ['2001', '2004', '2005', '2006', '2009'] },
            { id: 'red', label: 'Red', color: '#f87171', iconPrefixes: ['3001', '3002', '3004', '3005', '3007'] }
        ];

        async function loadSkillData() {
            if (skillDataCache) return skillDataCache;
            try {
                const res = await apiJson('/api/skills');
                if (res.success && res.skills) {
                    const uniqueMap = new Map();
                    Object.entries(res.skills).forEach(([id, s]) => {
                        if (!uniqueMap.has(s.name)) {
                            uniqueMap.set(s.name, { id, ...s, tags: new Set(s.tags || []) });
                        } else {
                            const existing = uniqueMap.get(s.name);
                            if (s.rarity > existing.rarity) existing.rarity = s.rarity;
                            (s.tags || []).forEach(t => existing.tags.add(t));
                        }
                    });
                    skillDataCache = Array.from(uniqueMap.values()).map(s => ({ ...s, tags: Array.from(s.tags) }));
                    skillDataCache.sort((a, b) => a.name.localeCompare(b.name));
                    return skillDataCache;
                }
            } catch (e) {}
            return [];
        }

        function renderSkillFilters() {
            const container = document.getElementById('skill-filters');
            if (!container) return;
            
            let html = '<div style="display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 4px;">';
            for (const filter of SKILL_FILTERS) {
                const isActive = activeSkillFilter === filter.id;
                const bg = isActive ? 'rgba(var(--accent-primary-rgb), 0.2)' : 'rgba(255,255,255,0.05)';
                const border = isActive ? 'var(--accent-primary)' : 'transparent';
                const color = isActive ? 'var(--text-main)' : '#a1a1aa';
                html += `<div class="skill-filter-chip affinity-filter" data-id="${filter.id}" style="padding: 0.35rem 0.75rem; border-radius: 1rem; font-size: 0.75rem; cursor: pointer; background: ${bg}; border: 1px solid ${border}; color: ${color}; font-weight: bold; transition: all 0.1s;">${filter.label}</div>`;
            }
            html += '</div><div style="display: flex; flex-wrap: wrap; gap: 4px;">';
            
            for (const filter of COLOR_FILTERS) {
                const isActive = activeColorFilter === filter.id;
                const bg = isActive ? `${filter.color}33` : 'rgba(255,255,255,0.05)';
                const border = isActive ? filter.color : 'transparent';
                const color = isActive ? 'var(--text-main)' : filter.color;
                html += `<div class="skill-filter-chip color-filter" data-color="${filter.id}" style="padding: 0.35rem 0.75rem; border-radius: 1rem; font-size: 0.75rem; cursor: pointer; background: ${bg}; border: 1px solid ${border}; color: ${color}; font-weight: bold; transition: all 0.1s;">${filter.label}</div>`;
            }
            html += '</div>';
            
            container.innerHTML = html;
            
            container.querySelectorAll('.affinity-filter').forEach(el => {
                el.addEventListener('click', () => {
                    let tagId = el.getAttribute('data-id');
                    if (tagId !== 'turf') tagId = Number(tagId);
                    
                    if (activeSkillFilter === tagId) activeSkillFilter = null;
                    else activeSkillFilter = tagId;
                    
                    renderSkillFilters();
                    renderSkillList();
                });
            });

            container.querySelectorAll('.color-filter').forEach(el => {
                el.addEventListener('click', () => {
                    const colorId = el.getAttribute('data-color');
                    
                    if (activeColorFilter === colorId) activeColorFilter = null;
                    else activeColorFilter = colorId;
                    
                    renderSkillFilters();
                    renderSkillList();
                });
            });
        }

        function renderSkillList() {
            const query = (els.skillSearch?.value || '').toLowerCase();
            const skills = skillDataCache || [];
            
            let count = 0;
            let html = '';
            for (const s of skills) {
                if (query && !s.name.toLowerCase().includes(query)) continue;
                
                if (activeSkillFilter !== null) {
                    const skillTags = s.tags || [];
                    if (activeSkillFilter === 'turf') {
                        if (skillTags.includes(502)) continue;
                    } else {
                        if (!skillTags.includes(activeSkillFilter)) continue;
                    }
                }
                
                if (activeColorFilter !== null) {
                    const iconId = String(s.icon_id || '');
                    const colorFilter = COLOR_FILTERS.find(filter => filter.id === activeColorFilter);
                    const skillColor = colorFilter && colorFilter.iconPrefixes.some(prefix => iconId.startsWith(prefix)) ? activeColorFilter : 'none';
                    
                    if (skillColor !== activeColorFilter) continue;
                }
                
                count++;
                
                html += `<div class="skill-list-item" data-name="${escapeAttr(s.name)}" style="padding: 0.5rem; background: rgba(255,255,255,0.03); border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 8px; transition: background 0.1s;">
                    <span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-main); font-size: 0.85rem;">${escapeHtml(s.name)}</span>
                </div>`;
            }
            
            if (els.skillList) {
                if (count === 0) {
                    els.skillList.innerHTML = `<div style="padding: 1rem; color: #a1a1aa; font-size: 0.85rem;">No skills found.</div>`;
                } else {
                    els.skillList.innerHTML = html;
                    els.skillList.querySelectorAll('.skill-list-item').forEach(el => {
                        el.addEventListener('click', () => {
                            const name = el.getAttribute('data-name');
                            addSkillToFocusedArea(name);
                        });
                        el.addEventListener('mouseenter', () => el.style.background = 'rgba(255,255,255,0.1)');
                        el.addEventListener('mouseleave', () => el.style.background = 'rgba(255,255,255,0.03)');
                    });
                }
            }
        }

        function renderSkillEditorRightSide() {
            const current = getCurrentPreset();
            if (!current) {
                if (els.skillTiersContainer) els.skillTiersContainer.innerHTML = '';
                if (els.skillBlacklistContainer) els.skillBlacklistContainer.innerHTML = '';
                if (els.skillGoalContainer) els.skillGoalContainer.innerHTML = '';
                return;
            }

            let tiersHtml = '';
            // TIER 0: the most-important skills -- bought immediately (checked every 24 turns) in every
            // mode, ahead of every normal tier. A fixed dropzone above TIER 1 (can't be deleted).
            const tier0 = current.learn_skill_tier0 || [];
            const t0Active = activeEditTier === 'tier0';
            const t0Items = tier0.map(s =>
                `<div class="skill-tag">
                    ${escapeHtml(s)} <span class="skill-tag-del" data-tier0="true" data-skill="${escapeAttr(s)}">&times;</span>
                </div>`
            ).join('');
            tiersHtml += `
            <div class="skill-tier-dropzone tier-zero ${t0Active ? 'is-active' : ''}" data-tier="tier0">
                <div class="skill-tier-header">
                    <span class="skill-tier-label">TIER 0 &middot; BUY NOW</span>
                </div>
                <div class="skill-tag-list">
                    ${t0Items}
                </div>
            </div>`;
            const storedTiers = current.learn_skill_list || [];
            const tiers = storedTiers.length > 0 ? storedTiers : [[]];
            tiers.forEach((tier, i) => {
                const isActive = activeEditTier === i;
                const itemsHtml = tier.map(s =>
                    `<div class="skill-tag">
                        ${escapeHtml(s)} <span class="skill-tag-del" data-tier="${i}" data-skill="${escapeAttr(s)}">&times;</span>
                    </div>`
                ).join('');

                tiersHtml += `
                <div class="skill-tier-dropzone ${isActive ? 'is-active' : ''}" data-tier="${i}">
                    <div class="skill-tier-header">
                        <span class="skill-tier-label">TIER ${i+1}</span>
                        <button class="btn btn-sm btn-danger-soft skill-editor-action tier-del-btn" data-tier="${i}">DEL</button>
                    </div>
                    <div class="skill-tag-list">
                        ${itemsHtml}
                    </div>
                </div>`;
            });
            if (els.skillTiersContainer) els.skillTiersContainer.innerHTML = tiersHtml;

            // BEFORE GOAL RACES: its own list (learn_skill_before_goal), bought by the runner right before
            // each hard career-goal race. Focused with activeEditTier === 'goal'.
            if (els.skillGoalContainer) {
                els.skillGoalContainer.classList.toggle('is-active', activeEditTier === 'goal');
                const goalSkills = current.learn_skill_before_goal || [];
                const goalTags = goalSkills.map(s =>
                    `<div class="skill-tag">${escapeHtml(s)} <span class="skill-tag-del" data-goal="true" data-skill="${escapeAttr(s)}">&times;</span></div>`
                ).join('');
                els.skillGoalContainer.innerHTML = goalTags
                    ? `<div class="skill-tag-list">${goalTags}</div>`
                    : `<span class="skill-goal-empty">Click here, then pick skills on the right</span>`;
                els.skillGoalContainer.onclick = (e) => {
                    if (e.target.classList.contains('skill-tag-del')) return;
                    activeEditTier = 'goal';
                    renderSkillEditorRightSide();
                };
            }

            if (els.skillBlacklistContainer) {
                const isBlActive = activeEditTier === null;
                els.skillBlacklistContainer.classList.toggle('is-active', isBlActive);

                const blacklist = current.learn_skill_blacklist || [];
                els.skillBlacklistContainer.innerHTML = blacklist.map(s =>
                    `<div class="skill-tag blacklist">
                        ${escapeHtml(s)} <span class="skill-tag-del" data-blacklist="true" data-skill="${escapeAttr(s)}">&times;</span>
                    </div>`
                ).join('');
            }

            els.skillTiersContainer?.querySelectorAll('.skill-tier-dropzone').forEach(el => {
                el.addEventListener('click', (e) => {
                    if (e.target.classList.contains('tier-del-btn') || e.target.classList.contains('skill-tag-del')) return;
                    const t = el.getAttribute('data-tier');
                    activeEditTier = t === 'tier0' ? 'tier0' : parseInt(t);
                    renderSkillEditorRightSide();
                });
            });
            if (els.skillBlacklistContainer) {
                els.skillBlacklistContainer.onclick = (e) => {
                    if (e.target.classList.contains('skill-tag-del')) return;
                    activeEditTier = null;
                    renderSkillEditorRightSide();
                };
            }

            els.skillTiersContainer?.querySelectorAll('.tier-del-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const idx = parseInt(btn.getAttribute('data-tier'));
                    current.learn_skill_list = current.learn_skill_list || [];
                    current.learn_skill_list.splice(idx, 1);
                    if (activeEditTier === idx) activeEditTier = null;
                    else if (activeEditTier > idx) activeEditTier--;
                    await savePresetConfig();
                    renderSkillEditorRightSide();
                });
            });

            document.querySelectorAll('.skill-tag-del').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const skillName = btn.getAttribute('data-skill');
                    if (btn.hasAttribute('data-tier0')) {
                        current.learn_skill_tier0 = (current.learn_skill_tier0 || []).filter(s => s !== skillName);
                    } else if (btn.hasAttribute('data-goal')) {
                        current.learn_skill_before_goal = (current.learn_skill_before_goal || []).filter(s => s !== skillName);
                    } else if (btn.hasAttribute('data-blacklist')) {
                        current.learn_skill_blacklist = current.learn_skill_blacklist.filter(s => s !== skillName);
                    } else {
                        const tierIdx = parseInt(btn.getAttribute('data-tier'));
                        current.learn_skill_list[tierIdx] = current.learn_skill_list[tierIdx].filter(s => s !== skillName);
                    }
                    await savePresetConfig();
                    renderSkillEditorRightSide();
                });
            });
        }

        async function addSkillToFocusedArea(name) {
            const current = getCurrentPreset();
            if (!current) return;

            if (activeEditTier === 'tier0') {
                if (!current.learn_skill_tier0) current.learn_skill_tier0 = [];
                if (!current.learn_skill_tier0.includes(name)) current.learn_skill_tier0.push(name);
            } else if (activeEditTier === 'goal') {
                if (!current.learn_skill_before_goal) current.learn_skill_before_goal = [];
                if (!current.learn_skill_before_goal.includes(name)) current.learn_skill_before_goal.push(name);
            } else if (activeEditTier === null) {
                if (!current.learn_skill_blacklist) current.learn_skill_blacklist = [];
                if (!current.learn_skill_blacklist.includes(name)) {
                    current.learn_skill_blacklist.push(name);
                }
            } else {
                if (!current.learn_skill_list) current.learn_skill_list = [];
                if (!current.learn_skill_list[activeEditTier]) current.learn_skill_list[activeEditTier] = [];
                if (!current.learn_skill_list[activeEditTier].includes(name)) {
                    current.learn_skill_list[activeEditTier].push(name);
                }
            }
            await savePresetConfig();
            renderSkillEditorRightSide();
        }

        function initSkillEditor() {
            if (!state.selectedPreset) return;
            activeEditTier = 0;

            els.skillModal.style.display = 'flex';
            if (els.skillSearch) els.skillSearch.value = '';
            activeSkillFilter = null;
            activeColorFilter = null;

            loadSkillData().then(() => {
                renderSkillFilters();
                renderSkillList();
            });
            renderSkillEditorRightSide();
        }

        async function savePresetConfig() {
            if (!state.selectedPreset || !state.presets) return;
            const current = getCurrentPreset();
            if (!current) return;

            current.running_style = parseInt(els.presetRunningStyle?.value) || 1;
            readSettingsIntoPreset(current);

            try {
                await apiJson('/api/presets', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ preset: current })
                });
            } catch (e) {}
        }

        function populatePresetUI() {
            if (!state.selectedPreset || !state.presets) return;
            const current = getCurrentPreset();
            if (!current) return;

            if (els.presetRunningStyle) els.presetRunningStyle.value = current.running_style || 1;
            syncScheduleControls();   // reflect THIS preset's per-preset use_race_schedule
            populateSettingsUI();     // reflect THIS preset's Settings-tab tunables
        }

        // === SETTINGS tab (Trainee | Settings nav): behaviour tunables saved onto the active preset ===
        const SPARK_COLOUR_FIELDS = { blue: 'set-spark-blue', pink: 'set-spark-pink',
                                      green: 'set-spark-green', white: 'set-spark-white' };
        function readSettingsIntoPreset(current) {
            const num = (id) => { const v = parseFloat(document.getElementById(id)?.value); return Number.isFinite(v) ? v : null; };
            const setOrDel = (key, v) => { if (v === null) delete current[key]; else current[key] = v; };
            const cutoff = num('set-hint-cutoff');
            setOrDel('hint_priority_until_turn', cutoff === null ? null : Math.round(cutoff));
            setOrDel('hint_presenior_boost', num('set-hint-boost'));
            const jr = document.getElementById('set-junior-rec');
            if (jr) current.junior_recreation = !!jr.checked;
            const jp = num('set-junior-partners');
            setOrDel('junior_recreation_max_partners', jp === null ? null : Math.round(jp));
            // Inheritance sparks: per-colour priority (0-5) + optional TP reroll
            for (const [colour, id] of Object.entries(SPARK_COLOUR_FIELDS)) {
                const v = num(id);
                setOrDel(`spark_priority_${colour}`, v === null ? null : Math.max(0, Math.min(5, Math.round(v))));
            }
            const sr = document.getElementById('set-spark-reroll');
            if (sr) current.spark_reroll = !!sr.checked;
            const srMax = num('set-spark-reroll-max');
            setOrDel('spark_reroll_max', srMax === null ? null : Math.max(0, Math.round(srMax)));
            const tpFloor = num('set-spark-tp-floor');
            setOrDel('spark_reroll_tp_floor', tpFloor === null ? null : Math.max(0, Math.round(tpFloor)));
            const ef = document.getElementById('set-entry-farm');
            if (ef) current.fan_eligibility_farm = !!ef.checked;
            const ew = num('set-entry-window');
            setOrDel('fan_farm_window', ew === null ? null : Math.max(1, Math.round(ew)));
        }
        function populateSettingsUI() {
            const current = getCurrentPreset() || {};
            const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = (v === undefined || v === null) ? '' : v; };
            setVal('set-hint-cutoff', current.hint_priority_until_turn);
            setVal('set-hint-boost', current.hint_presenior_boost);
            setVal('set-junior-partners', current.junior_recreation_max_partners);
            const jr = document.getElementById('set-junior-rec');
            if (jr) jr.checked = current.junior_recreation !== false;   // default ON
            for (const [colour, id] of Object.entries(SPARK_COLOUR_FIELDS)) {
                setVal(id, current[`spark_priority_${colour}`]);
            }
            const sr = document.getElementById('set-spark-reroll');
            if (sr) sr.checked = current.spark_reroll === true;         // default OFF (spends TP)
            setVal('set-spark-reroll-max', current.spark_reroll_max);
            setVal('set-spark-tp-floor', current.spark_reroll_tp_floor);
            const ef = document.getElementById('set-entry-farm');
            if (ef) ef.checked = current.fan_eligibility_farm !== false;   // default ON
            setVal('set-entry-window', current.fan_farm_window);
            const label = document.getElementById('setup-settings-preset');
            if (label) label.textContent = state.selectedPreset || 'active';
        }
        let settingsHandlersBound = false;
        function bindSettingsHandlers() {
            if (settingsHandlersBound) return;   // renderDashboard re-runs on refresh; bind once
            settingsHandlersBound = true;
            const save = () => savePresetConfig();
            ['set-hint-cutoff', 'set-hint-boost', 'set-junior-partners', 'set-junior-rec',
             'set-spark-blue', 'set-spark-pink', 'set-spark-green', 'set-spark-white',
             'set-spark-reroll', 'set-spark-reroll-max', 'set-spark-tp-floor',
             'set-entry-farm', 'set-entry-window'].forEach(id =>
                document.getElementById(id)?.addEventListener('change', save));
            // Top nav: switch between the Trainee view and the Settings view
            document.querySelectorAll('.setup-ws-nav-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const view = btn.dataset.view;
                    document.querySelectorAll('.setup-ws-nav-btn').forEach(b => b.classList.toggle('is-active', b === btn));
                    document.querySelectorAll('.setup-ws-view').forEach(v => v.classList.toggle('is-active', v.dataset.view === view));
                    if (view === 'settings') populateSettingsUI();
                });
            });
        }

        function bindPresetHandlers() {
            bindSettingsHandlers();   // Settings-tab inputs + the Trainee|Settings top nav
            if (els.presetSelect) {
                els.presetSelect.addEventListener('change', async (e) => {
                    state.selectedPreset = e.target.value;
                    localStorage.setItem('uma_selected_preset', state.selectedPreset);
                    syncSelectedPresetRaces();
                    populatePresetUI();
                    renderRaces();
                });
            }

            const saveHandler = () => savePresetConfig();
            els.presetRunningStyle?.addEventListener('change', saveHandler);

            els.presetEditSkillsBtn?.addEventListener('click', () => {
                if (!state.selectedPreset) return;
                activeEditTier = 0;

                els.skillModal.style.display = 'flex';
                if (els.skillSearch) els.skillSearch.value = '';
                activeSkillFilter = null;

                loadSkillData().then(() => {
                    renderSkillFilters();
                    renderSkillList();
                });
                renderSkillEditorRightSide();
            });
            els.skillModalClose?.addEventListener('click', () => { els.skillModal.style.display = 'none'; });

            // SETUP WORKSPACE overlay: opened from the account-strip "TEAM / SETUP" pill
            // (wired in renderAccountStrip), closed with DONE. The library tabs switch
            // panels; opening the Friends tab lazily loads the friend list.
            if (els.setupWorkspaceClose) els.setupWorkspaceClose.addEventListener('click', () => {
                if (els.setupWorkspace) els.setupWorkspace.style.display = 'none';
            });
            // Mirror the reference build: assemble the SETUP workspace by MOVING the existing
            // setup sections into its left column (preserves all their wiring; no duplicate DOM).
            // Assemble the SETUP workspace left column: PRESET + DATA (master data) go into a
            // tab-toggled host (click a tab -> that section shows instantly); Discord stays inline
            // below (under both tabs); Race Schedule shows only under the PRESET tab. All sections
            // keep their original wiring (move, not copy).
            const setupLeftToggle = document.getElementById('setup-left-toggle');
            const setupLeftFixed = document.getElementById('setup-left-fixed');
            if (setupLeftToggle) {
                ['preset-section', 'master-data-section'].forEach(id => {
                    const sec = document.getElementById(id);
                    if (sec) setupLeftToggle.appendChild(sec);
                });
            }
            if (setupLeftFixed) {
                ['race-schedule-section', 'discord-webhook-section'].forEach(id => {
                    const sec = document.getElementById(id);
                    if (sec) setupLeftFixed.appendChild(sec);
                });
            }
            const setupLeftTabs = Array.from(document.querySelectorAll('.setup-left-tab'));
            function showSetupLeftSection(target) {
                setupLeftTabs.forEach(t => t.classList.toggle('is-active', t.dataset.target === target));
                ['preset-section', 'master-data-section'].forEach(id => {
                    const sec = document.getElementById(id);
                    if (sec) sec.style.display = (id === target) ? '' : 'none';
                });
                // Race Schedule belongs to the PRESET tab only -- hide it under DATA.
                const race = document.getElementById('race-schedule-section');
                if (race) race.style.display = (target === 'preset-section') ? '' : 'none';
                // Discord Webhook belongs to the DATA tab only -- hide it under PRESET (it lived in the
                // shared "fixed" area and showed under both tabs, so it looked duplicated).
                const wh = document.getElementById('discord-webhook-section');
                if (wh) wh.style.display = (target === 'master-data-section') ? '' : 'none';
            }
            setupLeftTabs.forEach(t => t.addEventListener('click', () => showSetupLeftSection(t.dataset.target)));
            showSetupLeftSection('preset-section');
            let setupFriendsLoaded = false;
            document.querySelectorAll('.setup-lib-tab').forEach(tab => {
                tab.addEventListener('click', () => {
                    const name = tab.dataset.tab;
                    document.querySelectorAll('.setup-lib-tab').forEach(t => t.classList.toggle('is-active', t === tab));
                    document.querySelectorAll('.setup-lib-panel').forEach(p => p.classList.toggle('is-active', p.dataset.panel === name));
                    if ((name === 'friends' || name === 'guests') && !setupFriendsLoaded) {
                        setupFriendsLoaded = true;
                        loadFriends();
                    }
                });
            });

            els.skillSearch?.addEventListener('input', renderSkillList);

            els.skillAddTierBtn?.addEventListener('click', async () => {
                const current = getCurrentPreset();
                if (!current) return;
                if (!current.learn_skill_list) current.learn_skill_list = [];
                current.learn_skill_list.push([]);
                activeEditTier = current.learn_skill_list.length - 1;
                await savePresetConfig();
                renderSkillEditorRightSide();
            });

            document.getElementById('skill-select-all-btn')?.addEventListener('click', async () => {
                const current = getCurrentPreset();
                if (!current) return;
                const visibleNodes = els.skillList?.querySelectorAll('.skill-list-item') || [];
                let changed = false;

                visibleNodes.forEach(node => {
                    const name = node.getAttribute('data-name');
                    if (activeEditTier === 'tier0' || activeEditTier === 'goal') {
                        const key = activeEditTier === 'goal' ? 'learn_skill_before_goal' : 'learn_skill_tier0';
                        if (!current[key]) current[key] = [];
                        if (!current[key].includes(name)) {
                            current[key].push(name);
                            changed = true;
                        }
                    } else if (activeEditTier === null) {
                        if (!current.learn_skill_blacklist) current.learn_skill_blacklist = [];
                        if (!current.learn_skill_blacklist.includes(name)) {
                            current.learn_skill_blacklist.push(name);
                            changed = true;
                        }
                    } else {
                        if (!current.learn_skill_list) current.learn_skill_list = [];
                        if (!current.learn_skill_list[activeEditTier]) current.learn_skill_list[activeEditTier] = [];
                        if (!current.learn_skill_list[activeEditTier].includes(name)) {
                            current.learn_skill_list[activeEditTier].push(name);
                            changed = true;
                        }
                    }
                });
                if (changed) {
                    await savePresetConfig();
                    renderSkillEditorRightSide();
                }
            });

            document.getElementById('skill-deselect-all-btn')?.addEventListener('click', async () => {
                const current = getCurrentPreset();
                if (!current) return;
                const visibleNodes = els.skillList?.querySelectorAll('.skill-list-item') || [];
                let changed = false;

                const namesToRemove = Array.from(visibleNodes).map(node => node.getAttribute('data-name'));

                if (activeEditTier === 'tier0' || activeEditTier === 'goal') {
                    const key = activeEditTier === 'goal' ? 'learn_skill_before_goal' : 'learn_skill_tier0';
                    if (current[key]) {
                        const originalLen = current[key].length;
                        current[key] = current[key].filter(s => !namesToRemove.includes(s));
                        if (current[key].length !== originalLen) changed = true;
                    }
                } else if (activeEditTier === null) {
                    if (current.learn_skill_blacklist) {
                        const originalLen = current.learn_skill_blacklist.length;
                        current.learn_skill_blacklist = current.learn_skill_blacklist.filter(s => !namesToRemove.includes(s));
                        if (current.learn_skill_blacklist.length !== originalLen) changed = true;
                    }
                } else {
                    if (current.learn_skill_list && current.learn_skill_list[activeEditTier]) {
                        const originalLen = current.learn_skill_list[activeEditTier].length;
                        current.learn_skill_list[activeEditTier] = current.learn_skill_list[activeEditTier].filter(s => !namesToRemove.includes(s));
                        if (current.learn_skill_list[activeEditTier].length !== originalLen) changed = true;
                    }
                }

                if (changed) {
                    await savePresetConfig();
                    renderSkillEditorRightSide();
                }
            });

            document.getElementById('skill-blacklist-all-btn')?.addEventListener('click', async () => {
                const current = getCurrentPreset();
                if (!current) return;
                const visibleNodes = els.skillList?.querySelectorAll('.skill-list-item') || [];
                let changed = false;

                if (!current.learn_skill_blacklist) current.learn_skill_blacklist = [];
                visibleNodes.forEach(node => {
                    const name = node.getAttribute('data-name');
                    if (!current.learn_skill_blacklist.includes(name)) {
                        current.learn_skill_blacklist.push(name);
                        changed = true;
                    }
                });

                if (changed) {
                    await savePresetConfig();
                    renderSkillEditorRightSide();
                }
            });
            document.getElementById('skill-clear-blacklist-btn')?.addEventListener('click', async () => {
                const current = getCurrentPreset();
                if (!current) return;
                if (current.learn_skill_blacklist && current.learn_skill_blacklist.length > 0) {
                    current.learn_skill_blacklist = [];
                    await savePresetConfig();
                    renderSkillEditorRightSide();
                }
            });

            els.presetAddBtn?.addEventListener('click', async () => {
                const newName = prompt("Enter new preset name:");
                if (!newName || !newName.trim()) return;
                const normalizedName = normalizePresetName(newName);
                if (!normalizedName) {
                    alert("Preset name cannot be empty.");
                    return;
                }
                if (presetNameExists(normalizedName)) {
                    alert("A preset with that name already exists.");
                    return;
                }

                const newPreset = {
                    name: normalizedName,
                    running_style: 1,
                    use_race_schedule: false,
                    learn_skill_tier0: [],
                    learn_skill_before_goal: [],
                    learn_skill_list: [],
                    learn_skill_blacklist: [],
                    extra_race_list: []
                };

                try {
                    const res = await apiJson('/api/presets', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ preset: newPreset })
                    });
                    if (!res.success || !res.preset?.name) {
                        alert(res.detail || "Failed to save new preset.");
                        return;
                    }
                    state.selectedPreset = res.preset.name;
                    localStorage.setItem('uma_selected_preset', state.selectedPreset);
                    await loadPresets();
                    if (els.presetSelect) els.presetSelect.value = state.selectedPreset;
                    syncSelectedPresetRaces();
                    populatePresetUI();
                    renderRaces();
                } catch (e) { alert("Failed to save new preset."); }
            });

            els.presetDelBtn?.addEventListener('click', async () => {
                if (!state.selectedPreset) return;
                const deletedName = state.selectedPreset;
                if (!confirm(`Are you sure you want to delete preset '${deletedName}'?`)) return;

                try {
                    const res = await apiJson('/api/presets/delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: deletedName })
                    });
                    if (!res.success) {
                        alert(res.detail || "Failed to delete preset.");
                        return;
                    }
                    await loadPresets();
                } catch (e) { alert("Failed to delete preset."); }
            });
        }

        async function loadPresets() {
            try {
                const res = await apiJson('/api/presets');
                if (res.success && res.presets && res.presets.length > 0) {
                    state.presets = res.presets;
                    if (els.presetSelect) {
                        els.presetSelect.innerHTML = state.presets.map(p => `<option value="${escapeAttr(p.name)}">${escapeHtml(p.name)}</option>`).join('');
                    }
                    const saved = localStorage.getItem('uma_selected_preset');
                    if (saved && state.presets.some(p => p.name === saved)) {
                        state.selectedPreset = saved;
                    } else {
                        state.selectedPreset = state.presets[0].name;
                    }
                    localStorage.setItem('uma_selected_preset', state.selectedPreset);
                    if (els.presetSelect) els.presetSelect.value = state.selectedPreset;
                    populatePresetUI();
                } else {
                    state.presets = [];
                    state.selectedPreset = "";
                    localStorage.removeItem('uma_selected_preset');
                    if (els.presetSelect) els.presetSelect.innerHTML = "";
                    populatePresetUI();
                }
            } catch(e) {
                state.presets = [];
                state.selectedPreset = "";
                localStorage.removeItem('uma_selected_preset');
                populatePresetUI();
            }
            syncStartButton();
            await loadRaceData();
        }

        function renderFriends() {
            const friends = (dashData && dashData.friends) || [];
            clearInvalidFriendSelection();
            const visibleFriends = getVisibleFriends();
            if (dashData) dashData.visibleFriends = visibleFriends;

            if (state.pendingFriendSelection) {
                const f = visibleFriends.find(v =>
                    String(v.viewer_id) === state.pendingFriendSelection.viewer_id &&
                    String(v.support_card_id) === state.pendingFriendSelection.support_card_id
                );
                if (f) {
                    selection.friend = f;
                    state.pendingFriendSelection = null;
                }
            }

            if (els.friendCount) els.friendCount.innerText = `(${visibleFriends.length}/${friends.length})`;
            if (!els.friendGrid) { renderTeamPanel(); return; }
            els.friendGrid.innerHTML = visibleFriends.map(friend => {
                const imgId = friend.support_card_id || '10001';
                const lb = friend.limit_break_count ?? '?';
                return `<div class="grid-card friend-card">
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="grid-card-overlay">
                        <span class="grid-card-name">${friend.support_name || 'Unknown'}</span>
                        <span class="grid-card-kicker">${friend.type || '?'} | LB${lb}</span>
                    </div>
                </div>`;
            }).filter(Boolean).join('');
            attachFriendHandlers();
            syncFriendSelection();
            renderTeamPanel();
        }
        function appendSeenFriendIds(ids) {
            if (!dashData) return;
            const seen = new Set(dashData.friendExcludeIds || []);
            (ids || []).forEach(id => {
                if (id) seen.add(id);
            });
            dashData.friendExcludeIds = Array.from(seen);
        }
        async function loadFriends(refresh = false) {
            // Friend browser UI was removed from the LIBRARY panel; the bot resumes careers
            // with the friend already chosen in-game, so there is nothing to load into.
            if (!els.friendGrid || !els.friendStatus) return;
            if (!dashData || state.isFetchingFriends) return;
            // Don't pre-block on the cached career.active flag -- it goes stale after a career finishes.
            // Let the backend probe the real state (it clears the flag and returns friends if the slot
            // is actually free, or "Active Career (Skip)" if a career is genuinely still running).
            state.isFetchingFriends = true;
            els.friendRefreshBtn.disabled = true;
            els.friendStatus.classList.remove('error');
            els.friendStatus.innerText = refresh ? 'Refreshing friends...' : 'Loading friends...';
            if (els.guestRefreshBtn) els.guestRefreshBtn.disabled = true;
            if (els.guestStatus) els.guestStatus.innerText = refresh ? 'Refreshing...' : 'Loading...';
            const excludeIds = refresh ? (dashData.friendExcludeIds || []) : [];
            try {
                const data = await apiJson('/api/career/friends', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ exclude_viewer_ids: excludeIds })
                });
                if (!data.success) throw new Error(data.detail || 'Friend load failed');
                dashData.friends = data.friends || [];
                dashData.guestParents = data.guest_parents || [];
                appendSeenFriendIds(data.exclude_viewer_ids || []);
                renderFriends();
                renderGuestParents();
                if (data.source === 'Active Career (Skip)') {
                    els.friendStatus.innerText = 'Active career, endpoint blocked';
                    return;
                }
                // Friends loaded => no active career; clear the (possibly stale) local flag so the
                // button and other setup controls stop treating a finished career as still active.
                if (dashData.account && dashData.account.career) dashData.account.career.active = false;
                const source = data.source === 'initial' ? 'initial' : 'refresh';
                const visibleCount = ((dashData && dashData.visibleFriends) || []).length;
                els.friendStatus.innerText = `${source} list: ${visibleCount}/${dashData.friends.length} cards`;
            } catch (e) {
                els.friendStatus.innerText = e.message || 'Friend load failed';
                els.friendStatus.classList.add('error');
            } finally {
                state.isFetchingFriends = false;
                // Keep the button clickable so the user can re-probe after a career finishes; a
                // genuinely-active career just returns "endpoint blocked" on click (harmless).
                els.friendRefreshBtn.disabled = false;
                if (els.guestRefreshBtn) els.guestRefreshBtn.disabled = false;
            }
        }
        function attachFriendHandlers() {
            const visibleFriends = (dashData && dashData.visibleFriends) || [];
            document.querySelectorAll('#friend-grid .grid-card').forEach((el, i) => {
                el.classList.add('selectable');
                el.addEventListener('click', () => {
                    const friend = visibleFriends[i];
                    const already = selection.friend && friendKey(selection.friend) === friendKey(friend);
                    document.querySelectorAll('#friend-grid .grid-card').forEach(c => c.classList.remove('selected'));
                    selection.friend = already ? null : friend;
                    if (!already) el.classList.add('selected');
                    renderTeamPanel();
                    syncSelectionToServer();
                });
            });
        }
        function guestKey(g) { return g ? `${g.trained_chara_id}:${g.viewer_id}` : ''; }
        function renderGuestParents() {
            // GUEST (rental) parents get their own LIBRARY tab beside PARENTS: borrow one for the 2nd
            // inheritance slot. Rendered as a click-to-select grid, mirroring the friend grid.
            const guests = (dashData && dashData.guestParents) || [];
            if (els.guestCount) els.guestCount.innerText = guests.length ? `(${guests.length})` : '';
            if (els.guestStatus) els.guestStatus.innerText = guests.length
                ? 'Pick one to borrow — it replaces your 2nd parent'
                : 'Load to populate (uses the same fetch as Friend Supports)';
            if (!els.guestGrid) { renderTeamPanel(); return; }
            els.guestGrid.innerHTML = guests.map(g => {
                const imgId = g.card_id || '100101';
                const sel = selection.guestParent && guestKey(selection.guestParent) === guestKey(g) ? ' selected' : '';
                // Same hover sparks preview as owned parents (renderParentSparks reads g.tree). Guard so a
                // guest with no lineage factors just stays a plain card (no empty tooltip, no has-sparks).
                const sparks = g.tree ? renderParentSparks(g, imgId) : '';
                const tooltip = sparks ? `<div class="sparks-tooltip" style="--spark-bg: url('/api/images/${imgId}.png')">
                        <div class="sparks-tooltip-title"></div>
                        <div class="sparks-tooltip-scroll"><div class="sparks-lineage-grid">${sparks}</div></div>
                    </div>` : '';
                return `<div class="grid-card guest-card selectable${sel}">
                    <div class="rank-badge">${rankLabel(g.rank)}</div>
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    ${tooltip}
                    <div class="grid-card-overlay">
                        <span class="grid-card-kicker">GUEST | ${rankLabel(g.rank)}</span>
                        <span class="grid-card-name">${escapeHtml(g.name || ('#' + g.trained_chara_id))}</span>
                    </div>
                </div>`;
            }).join('');
            els.guestGrid.querySelectorAll('.grid-card').forEach((el, i) => {
                el.addEventListener('click', () => selectGuestParent(guests[i]));
            });
            bindSparkTooltips('#guest-grid .grid-card');
            applyGuestFilter();
            renderTeamPanel();
        }
        function selectGuestParent(g) {
            const already = selection.guestParent && guestKey(selection.guestParent) === guestKey(g);
            selection.guestParent = already ? null : g;
            // A guest occupies the 2nd parent slot: drop any 2nd owned parent + deselect its grid card.
            if (selection.guestParent && selection.veterans.length > 1) {
                const dropped = selection.veterans.splice(1);
                const cards = document.querySelectorAll('#parent-grid .grid-card');
                dropped.forEach(v => { const c = cards[v._gridIdx]; if (c) c.classList.remove('selected'); });
            }
            updateVetSelectability();
            renderGuestParents();
            syncSelectionToServer();
        }
        function formatRunEstimate(n) {
            // CAREER (MIN) is the length of each career (+~1 min per career to start and finish it);
            // a career that plays slower than that with no waiting at all just takes longer.
            const lo = Number(els.turnDelayMin && els.turnDelayMin.value) || 0;
            const hi = Number(els.turnDelayMax && els.turnDelayMax.value) || 0;
            const fmt = (m) => m < 90 ? `${Math.round(m)} min` : `${(m / 60).toFixed(1)} hr`;
            return `${fmt(n * (lo + 1))} – ${fmt(n * (hi + 1))}`;
        }
        function closeRunConfirm() {
            if (els.runConfirmModal) els.runConfirmModal.style.display = 'none';
        }
        function openRunConfirm() {
            const n = state.runCount;
            const activeCareer = state.account && state.account.career && state.account.career.active;
            const lead = activeCareer ? 'Resume the active career, then run ' : 'The bot will run ';
            let copy, infinite = false;
            if (n === 0) {
                infinite = true;
                copy = `<strong style="color:#ffcf48">⚠️ INFINITE MODE</strong><br>${lead}careers <strong>continuously</strong> until you click <strong>STOP</strong>. It won't stop on its own.`;
            } else if (n === 1) {
                copy = `${lead}<strong>1 career</strong> (single run), then stop.<br><span style="opacity:.7">Est. ~${formatRunEstimate(1)}</span>`;
            } else {
                copy = `${lead}<strong>${n} careers</strong> back-to-back, then stop automatically.<br><span style="opacity:.7">Est. total ~${formatRunEstimate(n)}</span>`;
            }
            els.runConfirmCopy.innerHTML = copy;
            els.runConfirmOk.textContent = infinite ? 'YES, RUN ∞' : `YES, RUN ${n}×`;
            els.runConfirmOk.classList.toggle('btn-danger', infinite);
            els.runConfirmOk.classList.toggle('btn-primary', !infinite);
            els.runConfirmModal.style.display = 'flex';
        }
        function requestStartCareer() {
            const reason = getStartMissingReason();
            if (reason || state.isStartingCareer) {
                syncStartButton();
                return;
            }
            openRunConfirm();
        }
        async function startCareer() {
            const reason = getStartMissingReason();
            if (reason || state.isStartingCareer) {
                syncStartButton();
                return;
            }
            state.isStartingCareer = true;
            syncStartButton();
            let finalMessage = '';
            let finalIsError = false;
            const activeCareer = state.account && state.account.career && state.account.career.active;
            const body = activeCareer ? {
                preset_name: state.selectedPreset,
                max_steps: 2500,
                burn_clocks: state.burnClocks,
                run_count: state.runCount,
                finish_career: state.finishCareer,
                scenario_id: currentScenarioId()
            } : {
                card_id: Number(selection.trainee.id),
                support_card_ids: selection.deck.cards.map(card => Number(card.id)),
                friend_viewer_id: Number(selection.friend.viewer_id),
                friend_card_id: Number(selection.friend.support_card_id),
                parent_id_1: Number(selection.veterans[0].instance_id),
                parent_id_2: selection.guestParent ? 0 : Number(selection.veterans[1].instance_id),
                rental_viewer_id: selection.guestParent ? Number(selection.guestParent.viewer_id) : 0,
                rental_trained_chara_id: selection.guestParent ? Number(selection.guestParent.trained_chara_id) : 0,
                deck_id: Number(selection.deck.id),
                scenario_id: currentScenarioId(),
                use_tp: 30,
                difficulty_id: 0,
                difficulty: 0,
                is_boost: 0,
                boost_story_event_id: 0,
                preset_name: state.selectedPreset,
                max_steps: 2500,
                burn_clocks: state.burnClocks,
                run_count: state.runCount,
                finish_career: state.finishCareer
            };
            try {
                const data = await apiJson('/api/career/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!data.success) throw new Error(data.detail || 'Start failed');
                state.displayedClocksUsed = Number(data.runner && data.runner.clocks_used || 0);
                renderAccountStrip(data.account);
                if (data.account && data.account.career && data.account.career.active) {
                    autoLoadCareerSelection();
                    renderFriends();
                }
                startRunnerPolling();
                finalMessage = 'Career runner started';
            } catch (e) {
                finalMessage = e.message || 'Start failed';
                finalIsError = true;
                if (state.devEnabled) {
                    setDevEnabled(false, { persist: true });
                }
            } finally {
                state.isStartingCareer = false;
                syncStartButton();
                if (finalMessage) {
                    els.startStatus.innerText = finalMessage;
                    els.startStatus.classList.toggle('error', finalIsError);
                }
            }
        }
        function applyRunnerSettings(runner) {
            if (runner.running && runner.burn_clocks !== undefined && state.burnClocks !== runner.burn_clocks) {
                setBurnClocks(runner.burn_clocks, { persist: true });
            }
        }
        function applyRunnerClockUsage(runner) {
            const clocksUsed = Number(runner.clocks_used || 0);
            if (state.account && clocksUsed > state.displayedClocksUsed) {
                const delta = clocksUsed - state.displayedClocksUsed;
                state.account = {
                    ...state.account,
                    clocks: Math.max(0, Number(state.account.clocks || 0) - delta)
                };
                state.displayedClocksUsed = clocksUsed;
                renderAccountStrip(state.account);
            } else if (clocksUsed < state.displayedClocksUsed) {
                state.displayedClocksUsed = clocksUsed;
            }
        }
        function updatePauseButton(runner) {
            const active = !!(runner && (runner.running || runner.loop_active));
            // STOP shares PAUSE's visibility rule: both only mean anything while a run is live.
            // PAUSE holds the current career; STOP also clears the multi-run loop flag, which is
            // the ONLY way to end an infinite (run count 0) loop short of killing the process.
            if (els.navStopBtn) els.navStopBtn.style.display = active ? '' : 'none';
            if (!els.navPauseBtn) return;
            els.navPauseBtn.style.display = active ? '' : 'none';
            if (active) {
                const paused = !!(runner && runner.paused);
                els.navPauseBtn.textContent = paused ? 'RESUME' : 'PAUSE';
                els.navPauseBtn.classList.toggle('paused', paused);
            }
        }
        async function stopRunner() {
            const infinite = !!(state.runner && state.runner.loop_active);
            if (!confirm(infinite
                ? 'Stop the bot and end the run loop? The career in progress is left as-is — you can resume it with RUN.'
                : 'Stop the bot? The career in progress is left as-is — you can resume it with RUN.')) return;
            els.navStopBtn.disabled = true;
            try {
                const data = await apiJson('/api/career/runner/stop', { method: 'POST' });
                if (data && data.runner) applyRunnerSnapshot(data.runner);
            } catch (e) {
                els.startStatus.classList.add('error');
                els.startStatus.innerText = `Stop failed: ${e.message || e}`;
            } finally {
                els.navStopBtn.disabled = false;
            }
        }
        async function togglePause() {
            const paused = !!(state.runner && state.runner.paused);
            const endpoint = paused ? '/api/career/runner/resume' : '/api/career/runner/pause';
            els.navPauseBtn.disabled = true;
            try {
                const data = await apiJson(endpoint, { method: 'POST' });
                if (data && data.runner) applyRunnerSnapshot(data.runner);
            } catch (e) {
            } finally {
                els.navPauseBtn.disabled = false;
            }
        }
        function applyRunnerSnapshot(runner) {
            state.runner = runner;
            applyRunnerSettings(runner);
            applyRunnerClockUsage(runner);
            updatePauseButton(runner);
            updateDeleteBarRunnerState(runner);
        }
        async function refreshRunnerStatus() {
            try {
                const data = await apiJson('/api/career/runner');
                if (!data.success || !data.runner) return;
                const runner = data.runner;
                applyRunnerSnapshot(runner);

                const rows = (runner.action_history && runner.action_history.length) ? runner.action_history : deriveActionHistory(runner.log || []);
                if (rows.length) renderActionHistory(rows);
                if (runner.running) {
                    els.startStatus.classList.toggle('error', false);
                    els.startStatus.classList.remove('backoff');
                    if (!rows.length) els.startStatus.innerText = `Turn ${runner.turn || '?'} / ${runner.last_action || 'running'} / ${runner.steps || 0}`;
                    return;
                }
                if (state.runnerTimer && !runner.loop_active) {
                    bgClearTimer(state.runnerTimer);
                    state.runnerTimer = 0;
                }
                if (runner.circuit_tripped) {
                    // Auto-backoff: the bot stopped itself after repeated server errors.
                    // Show it distinctly (amber, not red) so it doesn't read as a crash,
                    // and always show the message even when an action table is present.
                    els.startStatus.classList.toggle('error', false);
                    els.startStatus.classList.add('backoff');
                    els.startStatus.innerText = '🛑 Auto-backoff: too many server errors in a short time. The bot stopped ITSELF to protect your account — this is intentional, not a crash. Wait a while (ideally hours) before running again.';
                } else if (runner.last_error) {
                    els.startStatus.classList.remove('backoff');
                    els.startStatus.classList.toggle('error', true);
                    if (!rows.length) els.startStatus.innerText = runner.last_error;
                } else if (runner.finished && !runner.last_error) {
                    els.startStatus.classList.remove('backoff');
                    state.consecutiveRunnerFails = 0;
                    els.startStatus.classList.toggle('error', false);
                    if (!rows.length) els.startStatus.innerText = runner.loop_active ? 'Career finished! Restarting...' : 'Career finished!';
                    if (state.account && state.account.career) state.account.career.active = false;
                    renderAccountStrip(state.account);
                } else if (runner.steps) {
                    els.startStatus.classList.remove('backoff');
                    els.startStatus.classList.toggle('error', false);
                    if (!rows.length) els.startStatus.innerText = `Runner stopped after ${runner.steps} steps`;
                }
            } catch (e) {}
        }
        function ordinalSuffix(n) {
            const v = n % 100;
            if (v >= 11 && v <= 13) return n + 'th';
            return n + (['th', 'st', 'nd', 'rd'][n % 10] || 'th');
        }
        function raceResultBadge(row) {
            // Win/place badge on a race row (runner attaches row.result = {rank, won} after the race).
            if (row.action !== 'race' || !row.result) return '';
            const r = row.result;
            if (r.won) return ` <span class="race-result race-result-win">🏆 1st</span>`;
            const rank = Number(r.rank) || 0;
            return ` <span class="race-result race-result-loss">${rank ? ordinalSuffix(rank) : '—'}</span>`;
        }
        function renderActionHistory(rows) {
            if (!els.startStatus) return;
            state.lastRunnerRows = rows;
            renderCareerSummary(rows);
            if (!rows.length) {
                els.startStatus.innerText = '';
                return;
            }
            const formatStatsDetail = row => {
                const stats = row.stats || {};
                if (!Object.keys(stats).length) return row.detail || '';
                return [
                    `HP ${stats.hp ?? 0}/${stats.max_hp ?? 100}`,
                    `MOOD ${stats.motivation ?? 0}`,
                    `SPD ${stats.speed ?? 0} STA ${stats.stamina ?? 0} PWR ${stats.power ?? 0} GUT ${stats.guts ?? 0} WIT ${stats.wit ?? 0} SP ${stats.skill_point ?? 0}`
                ].join(' | ');
            };
            const body = rows.map(row => `
                    <tr>
                        <td>${escapeHtml(row.turn)}</td>
                        <td><span class="action-pill action-pill-${escapeAttr(normalizeHistoryAction(row).action)}">${escapeHtml(normalizeHistoryAction(row).action)}</span></td>
                        <td>${escapeHtml(row.facility)}${raceResultBadge(row)}</td>
                        <td class="action-history-detail">${escapeHtml(formatStatsDetail(row))}</td>
                    </tr>
                `).join('');
            els.startStatus.innerHTML = `
                <div class="action-history-wrap">
                    <table class="action-history-table">
                        <thead>
                            <tr>
                                <th>TURN</th>
                                <th>ACTION</th>
                                <th>FACILITY</th>
                                <th>DETAIL</th>
                            </tr>
                        </thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
            `;
            const wrap = els.startStatus.querySelector('.action-history-wrap');
            if (wrap) wrap.scrollTop = wrap.scrollHeight;
        }
        // Compact "current career" card shown above the RESUME button: who you're training
        // + how far along + live stats. Only shows when a career is active.
        function renderCareerSummary(rows) {
            const el = document.getElementById('career-summary');
            if (!el) return;
            const career = state.account && state.account.career;
            const active = career && career.active;
            const trainee = selection.trainee;
            if (!active || !trainee) {
                el.style.display = 'none';
                el.innerHTML = '';
                return;
            }
            const list = (rows && rows.length) ? rows : (state.lastRunnerRows || []);
            const last = list.length ? list[list.length - 1] : null;
            const s = (last && last.stats) || {};
            const turn = (last && last.turn != null) ? last.turn : null;
            const TOTAL = 78;
            let phase = 'Career';
            if (turn != null) {
                if (turn <= 24) phase = 'Junior Year';
                else if (turn <= 48) phase = 'Classic Year';
                else if (turn <= 72) phase = 'Senior Year';
                else phase = 'Finale';
            }
            const pct = turn != null ? Math.max(0, Math.min(100, Math.round(turn / TOTAL * 100))) : 0;
            const stat = (label, v) => `<span class="cs-stat"><b>${label}</b> ${v == null ? '–' : v}</span>`;
            el.style.display = '';
            el.innerHTML = `
                <div class="career-summary-portrait-box">
                    <img class="career-summary-portrait" src="/api/images/${trainee.id || '100101'}.png" onerror="hideBrokenImage(this)">
                </div>
                <div class="career-summary-info">
                    <div class="career-summary-name">${trainee.name || 'Unknown'}</div>
                    <div class="career-progress">
                        <div class="career-progress-top">
                            <span>${turn != null ? 'Turn ' + turn + ' / ' + TOTAL : 'Active career'}</span>
                            <span class="career-progress-phase">${phase}</span>
                        </div>
                        <div class="career-progress-track"><div class="career-progress-fill" style="width:${pct}%"></div></div>
                    </div>
                    <div class="career-summary-stats">
                        ${stat('HP', s.hp != null ? `${s.hp}/${s.max_hp == null ? 100 : s.max_hp}` : null)}
                        ${stat('MOOD', s.motivation)}
                        ${stat('SPD', s.speed)}
                        ${stat('STA', s.stamina)}
                        ${stat('PWR', s.power)}
                        ${stat('GUT', s.guts)}
                        ${stat('WIT', s.wit)}
                        ${stat('SP', s.skill_point)}
                    </div>
                </div>
            `;
        }
        function deriveActionHistory(log) {
            return log.filter(item => ['command', 'race', 'race_progress', 'finish', 'api_delay', 'turn_delay', 'complex_delay'].includes(item.action)).map(item => {
                const detail = String(item.detail || '');
                let action = item.action;
                let facility = '';
                if (action === 'command') {
                    if (detail.startsWith('training ')) {
                        action = 'train';
                        facility = detail.replace('training ', '');
                    } else if (detail.startsWith('rest ')) {
                        action = 'rest';
                        facility = detail.replace('rest ', '');
                        if (['301', '302', '303', '304', '305', '390'].includes(facility)) action = 'recreation';
                    } else if (detail.startsWith('challenge ')) {
                        action = 'rest';
                        facility = detail.replace('challenge ', '');
                    } else if (detail.startsWith('recreation ')) {
                        action = 'recreation';
                        facility = detail.replace('recreation ', '');
                    } else if (detail.startsWith('command 8:')) {
                        action = 'medic';
                    }
                } else if (action === 'race_progress') {
                    action = 'race';
                }
                return { turn: item.turn, action, facility, detail };
            });
        }
        function normalizeHistoryAction(row) {
            const facility = String(row.facility ?? '');
            if (row.action === 'rest' && ['301', '302', '303', '304', '305', '390'].includes(facility)) {
                return { ...row, action: 'recreation' };
            }
            return row;
        }
        const timerWorkerBlob = new Blob([`
            let activeTimers = {};
            self.onmessage = function(e) {
                const { action, id, ms } = e.data;
                if (action === 'setInterval') {
                    activeTimers[id] = setInterval(() => postMessage({ id }), ms);
                } else if (action === 'setTimeout') {
                    activeTimers[id] = setTimeout(() => {
                        postMessage({ id });
                        delete activeTimers[id];
                    }, ms);
                } else if (action === 'clear') {
                    clearInterval(activeTimers[id]);
                    clearTimeout(activeTimers[id]);
                    delete activeTimers[id];
                }
            };
        `], {type: 'application/javascript'});
        const timerWorker = new Worker(URL.createObjectURL(timerWorkerBlob));
        let nextTimerId = 1;
        const timerCallbacks = {};
        timerWorker.onmessage = function(e) {
            if (timerCallbacks[e.data.id]) timerCallbacks[e.data.id]();
        };
        function bgSetInterval(cb, ms) {
            const id = nextTimerId++;
            timerCallbacks[id] = cb;
            timerWorker.postMessage({ action: 'setInterval', id, ms });
            return id;
        }
        function bgSetTimeout(cb, ms) {
            const id = nextTimerId++;
            timerCallbacks[id] = () => { delete timerCallbacks[id]; cb(); };
            timerWorker.postMessage({ action: 'setTimeout', id, ms });
            return id;
        }
        function bgClearTimer(id) {
            delete timerCallbacks[id];
            timerWorker.postMessage({ action: 'clear', id });
        }
        function startRunnerPolling() {
            if (state.runnerTimer) bgClearTimer(state.runnerTimer);
            refreshRunnerStatus();
            state.runnerTimer = bgSetInterval(refreshRunnerStatus, 1500);
        }
        if (els.friendRefreshBtn) els.friendRefreshBtn.addEventListener('click', event => {
            event.stopPropagation();
            loadFriends(true);
        });
        if (els.friendSearch) els.friendSearch.addEventListener('input', () => {
            friendFilter.search = els.friendSearch.value;
            renderFriends();
        });
        if (els.friendTypeChips) els.friendTypeChips.addEventListener('click', event => {
            const chip = event.target.closest('.friend-type-chip');
            if (!chip) return;
            friendFilter.type = chip.dataset.type || 'all';
            els.friendTypeChips.querySelectorAll('.friend-type-chip').forEach(c =>
                c.classList.toggle('is-active', c === chip));
            renderFriends();
        });
        // Parent + guest library filters (any-spark search + stat chips + sort dropdown)
        [[els.parentSearch, els.parentStatChips, els.parentSort, parentFilter, applyParentFilter],
         [els.guestSearch, els.guestStatChips, els.guestSort, guestFilter, applyGuestFilter]].forEach(([searchEl, chipsEl, sortEl, filter, apply]) => {
            if (searchEl) searchEl.addEventListener('input', () => { filter.search = searchEl.value; apply(); });
            if (chipsEl) chipsEl.addEventListener('click', event => {
                const chip = event.target.closest('.lib-chip');
                if (!chip) return;
                filter.stat = chip.dataset.stat || 'all';
                chipsEl.querySelectorAll('.lib-chip').forEach(c => c.classList.toggle('is-active', c === chip));
                apply();
            });
            if (sortEl) sortEl.addEventListener('change', () => { filter.sort = sortEl.value; apply(); });
        });
        if (els.guestRefreshBtn) els.guestRefreshBtn.addEventListener('click', event => {
            event.stopPropagation();
            loadFriends(true);   // guests + friends come from the same endpoint
        });
        if (els.historyBtn) els.historyBtn.addEventListener('click', openCareerHistory);
        if (els.historyClose) els.historyClose.addEventListener('click', () => { els.historyModal.style.display = 'none'; });
        if (els.historyModal) els.historyModal.addEventListener('click', event => {
            if (event.target === els.historyModal) els.historyModal.style.display = 'none';   // click backdrop to close
        });
        els.startCareerBtn.addEventListener('click', requestStartCareer);
        if (els.navRunBtn) els.navRunBtn.addEventListener('click', requestStartCareer);
        if (els.navPauseBtn) els.navPauseBtn.addEventListener('click', togglePause);
        if (els.navStopBtn) els.navStopBtn.addEventListener('click', stopRunner);
        if (els.runConfirmOk) els.runConfirmOk.addEventListener('click', () => { closeRunConfirm(); startCareer(); });
        if (els.runConfirmCancel) els.runConfirmCancel.addEventListener('click', closeRunConfirm);
        if (els.runConfirmModal) els.runConfirmModal.addEventListener('click', event => {
            if (event.target === els.runConfirmModal) closeRunConfirm();
        });

        function selectDeck(index, element) {
            const alreadySelected = element.classList.contains('selected');
            document.querySelectorAll('.deck-container.selected').forEach(card => card.classList.remove('selected'));
            selection.deck = null;
            if (!alreadySelected) {
                element.classList.add('selected');
                selection.deck = dashData.validDecks[index];
            }
            renderFriends();
            renderTeamPanel();
            syncSelectionToServer();
        }
        function selectTrainee(index, element) {
            const alreadySelected = element.classList.contains('selected');
            document.querySelectorAll('#uma-grid .grid-card.selected').forEach(card => card.classList.remove('selected'));
            selection.trainee = null;
            if (!alreadySelected) {
                element.classList.add('selected');
                selection.trainee = dashData.umas[index];
            }
            renderFriends();
            updateVetSelectability();
            renderTeamPanel();
            syncSelectionToServer();
            applyTraineeGoals();   // live: fill the race schedule with THIS trainee's career goals
        }
        function selectParent(index, element) {
            if (parentDelete.mode) { toggleDeleteSelect(element); return; }
            if (element.classList.contains('vet-full')) return;
            if (element.classList.contains('selected')) {
                element.classList.remove('selected');
                selection.veterans = selection.veterans.filter(parent => parent._gridIdx !== index);
            } else if (selection.veterans.length < (selection.guestParent ? 1 : 2)) {
                element.classList.add('selected');
                selection.veterans.push({ ...dashData.parents[index], _gridIdx: index });
            }
            updateVetSelectability();
            renderTeamPanel();
            syncSelectionToServer();
        }
        function bindParentCardHandlers() {
            document.querySelectorAll('#parent-grid .grid-card').forEach((element, index) => {
                element.classList.add('selectable');
                element.addEventListener('click', () => selectParent(index, element));
            });
        }
        function attachSelectionHandlers() {
            document.querySelectorAll('.deck-container').forEach((element, index) => {
                element.addEventListener('click', () => selectDeck(index, element));
            });
            document.querySelectorAll('#uma-grid .grid-card').forEach((element, index) => {
                element.classList.add('selectable');
                element.addEventListener('click', () => selectTrainee(index, element));
            });
            bindParentCardHandlers();
        }

        // ---- Manual trainee deletion (PARENTS roster) --------------------------------------------
        function getProtectedParentIds() {
            // Trainees that must never be offered for deletion: the active/queued career's two
            // inheritance parents plus any veteran the user picked in SETUP -- deleting one breaks
            // the next career start (the backend enforces this too and reports it as skipped).
            const s = new Set();
            const career = (dashData && dashData.account && dashData.account.career) || {};
            [career.parent_id_1, career.parent_id_2].forEach(v => { const n = Number(v || 0); if (n) s.add(n); });
            (selection.veterans || []).forEach(v => { const n = Number(v && v.instance_id || 0); if (n) s.add(n); });
            return s;
        }
        function updateDeleteBar() {
            const n = parentDelete.ids.size;
            if (els.parentDeleteBtn) {
                els.parentDeleteBtn.textContent = `Delete selected (${n})`;
                els.parentDeleteBtn.disabled = parentDelete.busy || n === 0;
            }
        }
        function toggleDeleteSelect(element) {
            if (!element) return;
            const id = Number(element.getAttribute('data-instance-id') || 0);
            if (!id) return;
            if (element.classList.contains('trainee-locked')) {
                if (els.parentDeleteStatus) els.parentDeleteStatus.textContent = `#${id} is locked in-game — unlock it first to delete.`;
                return;
            }
            if (getProtectedParentIds().has(id)) {
                if (els.parentDeleteStatus) els.parentDeleteStatus.textContent = `#${id} is a configured inheritance parent — can't delete.`;
                return;
            }
            if (parentDelete.ids.has(id)) {
                parentDelete.ids.delete(id);
                element.classList.remove('selected-for-delete');
            } else {
                parentDelete.ids.add(id);
                element.classList.add('selected-for-delete');
            }
            if (els.parentDeleteStatus) els.parentDeleteStatus.textContent = '';
            updateDeleteBar();
        }
        function setDeleteMode(on) {
            parentDelete.mode = !!on;
            if (!on) {
                parentDelete.ids.clear();
                document.querySelectorAll('#parent-grid .grid-card.selected-for-delete')
                    .forEach(el => el.classList.remove('selected-for-delete'));
            }
            if (els.parentGrid) els.parentGrid.classList.toggle('delete-mode', parentDelete.mode);
            if (els.parentDeleteToggle) {
                els.parentDeleteToggle.setAttribute('aria-pressed', String(parentDelete.mode));
                els.parentDeleteToggle.classList.toggle('is-active', parentDelete.mode);
                els.parentDeleteToggle.textContent = parentDelete.mode ? '✕ Exit delete mode' : '🗑 Delete mode';
            }
            if (els.parentDeleteBtn) els.parentDeleteBtn.hidden = !parentDelete.mode;
            if (els.parentDeleteClear) els.parentDeleteClear.hidden = !parentDelete.mode;
            if (els.parentDeleteHint) els.parentDeleteHint.hidden = !parentDelete.mode;
            if (els.parentDeleteStatus) els.parentDeleteStatus.textContent = '';
            updateDeleteBar();
        }
        function updateDeleteBarRunnerState(runner) {
            // Deletion touches the roster mid-flight, so it's blocked while the runner/loop is live
            // (the backend refuses too). Force delete mode off and disable the switch while active.
            const active = !!(runner && (runner.running || runner.loop_active));
            if (active && parentDelete.mode) setDeleteMode(false);
            if (els.parentDeleteToggle) {
                els.parentDeleteToggle.disabled = active;
                els.parentDeleteToggle.title = active
                    ? 'Stop the career runner before deleting trainees'
                    : 'Turn on to pick trainees to permanently release';
            }
        }
        async function runTraineeDelete() {
            const ids = [...parentDelete.ids];
            if (!ids.length || parentDelete.busy) return;
            if (!confirm(`Permanently release ${ids.length} trainee(s)? This cannot be undone.`)) return;
            parentDelete.busy = true;
            updateDeleteBar();
            if (els.parentDeleteStatus) els.parentDeleteStatus.textContent = 'Deleting…';
            try {
                const res = await apiJson('/api/trainees/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ trained_chara_ids: ids })
                });
                if (!res || !res.success) {
                    if (els.parentDeleteStatus) els.parentDeleteStatus.textContent = (res && res.detail) || 'Delete failed';
                    return;
                }
                if (dashData) dashData.parents = res.parents || [];
                parentDelete.ids.clear();
                renderParents((dashData && dashData.parents) || []);
                bindParentCardHandlers();
                bindSparkTooltips('#parent-grid .grid-card');
                if (els.parentCount) els.parentCount.innerText = `(${((dashData && dashData.parents) || []).length})`;
                let msg = res.detail || `Released ${(res.removed || []).length} trainee(s).`;
                if (res.skipped && res.skipped.length) {
                    msg += ' Skipped: ' + res.skipped.map(s => `#${s.id} (${s.reason})`).join(', ');
                }
                if (els.parentDeleteStatus) els.parentDeleteStatus.textContent = msg;
            } catch (e) {
                if (els.parentDeleteStatus) els.parentDeleteStatus.textContent = 'Delete failed: ' + (e.message || e);
            } finally {
                parentDelete.busy = false;
                updateDeleteBar();
            }
        }
        if (els.parentDeleteToggle) els.parentDeleteToggle.addEventListener('click', () => {
            if (els.parentDeleteToggle.disabled) return;
            setDeleteMode(!parentDelete.mode);
        });
        if (els.parentDeleteBtn) els.parentDeleteBtn.addEventListener('click', runTraineeDelete);
        if (els.parentDeleteClear) els.parentDeleteClear.addEventListener('click', () => {
            parentDelete.ids.clear();
            document.querySelectorAll('#parent-grid .grid-card.selected-for-delete')
                .forEach(el => el.classList.remove('selected-for-delete'));
            if (els.parentDeleteStatus) els.parentDeleteStatus.textContent = '';
            updateDeleteBar();
        });
        function isValidDeck(deck) {
            return deck.cards.every(card => {
                const id = card.id || '';
                const name = card.name || '';
                return !id.includes('{') && !id.includes('-') && !name.includes('Unknown');
            });
        }
        function renderCounts(data) {
            // LIBRARY browser sections were removed; counts only render where elements remain.
            if (els.umaCount) els.umaCount.innerText = `(${data.umas.length})`;
            if (els.cardCount) els.cardCount.innerText = `(${data.supports.length})`;
            if (els.parentCount) els.parentCount.innerText = `(${data.parents.length})`;
        }
        function renderDecks(decks) {
            if (!els.deckList) return;
            els.deckList.innerHTML = decks.map(deck => {
                const cards = deck.cards.map(card => {
                    const imgId = card.id || '10001';
                    return `<div class="grid-card deck-card">
                        <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                        <div class="grid-card-overlay">
                            <span class="grid-card-kicker">${card.type || '?'} | ${card.rarity || '?'}</span>
                            <span class="grid-card-name">${card.name || 'Unknown'}</span>
                        </div>
                    </div>`;
                }).join('');
                return `<div class="deck-container">
                    <div class="deck-header">
                        <span>${deck.name.toUpperCase()}</span>
                        <span style="font-size:0.85rem; opacity:0.8">SLOT ${deck.id}</span>
                    </div>
                    <div class="deck-cards">${cards}</div>
                </div>`;
            }).join('');
        }
        function renderFactors(factors) {
            const star = String.fromCharCode(9733);
            return factors.map(factor => `
                <div class="factor-badge f-${factor.category}">
                    ${factor.name} <span class="stars">${star.repeat(factor.stars)}</span>
                </div>
            `).join('');
        }
        function renderWins(wins) {
            if (!wins || !wins.total) return '<span class="spark-win-chip">Wins --</span>';
            return `
                <span class="spark-win-chip">G1 ${wins.g1 || 0}</span>
                <span class="spark-win-chip">G2 ${wins.g2 || 0}</span>
                <span class="spark-win-chip">G3 ${wins.g3 || 0}</span>
            `;
        }
        function renderParentSparks(parent, fallbackImgId) {
            const tree = parent.tree || {};
            return ['self', 'p1', 'p2'].map(key => {
                const node = tree[key];
                if (!node || !node.factors || node.factors.length === 0) return '';
                const nodeImg = node.card_id || fallbackImgId;
                const nodeClass = key === 'self' ? 'spark-node spark-node-self' : 'spark-node';
                return `<div class="${nodeClass}" style="--node-bg: url('/api/images/${nodeImg}.png')">
                    <div class="spark-node-header">
                        <img class="spark-node-portrait" src="/api/images/${nodeImg}.png" onerror="hideBrokenImage(this)">
                        <div class="spark-node-meta">
                            <div class="spark-node-title">${node.name || `Card ${node.card_id || '?'}`}</div>
                            <div class="spark-win-row">${renderWins(node.wins)}</div>
                        </div>
                    </div>
                    <div class="spark-factor-list">
                        ${renderFactors(node.factors)}
                    </div>
                </div>`;
            }).join('');
        }
        // Parent / guest-parent LIBRARY filter: search by uma name OR any spark name across the
        // lineage (self/p1/p2), plus a factor-category chip (stat/aptitude/skill/unique). Cards are
        // HIDDEN, not re-rendered, so the grid-index <-> dashData.parents coupling the selection
        // relies on (selectVeteran, syncSelection) stays intact.
        function parentMatchesFilter(item, filter) {
            if (!item) return false;
            const tree = item.tree || {};
            let hay = String(item.name || '').toLowerCase();
            const wantStat = filter.stat && filter.stat !== 'all' ? filter.stat.toLowerCase() : null;
            let hasStat = false;
            ['self', 'p1', 'p2'].forEach(k => {
                const node = tree[k];
                if (!node) return;
                if (node.name) hay += ' ' + String(node.name).toLowerCase();
                (node.factors || []).forEach(f => {
                    const nm = String(f.name || '').toLowerCase();
                    hay += ' ' + nm;
                    if (wantStat && String(f.category || '').toLowerCase() === 'stat' && nm === wantStat) hasStat = true;
                });
            });
            if (wantStat && !hasStat) return false;                  // stat chip: must carry THAT stat spark
            const q = (filter.search || '').trim().toLowerCase();
            if (q && !hay.includes(q)) return false;                 // search: any spark name OR uma name
            return true;
        }
        // Total spark STARS per category across the lineage -- drives the "Most aptitude/skills/unique" sort.
        function parentSparkStats(item) {
            const tree = (item && item.tree) || {};
            const s = { aptitude: 0, skill: 0, unique: 0, stat: 0 };
            ['self', 'p1', 'p2'].forEach(k => {
                ((tree[k] && tree[k].factors) || []).forEach(f => {
                    const c = String(f.category || '').toLowerCase();
                    if (c in s) s[c] += Number(f.stars) || 0;
                });
            });
            return s;
        }
        function applyLibFilter(grid, items, filter) {
            if (!grid) return 0;
            const cards = [...grid.querySelectorAll('.grid-card')];
            let shown = 0;
            cards.forEach((el, i) => {
                const ok = items[i] ? parentMatchesFilter(items[i], filter) : true;
                el.classList.toggle('filtered-out', !ok);
                if (ok) shown++;
            });
            // Sort via CSS `order` so DOM order (and the selection's grid-index coupling) stays intact.
            if (filter.sort && filter.sort !== 'default') {
                let ranked;
                if (filter.sort === 'newest' || filter.sort === 'oldest') {
                    // trained_chara_id increases with creation, so it doubles as an age key.
                    ranked = items.map((it, i) => ({ i, k: Number(it.instance_id || it.trained_chara_id || 0) }))
                        .sort((a, b) => filter.sort === 'newest' ? (b.k - a.k || a.i - b.i) : (a.k - b.k || a.i - b.i));
                } else {
                    ranked = items.map((it, i) => ({ i, k: parentSparkStats(it)[filter.sort] || 0 }))
                        .sort((a, b) => b.k - a.k || a.i - b.i);
                }
                ranked.forEach((r, pos) => { if (cards[r.i]) cards[r.i].style.order = String(pos); });
            } else {
                cards.forEach(el => { el.style.order = ''; });
            }
            return shown;
        }
        function applyParentFilter() {
            const parents = (dashData && dashData.parents) || [];
            const shown = applyLibFilter(els.parentGrid, parents, parentFilter);
            if (els.parentCount) els.parentCount.innerText = `(${shown}/${parents.length})`;
        }
        function applyGuestFilter() {
            const guests = (dashData && dashData.guestParents) || [];
            const shown = applyLibFilter(els.guestGrid, guests, guestFilter);
            if (els.guestCount && guests.length) els.guestCount.innerText = `(${shown}/${guests.length})`;
        }
        function renderParents(parents) {
            if (!els.parentGrid) return;
            els.parentGrid.innerHTML = parents.map(parent => {
                const imgId = parent.card_id || '100101';
                const locked = Number(parent.is_locked) === 1;
                const created = parent.create_time ? String(parent.create_time).split(' ')[0] : '';
                return `<div class="grid-card${locked ? ' trainee-locked' : ''}" data-instance-id="${parent.instance_id || ''}">
                    <div class="rank-badge">${rankLabel(parent.rank)}</div>
                    ${locked ? '<div class="lock-badge" title="Locked in-game — cannot be deleted">🔒</div>' : ''}
                    <div class="delete-check" aria-hidden="true"></div>
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="sparks-tooltip" style="--spark-bg: url('/api/images/${imgId}.png')">
                        <div class="sparks-tooltip-title"></div>
                        <div class="sparks-tooltip-scroll">
                            <div class="sparks-lineage-grid">
                                ${renderParentSparks(parent, imgId)}
                            </div>
                        </div>
                    </div>
                    <div class="grid-card-overlay">
                        <span class="grid-card-kicker">ID: ${parent.instance_id || '?'}${created ? ' · ' + created : ''}</span>
                        <span class="grid-card-name">${parent.name || 'Unknown'}</span>
                    </div>
                </div>`;
            }).join('');
            applyParentFilter();
        }
        function renderTrainees(umas) {
            if (!els.umaGrid) return;
            els.umaGrid.innerHTML = umas.map(uma => {
                const imgId = uma.id || '100101';
                return `<div class="grid-card">
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="grid-card-overlay"><span class="grid-card-name">${uma.name || 'Unknown'}</span></div>
                </div>`;
            }).join('');
        }
        function renderSupports(supports) {
            if (!els.cardGrid) return;
            els.cardGrid.innerHTML = supports.map(card => {
                const imgId = card.id || '10001';
                return `<div class="grid-card support-card">
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="grid-card-overlay">
                        <span class="grid-card-kicker">${(card.rarity || '?') + ' | ' + (card.type || '?')}</span>
                        <span class="grid-card-name">${card.name || 'Unknown'}</span>
                    </div>
                </div>`;
            }).join('');
        }
        function showDashboardView(data) {
            document.body.classList.add('dashboard-mode');
            els.loginView.style.display = 'none';
            els.dashboardView.style.display = '';
            els.dashboardView.classList.add('active');
            if (els.refreshBtn) els.refreshBtn.style.display = 'block';
            if (els.historyBtn) els.historyBtn.style.display = 'block';
            showNavbar();
            renderAccountStrip(data.account);
            syncDashboardHeight();
        }

        function renderCareerHistory(entries) {
            if (!els.historyList) return;
            if (!entries || !entries.length) {
                els.historyList.innerHTML = '<div class="history-empty">No finished careers yet. Completed careers show up here.</div>';
                return;
            }
            const star = String.fromCharCode(9733);
            els.historyList.innerHTML = entries.map(e => {
                const sparks = (e.sparks || []).map(s => {
                    const stars = Math.max(1, Math.min(3, Number(s.stars) || 1));
                    return `<span class="factor-badge f-${s.category || 'other'}">${escapeHtml(s.name || '?')} <span class="stars">${star.repeat(stars)}</span></span>`;
                }).join('') || '<span class="history-nospark">no sparks</span>';
                return `<div class="history-row">
                    <img class="history-portrait" src="/api/images/${e.card_id || '100101'}.png" onerror="hideBrokenImage(this)">
                    <div class="history-info">
                        <div class="history-head">
                            <span class="history-name">${escapeHtml(e.uma_name || 'Unknown')}</span>
                            <span class="history-rank">${escapeHtml(e.rank_letter || '?')}</span>
                        </div>
                        <div class="history-meta">${escapeHtml(e.when || '')}${e.fans ? ' · ' + Number(e.fans).toLocaleString() + ' fans' : ''}${e.preset ? ' · ' + escapeHtml(e.preset) : ''}</div>
                        <div class="history-sparks">${sparks}</div>
                    </div>
                </div>`;
            }).join('');
        }

        async function openCareerHistory() {
            if (!els.historyModal) return;
            els.historyModal.style.display = 'flex';
            els.historyList.innerHTML = '<div class="history-empty">Loading…</div>';
            try {
                const data = await apiJson('/api/career/history');
                renderCareerHistory(data.history || []);
            } catch (e) {
                els.historyList.innerHTML = `<div class="history-empty">${escapeHtml(e.message || 'Failed to load history')}</div>`;
            }
        }

        function autoLoadCareerSelection() {
            const activeCareer = state.account && state.account.career && state.account.career.active ? state.account.career : null;
            if (!activeCareer) return;

            resetSelection();
            document.querySelectorAll('.deck-container.selected, #uma-grid .grid-card.selected, #parent-grid .grid-card.selected, #friend-grid .grid-card.selected')
                .forEach(el => el.classList.remove('selected'));

            selectCareerDeck(activeCareer);

            if (activeCareer.card_id && dashData.umas) {
                const umaIdx = dashData.umas.findIndex(u => String(u.id) === String(activeCareer.card_id));
                if (umaIdx >= 0) {
                    selection.trainee = dashData.umas[umaIdx];
                    const umaEls = document.querySelectorAll('#uma-grid .grid-card');
                    if (umaEls[umaIdx]) umaEls[umaIdx].classList.add('selected');
                }
            }

            if (dashData.parents) {
                const p1 = activeCareer.parent_id_1;
                const p2 = activeCareer.parent_id_2;

                if (p1 || p2) {
                    dashData.parents.forEach((p, idx) => {
                        const pId = Number(p.instance_id);
                        if ((p1 && pId === Number(p1)) || (p2 && pId === Number(p2))) {
                            if (selection.veterans.length < 2 && !selection.veterans.find(v => Number(v.instance_id) === pId)) {
                                p._gridIdx = idx;
                                selection.veterans.push(p);
                                const parentEls = document.querySelectorAll('#parent-grid .grid-card');
                                if (parentEls[idx]) parentEls[idx].classList.add('selected');
                            }
                        }
                    });
                    updateVetSelectability();
                }
            }

            selectCareerFriend(activeCareer);
            renderTeamPanel();
        }

        function applyServerSelection(serverSelection) {
            if (!serverSelection) return;
            if (serverSelection.deck && dashData.validDecks) {
                const deckIdx = dashData.validDecks.findIndex(d => Number(d.id) === Number(serverSelection.deck.id));
                if (deckIdx >= 0) {
                    selection.deck = dashData.validDecks[deckIdx];
                    const deckEls = document.querySelectorAll('.deck-container');
                    if (deckEls[deckIdx]) deckEls[deckIdx].classList.add('selected');
                }
            }
            if (serverSelection.trainee && dashData.umas) {
                const umaIdx = dashData.umas.findIndex(u => String(u.id) === String(serverSelection.trainee.id));
                if (umaIdx >= 0) {
                    selection.trainee = dashData.umas[umaIdx];
                    const umaEls = document.querySelectorAll('#uma-grid .grid-card');
                    if (umaEls[umaIdx]) umaEls[umaIdx].classList.add('selected');
                }
            }
            if (serverSelection.veterans && dashData.parents) {
                serverSelection.veterans.forEach(v => {
                    const pIdx = dashData.parents.findIndex(p => Number(p.instance_id) === Number(v.instance_id));
                    if (pIdx >= 0 && selection.veterans.length < 2) {
                        const parent = dashData.parents[pIdx];
                        parent._gridIdx = pIdx;
                        selection.veterans.push(parent);
                        const parentEls = document.querySelectorAll('#parent-grid .grid-card');
                        if (parentEls[pIdx]) parentEls[pIdx].classList.add('selected');
                    }
                });
                updateVetSelectability();
            }
            if (serverSelection.friend) {
                state.pendingFriendSelection = {
                    viewer_id: String(serverSelection.friend.viewer_id),
                    support_card_id: String(serverSelection.friend.support_card_id)
                };
            }
        }

        async function renderDashboard(data, options = {}) {
            dashData = data;
            dashData.validDecks = data.decks.filter(isValidDeck);
            dashData.friends = data.friends || [];
            dashData.friendExcludeIds = data.friendExcludeIds || [];
            showDashboardView(data);
            renderCounts(data);
            renderDecks(dashData.validDecks);
            renderParents(data.parents);
            renderTrainees(dashData.umas);
            renderSupports(data.supports);
            resetSelection();
            if (data.selection) applyServerSelection(data.selection);
            autoLoadCareerSelection();
            // EVENT CHOICES is the library's main content now and starts expanded —
            // populate it from the active career's deck as soon as the dashboard lands.
            loadEvents();

            await loadPresets();
            if (!dashData.friends.length) {
                loadFriends(false);
            } else {
                renderFriends();
            }
            bindSparkTooltips();
            attachSelectionHandlers();
            setDeleteMode(false);   // fresh roster render -> start with delete mode off, no stale picks
            bindRaceHandlers();
            bindPresetHandlers();
            renderTeamPanel();

            startRunnerPolling();
            await waitForDomPaint(2);
            setLoadingScreen(false);
            await waitForDomPaint(2);
            if (options.animateIntro !== false) {
                playBrandIntro();
                if (options.waitForIntro) await sleep(780);
            }
        }

        async function restoreSession() {
            try {
                const data = await apiJson('/api/session?t=' + Date.now());
                if (data && data.success) await renderDashboard(data, { animateIntro: true, waitForIntro: false });
                else {
                    hideNavbar();
                    setLoadingScreen(false);
                }
            } catch (e) {
                hideNavbar();
                setLoadingScreen(false);
            }
        }
        bindDelayControls();
        bindMasterDataControls();
        bindDiscordWebhookControls();
        setLoadingScreen(true);
        restoreSession();
})();
