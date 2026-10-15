// ── Race search (hero) ──
const input       = document.getElementById('rs-input');
const filterBtn   = document.getElementById('filterToggle');
const filterPanel = document.getElementById('filterPanel');
const results     = document.getElementById('rs-results');
const countryEl   = document.getElementById('rs-country');
const yearStartEl = document.getElementById('rs-year-start');
const yearEndEl   = document.getElementById('rs-year-end');
const resetBtn    = document.getElementById('rs-reset');

function getSort() { return document.querySelector('input[name="rs-sort"]:checked').value; }

// The panel is closed by default, so the button carries the count of active filters
function updateFilterCount() {
    const n = (getSort() !== 'desc') + !!countryEl.value + !!(yearStartEl.value || yearEndEl.value);
    filterBtn.textContent = n ? `Filters (${n})` : 'Filters';
    filterBtn.classList.toggle('active', n > 0);
}

filterBtn.addEventListener('click', () => {
    const open = filterPanel.classList.toggle('open');
    filterBtn.setAttribute('aria-expanded', open);
});

let searchTimer;

function runSearch() {
    const q = input.value.trim();
    if (q.length < 2) {
        results.innerHTML = '';
        return;
    }
    const params = new URLSearchParams({ q, sort: getSort() });
    if (countryEl.value)   params.set('country', countryEl.value);
    if (yearStartEl.value) params.set('year_start', yearStartEl.value);
    if (yearEndEl.value)   params.set('year_end', yearEndEl.value);

    results.innerHTML = '<div class="rs-loading">Searching…</div>';
    fetch(`/races/search?${params}`)
        .then(r => r.json())
        .then(renderResults);
}

function onFilterChange() {
    updateFilterCount();
    runSearch();
}

input.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 200);
});
document.querySelectorAll('input[name="rs-sort"]').forEach(r => r.addEventListener('change', onFilterChange));
countryEl.addEventListener('change', onFilterChange);
[yearStartEl, yearEndEl].forEach(el => el.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(onFilterChange, 400);
}));

resetBtn.addEventListener('click', () => {
    document.getElementById('sort-desc').checked = true;
    countryEl.value   = '';
    yearStartEl.value = '';
    yearEndEl.value   = '';
    input.value       = '';
    results.innerHTML = '';
    updateFilterCount();
});

function renderResults(events) {
    if (!events.length) {
        results.innerHTML = '<div class="rs-no-results">No events found</div>';
        return;
    }
    results.innerHTML = events.map(ev => {
        const races = ev.races || [];
        const meta = [ev.venue, ev.country, ev.event_date].filter(Boolean).map(escapeHtml).join(' · ');

        // Programs at an event share course length, so emit one chip next
        // to the event name rather than repeating it on every program pill.
        const course = races.find(r => r.course)?.course;
        const chip = course === 'long'
            ? '<span class="ptd-tag ptd-tag--sm ptd-tag--lc">LC</span>'
            : course === 'short'
                ? '<span class="ptd-tag ptd-tag--sm ptd-tag--sc">SC</span>'
                : '';
        const pills = races.map(r =>
            `<a href="/race/${r.race_id}" class="race-pill">${escapeHtml(r.prog_name)}</a>`).join('');

        return `
            <div class="rs-result-item">
                <div class="rs-result-name-row">
                    <a href="/event/${ev.event_id}" class="rs-result-name">${escapeHtml(ev.name)}</a>
                    ${chip}
                </div>
                <div class="rs-result-meta">${meta}</div>
                ${races.length ? `<div class="rs-result-races">${pills}</div>` : ''}
            </div>`;
    }).join('');
}

// ── Calendar tabs: the section link follows the tab ──
const calLink = document.getElementById('cal-link');
document.querySelectorAll('.rs-tab').forEach(tab => tab.addEventListener('click', () => {
    document.querySelectorAll('.rs-tab').forEach(t => {
        t.classList.toggle('active', t === tab);
        t.setAttribute('aria-selected', t === tab);
        document.querySelector(`.rs-cal[data-pane="${t.dataset.tab}"]`).hidden = t !== tab;
    });
    calLink.href = tab.dataset.link;
    calLink.textContent = tab.dataset.label;
}));
