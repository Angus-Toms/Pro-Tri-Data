// ── Athlete leaderboard (/athlete-leaderboard) ──
const filterBtn = document.getElementById('filterToggle');
const panel     = document.getElementById('filterPanel');

function setOpen(open) {
    panel.classList.toggle('open', open);
    filterBtn.setAttribute('aria-expanded', open);
}
filterBtn.addEventListener('click', () => setOpen(!panel.classList.contains('open')));
// A filter change reloads the page; reopen the panel so the next can be set
if (sessionStorage.getItem('lbFiltersOpen')) {
    sessionStorage.removeItem('lbFiltersOpen');
    setOpen(true);
}

// A change reloads the list. The URL keeps only what differs from the
// router's defaults (gender is always written).
function go(changes, fromPanel) {
    const p = new URLSearchParams(location.search);
    for (const [k, v] of Object.entries(changes)) {
        if (v === null) p.delete(k);
        else p.set(k, v);
    }
    if (fromPanel) sessionStorage.setItem('lbFiltersOpen', '1');
    location.href = `/athlete-leaderboard?${p}`;
}
document.getElementById('lb-disc').addEventListener('change', e => {
    go({ disc: e.target.value === 'overall' ? null : e.target.value });
});
panel.addEventListener('change', e => {
    const el = e.target;
    if (el.name === 'active_only') go({ active_only: el.checked ? null : 'false' }, true);
    else if (el.name === 'country') go({ country: el.value === 'all' ? null : el.value }, true);
    else if (el.name === 'yob_start' || el.name === 'yob_end') {
        if (!el.checkValidity()) return el.reportValidity();
        go({ [el.name]: el.value || null }, true);
    }
});
// U23 and Junior: born in that year or later
panel.querySelectorAll('[data-born]').forEach(b => b.addEventListener('click', () => {
    go({ yob_start: b.dataset.born, yob_end: null }, true);
}));

// Hero search: athletes in this list's programme (hub.js)
const input = document.getElementById('lb-input');
const program = { 'elite:short': 'short', 'elite:long': 'long', 'ag:short': 'ag' }[input.dataset.program];
hubAthleteSearch(input, document.getElementById('lb-results'), () => program ? { program } : {});

// Show 50 more
const moreBtn = document.getElementById('lb-more');
if (moreBtn) moreBtn.addEventListener('click', async () => {
    moreBtn.disabled = true;
    const list = document.getElementById('lb-list');
    const res = await fetch(`${moreBtn.dataset.url}&offset=${list.children.length}`);
    list.insertAdjacentHTML('beforeend', await res.text());
    initFollowButtons(list);
    if (res.headers.get('X-Has-More') === '1') moreBtn.disabled = false;
    else moreBtn.parentElement.remove();
});
