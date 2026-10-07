// Selected athletes in slot order. Each entry is the merged search payload +
// the /athlete-compare/athlete/{id} response (rating, rank, wins, programs).
let selectedAthletes = [];
let selectedProgram = null;   // one of 'elite-short' | 'elite-long' | 'ag', once chosen
let comparisonGraphsLoaded = false;

const slotsEl      = document.getElementById('athleteSlots');
const MAX_ATHLETES = parseInt(slotsEl.dataset.max, 10);
const MIN_SLOTS    = 2;

// Mirrors ATHLETE_COLORS in comparison.py so the selection cards match the
// chart lines and table headers in the results.
const ATHLETE_COLORS = ['#357ABD', '#E91E63', '#059669', '#F59E0B', '#7E57C2'];

const PROGRAM_LABELS = {
    'elite-short': 'Short Course',
    'elite-long':  'Long Course',
    'ag':          'Age Group',
};

function badgesHtml(athlete) {
    const tags = [];
    if (athlete.has_elite_short) tags.push('<span class="ptd-tag ptd-tag--sc">SC</span>');
    if (athlete.has_elite_long)  tags.push('<span class="ptd-tag ptd-tag--lc">LC</span>');
    if (athlete.has_ag)          tags.push('<span class="ptd-tag ptd-tag--ag">AG</span>');
    if (!tags.length) return '';
    return `<span class="result-meta-sep">·</span><span class="ptd-tag-row">${tags.join('')}</span>`;
}

function programsFromTags(athlete) {
    const out = [];
    if (athlete.has_elite_short) out.push('elite-short');
    if (athlete.has_elite_long)  out.push('elite-long');
    if (athlete.has_ag)          out.push('ag');
    return out;
}

function athletePrograms(a) {
    return a.programs || programsFromTags(a);
}

// Intersection of every selected athlete's programs. [] until two are selected.
function sharedPrograms() {
    if (selectedAthletes.length < 2) return [];
    return selectedAthletes
        .map(athletePrograms)
        .reduce((acc, ps) => acc.filter(p => ps.includes(p)));
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func(...args), wait);
    };
}

// Labels carry a short variant that CSS swaps in when the box is narrow.
function statsBlockHtml(data) {
    if (data == null || data.overall_rating == null) return '';
    const lbl = (long, short) => `<span class="sel-stat-lbl"><span class="sel-stat-lbl-long">${long}</span><span class="sel-stat-lbl-short">${short}</span></span>`;
    return `
        <div class="sel-athlete-stats">
            <div class="sel-stat">
                <span class="sel-stat-num">${data.overall_rating}</span>
                ${lbl('Rating', 'Rating')}
            </div>
            <div class="sel-stat-divider"></div>
            <div class="sel-stat">
                <span class="sel-stat-num">${data.world_rank != null ? '#' + data.world_rank : '-'}</span>
                ${data.world_rank_is_peak ? lbl('Peak rank', 'Peak') : lbl('World rank', 'Rank')}
            </div>
            <div class="sel-stat-divider"></div>
            <div class="sel-stat">
                <span class="sel-stat-num">${data.wins ?? '-'}</span>
                ${lbl('Career wins', 'Wins')}
            </div>
        </div>`;
}

function selectedCardHtml(a) {
    const baseUrl    = window.STATIC_BASE_URL || '';
    const imgSrc     = `${baseUrl}athlete_imgs/128/${a.id}.webp`;
    const defaultImg = `${baseUrl}imgs/default_user.jpg`;
    return `
        <div class="sel-athlete-card">
            <img class="sel-athlete-img" src="${imgSrc}" onerror="this.src='${defaultImg}'" alt="${escapeHtml(a.name)}">
            <div class="sel-athlete-details">
                <div class="sel-athlete-name">${escapeHtml(a.name)} ${flagImg(a.country_alpha3 || '', a.country_name || '')}</div>
                ${a.loading ? '<div class="sel-loading">Loading…</div>' : statsBlockHtml(a)}
            </div>
        </div>`;
}

