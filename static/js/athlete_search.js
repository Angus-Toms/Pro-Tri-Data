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

// Results use the header search's athlete rows (hub.js, header.js)
const search = hubAthleteSearch(input, results, () => {
    const p = {};
    if (programEl.value)  p.program = programEl.value;
    if (countryEl.value)  p.country = countryEl.value;
    if (yobStartEl.value) p.yob_start = yobStartEl.value;
    if (yobEndEl.value)   p.yob_end = yobEndEl.value;
    if (activeEl.checked) p.active_only = 'true';
    return p;
});

function onFilterChange() {
    updateFilterCount();
    search.run();
}

[programEl, countryEl, activeEl].forEach(el => el.addEventListener('change', onFilterChange));
// Count now, search once typing pauses
[yobStartEl, yobEndEl].forEach(el => el.addEventListener('input', () => {
    updateFilterCount();
    search.later(400);
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
    search.run();
    updateFilterCount();
});
