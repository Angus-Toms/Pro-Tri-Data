// ── Athlete search (hero) ──
const input       = document.getElementById('as-input');
const filterBtn   = document.getElementById('filterToggle');
const filterPanel = document.getElementById('filterPanel');
const results     = document.getElementById('as-results');
const programEl   = document.getElementById('as-program');
const countryEl   = document.getElementById('as-country');
const yobStartEl  = document.getElementById('as-yob-start');
const yobEndEl    = document.getElementById('as-yob-end');
const activeEl    = document.getElementById('as-active');
const resetBtn    = document.getElementById('as-reset');

// The panel is closed by default, so the button carries the count of active filters
function updateFilterCount() {
    const n = !!programEl.value + !!countryEl.value + !!(yobStartEl.value || yobEndEl.value) + activeEl.checked;
    filterBtn.textContent = n ? `Filters (${n})` : 'Filters';
    filterBtn.classList.toggle('active', n > 0);
}

filterBtn.addEventListener('click', () => {
    const open = filterPanel.classList.toggle('open');
    filterBtn.setAttribute('aria-expanded', open);
});

let searchTimer;
let data = null;      // last response, in the header search's shape
let reqToken = 0;

function runSearch() {
    const q = input.value.trim().replace(/\s+/g, ' ');
    const token = ++reqToken;
    if (q.length < 2) {
        data = null;
        renderResults();
        return;
    }
    const params = new URLSearchParams({ q });
    if (programEl.value)  params.set('program', programEl.value);
    if (countryEl.value)  params.set('country', countryEl.value);
    if (yobStartEl.value) params.set('yob_start', yobStartEl.value);
    if (yobEndEl.value)   params.set('yob_end', yobEndEl.value);
    if (activeEl.checked) params.set('active_only', 'true');

    results.classList.add('is-loading');
    fetch(`/athletes/search?${params}`)
        .then(r => r.json())
        .then(d => {
            if (token !== reqToken) return;
            gsRows.highlight(q);
            data = d;
            renderResults();
        })
        .finally(() => { if (token === reqToken) results.classList.remove('is-loading'); });
}

// Results use the header search's athlete rows (header.js)
function renderResults() {
    if (!data) {
        results.innerHTML = '';
        return;
    }
    const q = escapeHtml(input.value.trim());
    const total = data.athletes_total, n = data.athletes.length;
    const foot = total > n ? `<div class="gs-message gs-foot">Top ${n} of ${total.toLocaleString()} athletes. Keep typing or filter to narrow it down.</div>` : '';
    results.innerHTML = n
        ? `<div class="hub-results-body"><div class="gs-section-head"><span>${total.toLocaleString()} athlete${total === 1 ? '' : 's'}</span></div>${data.athletes.map(gsRows.athleteRow).join('')}${foot}</div>`
        : `<div class="gs-message">No athletes match "${q}".</div>`;
}

function onFilterChange() {
    updateFilterCount();
    runSearch();
}

input.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 200);
});
[programEl, countryEl, activeEl].forEach(el => el.addEventListener('change', onFilterChange));
// Count now, search once typing pauses (the timer is shared with the search box)
[yobStartEl, yobEndEl].forEach(el => el.addEventListener('input', () => {
    updateFilterCount();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 400);
}));
// U23 and Junior: born in that year or later
document.querySelectorAll('[data-born]').forEach(b => b.addEventListener('click', () => {
    yobStartEl.value = b.dataset.born;
    yobEndEl.value = '';
    onFilterChange();
}));

resetBtn.addEventListener('click', () => {
    programEl.value  = '';
    countryEl.value  = '';
    yobStartEl.value = '';
    yobEndEl.value   = '';
    activeEl.checked = false;
    input.value      = '';
    data             = null;
    renderResults();
    updateFilterCount();
});