// ---------------------------------------------------------------------------
// Slot rendering. The grid always shows the selected athletes followed by one
// empty search slot, padded to MIN_SLOTS and capped at MAX_ATHLETES. Every
// state change re-renders from `selectedAthletes`.
// ---------------------------------------------------------------------------
function renderSlots(keepTyped = true) {
    const n = selectedAthletes.length;
    const slotCount = Math.min(MAX_ATHLETES, Math.max(MIN_SLOTS, n + 1));
    const tpl = document.getElementById('slotTemplate');

    // Keep the text typed into an open search box across re-renders (e.g. a
    // stats refresh finishing while the user is typing the next name).
    const openInput = slotsEl.querySelector('.search-box:not(.has-selection) .search-input');
    const pending   = keepTyped && openInput ? { value: openInput.value, focused: document.activeElement === openInput } : null;

    slotsEl.innerHTML = '';
    slotsEl.dataset.count = slotCount;
    let toFocus = null;
    for (let i = 0; i < slotCount; i++) {
        const box = tpl.content.firstElementChild.cloneNode(true);
        const athlete = selectedAthletes[i];
        box.dataset.slot = i;
        box.querySelector('.slot-dot').style.background = ATHLETE_COLORS[i];
        box.querySelector('.slot-label').textContent = athlete ? `Athlete ${i + 1}` : (i >= MIN_SLOTS ? 'Add athlete' : `Athlete ${i + 1}`);
        if (i >= MIN_SLOTS && !athlete) box.classList.add('is-extra');

        const selectedDiv = box.querySelector('.selected-athlete');
        if (athlete) {
            box.classList.add('has-selection');
            box.querySelector('.search-input-wrapper').classList.add('hidden');
            selectedDiv.classList.add('active');
            selectedDiv.innerHTML = selectedCardHtml(athlete);
            box.querySelector('.sel-remove-btn').addEventListener('click', () => removeAthlete(i));
        } else {
            const input = box.querySelector('.search-input');
            if (n === 0) input.placeholder = 'Search athlete name...';
            else input.placeholder = n === 1 ? 'Search athlete to compare...' : 'Add another athlete...';
            wireSearch(box, input, box.querySelector('.search-results'));
            if (pending && i === n) {
                input.value = pending.value;
                if (pending.focused) toFocus = input;
            }
        }
        slotsEl.appendChild(box);
    }
    if (toFocus) toFocus.focus();   // only works once the box is in the DOM
    refreshProgramPicker();
}

function wireSearch(box, searchInput, resultsDiv) {
    const performSearch = debounce(async (query) => {
        if (query.length < 2) {
            resultsDiv.classList.remove('active');
            return;
        }
        // Later picks must share gender with the first athlete and at least one
        // program with everyone already selected.
        let url = `/athlete-compare/search?q=${encodeURIComponent(query)}`;
        if (selectedAthletes.length) {
            url += `&gender=${encodeURIComponent(selectedAthletes[0].gender)}`;
            const programs = selectedAthletes.length === 1
                ? athletePrograms(selectedAthletes[0])
                : sharedPrograms();
            if (programs.length) url += `&programs=${encodeURIComponent(programs.join(','))}`;
        }
        try {
            const response = await fetch(url);
            let data = await response.json();
            const chosen = new Set(selectedAthletes.map(a => a.id));
            data = data.filter(a => !chosen.has(a.athlete_id));

            if (data.length > 0) {
                const baseUrl = window.STATIC_BASE_URL || '';
                const defaultImg = `${baseUrl}imgs/default_user.jpg`;
                resultsDiv.innerHTML = data.map(athlete => {
                    const imgSrc = `${baseUrl}athlete_imgs/128/${athlete.athlete_id}.webp`;
                    return `
                    <div class="search-result-item" data-id="${athlete.athlete_id}">
                        <img class="result-avatar" src="${imgSrc}" onerror="this.src='${defaultImg}'" alt="${escapeHtml(athlete.name)}">
                        <div class="result-info">
                            <div class="result-name">${escapeHtml(athlete.name)}</div>
                            <div class="result-meta"><span>${flagImg(athlete.country_alpha3, athlete.country_name)} ${escapeHtml(athlete.country_name)}${athlete.year_of_birth ? ' · ' + athlete.year_of_birth : ''}</span>${badgesHtml(athlete)}</div>
                        </div>
                    </div>`;
                }).join('');
                resultsDiv.classList.add('active');
                resultsDiv.querySelectorAll('.search-result-item').forEach(item => {
                    const athlete = data.find(a => a.athlete_id === parseInt(item.dataset.id, 10));
                    item.addEventListener('click', () => addAthlete({
                        id: athlete.athlete_id,
                        name: athlete.name,
                        gender: athlete.gender,
                        country_name: athlete.country_name,
                        country_alpha3: athlete.country_alpha3,
                        year_of_birth: athlete.year_of_birth,
                        has_elite_short: athlete.has_elite_short,
                        has_elite_long: athlete.has_elite_long,
                        has_ag: athlete.has_ag,
                    }));
                });
            } else {
                resultsDiv.innerHTML = '<div class="search-result-item">No athletes found</div>';
                resultsDiv.classList.add('active');
            }
        } catch (error) {
            console.error('Search error:', error);
        }
    }, 300);

    searchInput.addEventListener('input', (e) => performSearch(e.target.value));
}

