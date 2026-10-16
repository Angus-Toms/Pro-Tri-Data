// Hub pages (/races, /athletes). A tab shows its pane and hides its group's
// others; a section link marked data-follows="<group>" points at the active
// tab's page (data-link), and takes its wording (data-label) when it has one.
document.querySelectorAll('.hub-tab[data-group]').forEach(tab => tab.addEventListener('click', () => {
    const group = tab.dataset.group;
    document.querySelectorAll(`.hub-tab[data-group="${group}"]`).forEach(t => {
        t.classList.toggle('active', t === tab);
        t.setAttribute('aria-selected', t === tab);
        document.querySelector(`[data-pane="${t.dataset.tab}"]`).hidden = t !== tab;
    });
    const link = document.querySelector(`[data-follows="${group}"]`);
    if (link) {
        link.href = tab.dataset.link;
        if (tab.dataset.label) link.textContent = tab.dataset.label;
    }
}));

// Hero athlete search (/athletes, /athlete-leaderboard, /country): header.js's
// athlete rows in the results card under the hero. params() gives the filters
// to send. Returns run (search now) and later (search once typing pauses).
function hubAthleteSearch(input, results, params) {
    let timer, token = 0;
    function run() {
        const q = input.value.trim().replace(/\s+/g, ' ');
        const t = ++token;
        if (q.length < 2) {
            results.innerHTML = '';
            return;
        }
        results.classList.add('is-loading');
        fetch(`/athletes/search?${new URLSearchParams({ q, ...params() })}`)
            .then(r => r.json())
            .then(d => {
                if (t !== token) return;
                gsRows.highlight(q);
                const total = d.athletes_total, n = d.athletes.length;
                const foot = total > n ? `<div class="gs-message gs-foot">Top ${n} of ${total.toLocaleString()} athletes. Keep typing or filter to narrow it down.</div>` : '';
                results.innerHTML = n
                    ? `<div class="hub-results-body"><div class="gs-section-head"><span>${total.toLocaleString()} athlete${total === 1 ? '' : 's'}</span></div>${d.athletes.map(gsRows.athleteRow).join('')}${foot}</div>`
                    : `<div class="gs-message">No athletes match "${escapeHtml(q)}".</div>`;
            })
            .finally(() => { if (t === token) results.classList.remove('is-loading'); });
    }
    const later = ms => { clearTimeout(timer); timer = setTimeout(run, ms); };
    input.addEventListener('input', () => later(200));
    return { run, later };
}
