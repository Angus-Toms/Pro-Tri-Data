// ── Race search (hero) ──
const input       = document.getElementById('rs-input');
const filterBtn   = document.getElementById('filterToggle');
const filterPanel = document.getElementById('filterPanel');
const results     = document.getElementById('hub-results');
const sortEl      = document.getElementById('rs-sort');
const countryEl   = document.getElementById('rs-country');
const yearStartEl = document.getElementById('rs-year-start');
const yearEndEl   = document.getElementById('rs-year-end');
const resetBtn    = document.getElementById('hub-reset');

// The panel is closed by default, so the button carries the count of active filters
function updateFilterCount() {
    const n = (sortEl.value !== 'desc') + !!countryEl.value + !!(yearStartEl.value || yearEndEl.value);
    filterBtn.textContent = n ? `Filters (${n})` : 'Filters';
    filterBtn.classList.toggle('active', n > 0);
}

filterBtn.addEventListener('click', () => {
    const open = filterPanel.classList.toggle('open');
    filterBtn.setAttribute('aria-expanded', open);
});

let searchTimer;
let data = null;      // last response, in the header search's shape
let type = 'all';     // results tab
let reqToken = 0;

function runSearch() {
    const q = input.value.trim().replace(/\s+/g, ' ');
    const token = ++reqToken;
    if (q.length < 2) {
        data = null;
        renderResults();
        return;
    }
    const params = new URLSearchParams({ q, sort: sortEl.value });
    if (countryEl.value)   params.set('country', countryEl.value);
    if (yearStartEl.value) params.set('year_start', yearStartEl.value);
    if (yearEndEl.value)   params.set('year_end', yearEndEl.value);

    results.classList.add('is-loading');
    fetch(`/races/search?${params}`)
        .then(r => r.json())
        .then(d => {
            if (token !== reqToken) return;
            gsRows.highlight(q);
            data = d;
            renderResults();
        })
        .finally(() => { if (token === reqToken) results.classList.remove('is-loading'); });
}

function onFilterChange() {
    updateFilterCount();
    runSearch();
}

input.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 200);
});
[sortEl, countryEl].forEach(el => el.addEventListener('change', onFilterChange));
// Count now, search once typing pauses (the timer is shared with the search box)
[yearStartEl, yearEndEl].forEach(el => el.addEventListener('input', () => {
    updateFilterCount();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 400);
}));

resetBtn.addEventListener('click', () => {
    sortEl.value      = 'desc';
    countryEl.value   = '';
    yearStartEl.value = '';
    yearEndEl.value   = '';
    input.value       = '';
    type              = 'all';
    data              = null;
    renderResults();
    updateFilterCount();
});

// Results use the header search's rows (header.js) under its pill tabs. All
// shows each type's top rows, series first as in the header; a tab shows all.
const TYPES = {
    series: { label: 'Series',          noun: 'series',          top: 2, total: d => d.series.length,
              rows: d => d.series.map(gsRows.seriesRow) },
    groups: { label: 'Recurring races', noun: 'recurring races', top: 4, total: d => d.groups_total,
              rows: d => d.groups.map(gsRows.groupRow) },
    events: { label: 'Events',          noun: 'events',          top: 6, total: d => d.events_total,
              rows: d => d.events.map(gsRows.eventRow) },
};

function renderResults() {
    if (!data) {
        results.innerHTML = '';
        return;
    }
    const q = escapeHtml(input.value.trim());
    const rows = Object.fromEntries(Object.entries(TYPES).map(([k, t]) => [k, t.rows(data)]));
    const tab = (k, label, n) =>
        `<button type="button" class="gs-tab${type === k ? ' is-active' : ''}${n === 0 ? ' is-empty' : ''}" data-type="${k}">` +
        `${label}<span class="gs-tab-count">${n || ''}</span></button>`;
    const tabs = tab('all', 'All', null) + Object.entries(TYPES).map(([k, t]) => tab(k, t.label, t.total(data))).join('');

    let body;
    if (type === 'all') {
        const present = Object.keys(TYPES).filter(k => rows[k].length);
        body = present.map(k => {
            const t = TYPES[k], total = t.total(data);
            const shown = present.length === 1 ? rows[k].length : t.top;
            const more = total > shown ? `<button type="button" class="gs-more" data-type="${k}">All ${total}</button>` : '';
            return `<section class="gs-section"><div class="gs-section-head"><span>${t.label}</span>${more}</div>${rows[k].slice(0, shown).join('')}</section>`;
        }).join('') || `<div class="gs-message">No races or series match "${q}".</div>`;
    } else {
        const t = TYPES[type], total = t.total(data), n = rows[type].length;
        const foot = total > n ? `<div class="gs-message gs-foot">Top ${n} of ${total.toLocaleString()} ${t.noun}. Keep typing or filter to narrow it down.</div>` : '';
        body = n ? rows[type].join('') + foot : `<div class="gs-message">No ${t.noun} match "${q}".</div>`;
    }
    results.innerHTML = `<div class="gs-tabs">${tabs}</div><div class="hub-results-body">${body}</div>`;
    // A single recurring race opens straight onto its editions, as in the header
    if (data.groups.length === 1) results.querySelectorAll('.gs-group').forEach(g => gsRows.setOpen(g, true));
}

results.addEventListener('click', e => {
    const pick = e.target.closest('[data-type]');
    if (pick) {
        type = pick.dataset.type;
        renderResults();
        return;
    }
    const ex = e.target.closest('[data-gs-expand]');
    if (ex) {
        const group = ex.closest('.gs-group');
        gsRows.setOpen(group, !group.classList.contains('is-open'));
    }
});