// Close any open results dropdown when clicking elsewhere.
document.addEventListener('click', (e) => {
    slotsEl.querySelectorAll('.search-results.active').forEach(div => {
        if (!div.contains(e.target) && !div.previousElementSibling.contains(e.target)) {
            div.classList.remove('active');
        }
    });
});

async function fetchAthleteFull(id, program) {
    const url = program
        ? `/athlete-compare/athlete/${id}?program=${encodeURIComponent(program)}`
        : `/athlete-compare/athlete/${id}`;
    const res = await fetch(url);
    if (!res.ok) return null;
    const full = await res.json();
    full.id = full.athlete_id;
    return full;
}

// Add an athlete to the next slot, then fetch its full data (rating, rank,
// wins, programs) under the current program and re-render.
async function addAthlete(athlete) {
    if (selectedAthletes.length >= MAX_ATHLETES) return;
    const entry = { ...athlete, loading: true };
    selectedAthletes.push(entry);
    renderSlots(/* keepTyped= */ false);   // the typed query has done its job
    // Defer past the click that got us here so it can't steal focus back.
    setTimeout(() => slotsEl.querySelector('.search-box:not(.has-selection) .search-input')?.focus(), 0);

    // renderSlots has already picked the shared program (if any), so this fetch
    // returns stats for the right course. Match by id afterwards: a concurrent
    // refreshAllStats may have swapped the entry object out.
    const full = await fetchAthleteFull(athlete.id, selectedProgram);
    const idx = selectedAthletes.findIndex(a => a.id === athlete.id);
    if (idx === -1) return;   // removed while loading
    selectedAthletes[idx] = { ...selectedAthletes[idx], ...(full || {}), loading: false };
    renderSlots();
}

function removeAthlete(index) {
    selectedAthletes.splice(index, 1);
    renderSlots();
    const firstEmpty = slotsEl.querySelector('.search-box:not(.has-selection) .search-input');
    if (firstEmpty) firstEmpty.focus();
}

// Refetch every athlete's stats under `program` (course toggle changed, or a
// new pick narrowed the shared programs) and re-render the cards.
async function refreshAllStats(program) {
    const fulls = await Promise.all(selectedAthletes.map(a => fetchAthleteFull(a.id, program)));
    fulls.forEach((full, i) => {
        if (!full || !selectedAthletes[i] || selectedAthletes[i].id !== full.id) return;
        // Programs list is program-agnostic; keep the original so a transient
        // refresh can't drop it.
        selectedAthletes[i] = { ...selectedAthletes[i], ...full, programs: selectedAthletes[i].programs || full.programs };
    });
    slotsEl.querySelectorAll('.search-box.has-selection').forEach((box, i) => {
        const a = selectedAthletes[i];
        if (a) box.querySelector('.selected-athlete').innerHTML = selectedCardHtml(a);
    });
}

// Render the program picker (or hide it). Shown when 2+ athletes are selected
// AND they share more than one program; single-program sets auto-select
// without UI, sets with nothing in common surface an inline hint.
function refreshProgramPicker() {
    const picker     = document.getElementById('programPicker');
    const chips      = document.getElementById('programPickerChips');
    const hint       = document.getElementById('programPickerHint');
    const compareBtn = document.getElementById('compareBtn');

    picker.hidden = true;
    chips.innerHTML = '';
    hint.textContent = '';
    hint.hidden = true;
    compareBtn.textContent = selectedAthletes.length > 2
        ? `Compare ${selectedAthletes.length} Athletes` : 'Compare Athletes';

    if (selectedAthletes.length < 2) {
        selectedProgram = null;
        compareBtn.disabled = true;
        return;
    }

    const shared = sharedPrograms();
    if (shared.length === 0) {
        selectedProgram = null;
        compareBtn.disabled = true;
        hint.textContent = "These athletes don't share a program and can't be compared.";
        hint.hidden = false;
        return;
    }

    // Keep a previously-picked program if still valid, else default to first.
    const prevSelected = selectedProgram;
    if (!selectedProgram || !shared.includes(selectedProgram)) {
        selectedProgram = shared[0];
    }
    if (selectedProgram !== prevSelected) refreshAllStats(selectedProgram);

    compareBtn.disabled = selectedAthletes.some(a => a.loading);
    if (shared.length === 1) return;

    chips.innerHTML = shared.map(p => `
        <input type="radio" name="compare-program" id="program-${p}" value="${p}"${p === selectedProgram ? ' checked' : ''}>
        <label for="program-${p}">${PROGRAM_LABELS[p] || p}</label>
    `).join('');
    chips.querySelectorAll('input[name="compare-program"]').forEach(r => {
        r.addEventListener('change', () => {
            if (r.checked) {
                selectedProgram = r.value;
                refreshAllStats(selectedProgram);
            }
        });
    });
    picker.hidden = false;
}

function showError(message) {
    const errorDiv = document.getElementById('errorMsg');
    errorDiv.textContent = message;
    errorDiv.classList.add('active');
    setTimeout(() => errorDiv.classList.remove('active'), 5000);
}

// URL forms: ?a=1,2,3 (current), ?a1=&a2= (older pair links), ?athlete1= (single
// prefill from the athlete page). All accept &program=.
async function prefillFromUrl() {
    const params = new URLSearchParams(window.location.search);
    let ids = (params.get('a') || '').split(',').filter(Boolean);
    if (!ids.length) {
        ids = [params.get('a1') || params.get('athlete1'), params.get('a2')].filter(Boolean);
    }
    ids = [...new Set(ids)].slice(0, MAX_ATHLETES);
    if (!ids.length) return;
    const urlProgram = params.get('program');

    try {
        const fulls = (await Promise.all(ids.map(id => fetchAthleteFull(id, null)))).filter(Boolean);
        selectedAthletes = fulls.map(a => ({ ...a, loading: false }));
        // Honour ?program= when everyone shares it, otherwise renderSlots picks a default.
        if (urlProgram && sharedPrograms().includes(urlProgram)) selectedProgram = urlProgram;
        renderSlots();
        if (selectedAthletes.length >= 2 && selectedProgram) await performComparison(/* pushState= */ false);
    } catch (error) {
        console.error('Prefill error:', error);
    }
}

async function performComparison(pushState = true) {
    if (!selectedProgram || selectedAthletes.length < 2) return;
    const loadingDiv = document.getElementById('loading');
    const resultsDiv = document.getElementById('comparisonResults');

    loadingDiv.classList.add('active');
    resultsDiv.classList.remove('active');

    const ids = selectedAthletes.map(a => a.id).join(',');
    const program = selectedProgram;

    try {
        const response = await fetch(`/athlete-compare/results?a=${ids}&program=${encodeURIComponent(program)}`,
                                     { headers: { 'X-Partial': '1' } });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Comparison failed');
        }
        resultsDiv.innerHTML = await response.text();
        resultsDiv.classList.add('active');

        if (pushState) {
            history.pushState({ a: ids, program }, '', `?a=${ids}&program=${program}`);
        }
        loadComparisonResultsJs();
    } catch (error) {
        showError(error.message);
    } finally {
        loadingDiv.classList.remove('active');
    }
}

// comparison_results.js wires up the chips on load via its IIFE. On re-runs
// (new athlete set while on the same page), re-append the script so the
// newly rendered DOM is wired up fresh.
function loadComparisonResultsJs() {
    const script = document.createElement("script");
    const baseUrl = window.STATIC_BASE_URL || "https://www.static.protridata/";
    script.src = `${baseUrl}js/comparison_results.js?ts=${Date.now()}`;
    document.body.appendChild(script);
    script.onload = () => { comparisonGraphsLoaded = true; };
}

renderSlots();
prefillFromUrl();
document.getElementById('compareBtn').addEventListener('click', () => performComparison());
