// Wrapped in an IIFE so re-executing this script (after turbo-lite partial
// nav swaps the main content) doesn't collide with previous top-level `const`
// bindings. Each re-run gets a fresh lexical scope; the nav handler destroys
// the old Chart.js instances before the swap.
(function() {
// ---------- Turbo-lite partial navigation for the mode switcher -------------
// Bound FIRST so any later init error in this file doesn't leave the pills
// falling back to full-document navigation. Idempotent via window guard.
if (!window._ptdAthleteNavBound) {
    window._ptdAthleteNavBound = true;
    document.addEventListener('click', async (e) => {
        const link = e.target.closest('a[data-ptd-nav="athlete"]');
        if (!link) return;
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
        e.preventDefault();
        const url = link.getAttribute('href');
        try {
            const resp = await fetch(url, { credentials: 'same-origin' });
            if (!resp.ok) throw new Error(`status ${resp.status}`);
            const html = await resp.text();
            const doc = new DOMParser().parseFromString(html, 'text/html');
            // Only the career swaps; the person header and upcoming races stay.
            const newContent  = doc.querySelector('#athlete-ajax-content');
            const currContent = document.querySelector('#athlete-ajax-content');
            if (!newContent || !currContent) throw new Error('ajax targets missing');
            // Chart.js keeps every chart in Chart.instances until destroy(), so
            // swapping the canvases out would leak 23 instances per switch.
            Object.values(Chart.instances).forEach(c => c.destroy());
            currContent.replaceWith(newContent);
            // Compare in the header presets the career on screen.
            document.querySelector('.athlete-compare-link').href = doc.querySelector('.athlete-compare-link').getAttribute('href');
            initSortIcons();
            document.title = doc.title;
            history.pushState({}, '', url);
            const currScript = document.querySelector('script[src*="js/athlete.js"]');
            if (currScript) {
                const fresh = document.createElement('script');
                for (const a of currScript.attributes) fresh.setAttribute(a.name, a.value);
                currScript.remove();
                document.body.appendChild(fresh);
            }
        } catch (err) {
            console.warn('athlete partial nav failed, falling back to reload:', err);
            window.location.href = url;
        }
    });
    window.addEventListener('popstate', () => { window.location.reload(); });
}

// ---------- Doping sanction interstitial -----------------------------------
// Full-screen acknowledgement shown once per session per athlete before the
// profile is revealed. The overlay lives outside the AJAX-swapped hero/content
// so course switches leave it (and the rotating marquee) untouched.
(function initDopingOverlay() {
    const overlay = document.getElementById('dopingOverlay');
    if (!overlay || overlay.dataset.bound) return;
    overlay.dataset.bound = '1';
    const key = 'dopingSeen:' + overlay.dataset.athlete;
    if (sessionStorage.getItem(key)) {
        overlay.remove();
        return;
    }
    document.body.style.overflow = 'hidden';
    const dismiss = () => {
        sessionStorage.setItem(key, '1');
        overlay.classList.add('is-hiding');
        document.body.style.overflow = '';
        setTimeout(() => overlay.remove(), 400);
    };
    document.getElementById('dopingContinue')?.addEventListener('click', dismiss);
})();

// Shared constants used by both rankings and ratings charts
const DISC_COLORS = {
    overall:    '#E87722',  // orange
    swim:       '#38bdf8',  // sky blue
    bike:       '#a78bfa',  // violet
    run:        '#34d399',  // emerald
    transition: '#f472b6',  // pink
};
const DISC_LABELS = { overall: 'Overall', swim: 'Swim', bike: 'Bike', run: 'Run', transition: 'Transition' };

// One tooltip element per ranking type, same style as the ratings tooltip
function _makeRankTooltipEl(id) {
    const existing = document.getElementById(id);
    if (existing) return existing;
    const el = document.createElement('div');
    el.id = id;
    Object.assign(el.style, {
        position: 'fixed', pointerEvents: 'none', opacity: '0',
        background: '#1a1a2e', borderRadius: '10px',
        fontFamily: "'Plus Jakarta Sans', sans-serif",
        border: '1px solid rgba(255,255,255,0.1)',
        boxShadow: '0 6px 24px rgba(0,0,0,0.4)',
        transition: 'opacity 0.12s', width: '220px', zIndex: '100',
        overflow: 'hidden',
    });
    document.body.appendChild(el);
    return el;
}

// Tooltips never take the pointer: a tooltip that did sat over the next points
// and froze on its race. Clicking a point opens the race instead (onClick).
// They stay clear of the sticky site header and hide on scroll (bound below).
function _positionTooltip(tooltipEl, chart, tooltip) {
    const minTop = (document.querySelector('.site-header')?.getBoundingClientRect().bottom || 0) + 8;
    const rect   = chart.canvas.getBoundingClientRect();
    const tipW   = tooltipEl.offsetWidth || 230;
    const caretX = rect.left + tooltip.caretX;
    const caretY = rect.top  + tooltip.caretY;
    if (caretX + tipW + 16 <= window.innerWidth) {
        // Fits to the right of the cursor - tooltip is outside the canvas, no blocking
        tooltipEl.style.left = (caretX + 16) + 'px';
        tooltipEl.style.top  = Math.max(minTop, caretY - 50) + 'px';
    } else {
        // Near right edge: go above the point so we don't sit over the canvas
        const tipH = tooltipEl.offsetHeight || 150;
        let left = Math.max(8, caretX - tipW / 2);
        if (left + tipW > window.innerWidth - 8) left = window.innerWidth - tipW - 8;
        tooltipEl.style.left = left + 'px';
        tooltipEl.style.top  = Math.max(minTop, caretY - tipH - 12) + 'px';
    }
    tooltipEl.style.opacity = '1';
}

if (!window._ptdChartTipScrollBound) {
    window._ptdChartTipScrollBound = true;
    window.addEventListener('scroll', () => {
        ['ratings-chart-tooltip', 'world-ranking-tooltip', 'national-ranking-tooltip', 'pct-behind-tooltip', 'vp-tooltip']
            .forEach(id => { const el = document.getElementById(id); if (el) el.style.opacity = '0'; });
    }, { passive: true });
}

function _fillRankTooltip(tooltipEl, d, disc, rankLabel) {
    const color  = DISC_COLORS[disc];
    const label  = DISC_LABELS[disc];
    const date   = new Date(d.x).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    const isDNF  = d.status && DNF_STATUSES.has(d.status);

    const raceLink   = `<a href="/race/${d.race_id}" style="color:#fff;text-decoration:none;font-weight:700;font-size:13px;line-height:1.2;display:block" onmouseover="this.style.color='#E87722'" onmouseout="this.style.color='#fff'">${escapeHtml(d.race_name)}</a>`;
    const statusBadge = isDNF
        ? `<span style="display:inline-block;background:rgba(220,38,38,0.2);color:#f87171;font-size:10px;font-weight:700;padding:1px 5px;border-radius:3px;margin-left:6px">${d.status}</span>`
        : '';

    // Build time rows - transition shows T1+T2, others show discipline time
    let timeRows = '';
    if (!isDNF) {
        if (disc === 'transition') {
            const mkRow = (lbl, t, diff) => {
                if (!t) return '';
                const timeR = `<div style="display:flex;justify-content:space-between;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">${lbl} time</span><span style="color:#fff;font-size:13px;font-weight:600">${fmtTime(t)}</span></div>`;
                const diffR = diff == null ? '' : diff > 0
                    ? `<div style="display:flex;justify-content:space-between;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">${lbl} behind</span><span style="color:#f87171;font-size:12px;font-weight:500">${fmtDiff(diff)}</span></div>`
                    : `<div style="display:flex;justify-content:space-between;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">${lbl} behind</span><span style="color:#5eead4;font-size:12px;font-weight:500">Leader</span></div>`;
                return timeR + diffR;
            };
            timeRows = mkRow('T1', d.t1_s, d.t1_diff) + mkRow('T2', d.t2_s, d.t2_diff);
        } else if (d.time_s) {
            timeRows = `<div style="display:flex;justify-content:space-between;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">${label} time</span><span style="color:#fff;font-size:13px;font-weight:600">${fmtTime(d.time_s)}</span></div>`;
            timeRows += d.diff_s > 0
                ? `<div style="display:flex;justify-content:space-between;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">Behind leader</span><span style="color:#f87171;font-size:12px;font-weight:500">${fmtDiff(d.diff_s)}</span></div>`
                : d.diff_s != null
                    ? `<div style="display:flex;justify-content:space-between;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">Behind leader</span><span style="color:#5eead4;font-size:12px;font-weight:500">Leader</span></div>`
                    : '';
        }
    }

    tooltipEl.innerHTML = `
        <div style="padding:7px 12px;border-bottom:1px solid rgba(255,255,255,0.08)">
            <div style="margin-bottom:1px">${raceLink}</div>
            <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-size:11px;color:rgba(255,255,255,0.4)">${date}</span>
                ${statusBadge}
            </div>
        </div>
        <div style="padding:10px 12px;${timeRows ? 'border-bottom:1px solid rgba(255,255,255,0.08);' : ''}">
            <div style="font-size:22px;font-weight:800;color:${color};line-height:1">#${d.y}${fmtRankChange(d.rank_chg)}</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.4);margin-top:3px">${label} ${rankLabel}</div>
        </div>
        ${timeRows ? `<div style="padding:8px 12px;display:flex;flex-direction:column;gap:4px">${timeRows}</div>` : ''}
    `;
}

function toggleNotableResults(button, targetId) {
    const dropdown = document.getElementById(targetId);
    if (!dropdown) return;

    const expanded = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', !expanded);
    dropdown.hidden = expanded;
    button.classList.toggle('open', !expanded);
}

// Races table: Times, Ratings and Predictions views of every start in the
// career. Find, distance and result filters show every match; unfiltered it
// shows the latest 20 until Show all. While sorted by date, a divider row
// opens each year with its tally. Heats sit under their final and open from
// its "n heats" toggle.
(function initRacesTable() {
    const table = document.getElementById('races-table');
    if (!table) return;
    const TOP = 20;
    const tbody   = table.tBodies[0];
    const ths     = [...table.tHead.rows[0].cells];
    const raceTh  = ths.find(th => th.dataset.key === 'race');
    const buttons = document.querySelectorAll('.race-view-btn[data-view]');
    const chipRow = document.querySelector('.race-table-chips');
    const find    = document.getElementById('races-find');
    const dist    = document.getElementById('races-dist');
    const result  = document.getElementById('races-result');
    const more    = document.querySelector('.race-show-all');
    const norm    = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
    const chevron = '<svg class="chip-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';
    const plural  = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
    let showAll = false;

    function refresh() {
        tbody.querySelectorAll('.season-row').forEach(r => r.remove());
        const q = norm(find.value.trim());
        const d = dist ? dist.value : '';
        const res = result.value;
        const filtered = !!(q || d || res);
        const years = new Map();   // year -> tally of matching races, first visible row
        let matched = 0, total = 0, shown = 0;
        for (const row of tbody.querySelectorAll('tr.race-row')) {
            total++;
            const r = row.dataset.res;
            const ok = (!q || row.dataset.find.includes(q)) && (!d || row.dataset.dist === d)
                       && (!res || r === res || (res === 'podium' && r === 'win'));
            if (!ok) { row.classList.add('is-hidden'); continue; }
            matched++;
            const visible = filtered || showAll || matched <= TOP;
            row.classList.toggle('is-hidden', !visible);
            if (!years.has(row.dataset.year)) years.set(row.dataset.year, { races: 0, wins: 0, podiums: 0, first: null });
            const y = years.get(row.dataset.year);
            y.races++;
            if (r === 'win') y.wins++;
            if (r === 'win' || r === 'podium') y.podiums++;
            if (visible) {
                row.classList.toggle('stripe', shown++ % 2 === 1);
                y.first ??= row;
            }
        }
        // Heats show only under an open, visible final.
        for (const sub of tbody.querySelectorAll('tr.sub-race-row')) {
            const toggle = tbody.querySelector(`.sub-race-toggle[data-parent="${sub.dataset.parent}"]`);
            sub.classList.toggle('is-hidden', toggle.closest('tr').classList.contains('is-hidden')
                                              || toggle.getAttribute('aria-expanded') !== 'true');
        }
        if (raceTh.matches('.asc, .desc')) {
            for (const [year, y] of years) {
                if (!y.first) continue;
                const tr = document.createElement('tr');
                tr.className = 'season-row';
                tr.innerHTML = `<td colspan="${ths.length}"><b>${year}</b>${plural(y.races, 'race')} · ${plural(y.wins, 'win')} · ${plural(y.podiums, 'podium')}</td>`;
                y.first.before(tr);
            }
        }
        // "Latest" only while newest first; any other sort shows its top 20.
        const first = raceTh.classList.contains('desc') ? `the latest ${TOP}` : `the top ${TOP}`;
        more.hidden = filtered || total <= TOP;
        more.textContent = showAll ? `Show ${first}` : `Show all ${total} races`;
        chipRow.querySelectorAll('.sort-chip').forEach(chip => {
            chip.classList.toggle('selected', chip._th.matches('.asc, .desc'));
            chip.classList.toggle('asc', chip._th.classList.contains('asc'));
            chip.classList.toggle('desc', chip._th.classList.contains('desc'));
        });
    }

    function sortBy(th, asc) {
        tbody.querySelectorAll('.season-row').forEach(r => r.remove());
        ths.forEach(h => h.classList.remove('asc', 'desc'));
        th.classList.add(asc ? 'asc' : 'desc');
        sortTable(table, ths.indexOf(th), asc);
        refresh();
    }
    // Re-clicking flips the direction; a fresh column starts in its data-first direction.
    const clickSort = th => sortBy(th, th.classList.contains('desc') ||
        (!th.classList.contains('asc') && th.dataset.first !== 'desc'));

    // Phone chips stand in for the hidden header: Position, Date and the
    // view's columns still on screen at phone width.
    function buildChips() {
        chipRow.innerHTML = '';
        for (const th of ths) {
            const onPhone = th.classList.contains('on') && (th.classList.contains('drawer') || !th.matches('.hide-768, .hide-1024'));
            if (!th.classList.contains('sortable') || (th.classList.contains('vc') && !onPhone)) continue;
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'sort-chip';
            chip.innerHTML = th.dataset.label + chevron;
            chip._th = th;
            chip.addEventListener('click', () => clickSort(th));
            chipRow.appendChild(chip);
        }
    }

    function setView(btn) {
        const view = btn.dataset.view;
        table.dataset.view = view;
        table.querySelectorAll('.vc').forEach(c => c.classList.toggle('on', c.classList.contains('v-' + view)));
        buttons.forEach(b => {
            b.classList.toggle('active', b === btn);
            b.setAttribute('aria-pressed', b === btn ? 'true' : 'false');
        });
        document.getElementById('races-download').dataset.downloadUrl = btn.dataset.download;
        buildChips();
        // A sort on a column the new view hides falls back to newest first.
        const sorted = ths.find(th => th.matches('.asc, .desc'));
        if (sorted.classList.contains('vc') && !sorted.classList.contains('on')) sortBy(raceTh, false);
        else refresh();
    }

    ths.forEach(th => { if (th.classList.contains('sortable')) th.addEventListener('click', () => clickSort(th)); });
    buttons.forEach(b => b.addEventListener('click', () => setView(b)));
    find.addEventListener('input', refresh);
    dist?.addEventListener('change', refresh);
    result.addEventListener('change', refresh);
    more.addEventListener('click', () => { showAll = !showAll; refresh(); });
    tbody.addEventListener('click', e => {
        const heats = e.target.closest('.sub-race-toggle');
        if (heats) {
            heats.setAttribute('aria-expanded', heats.getAttribute('aria-expanded') === 'true' ? 'false' : 'true');
            refresh();
            return;
        }
        // Phone: tap a row (or its chevron) to open the rest of the view's values.
        if (e.target.closest('a, button:not(.row-toggle)')) return;
        const row = e.target.closest('tr');
        const btn = row?.querySelector('.row-toggle');
        if (!btn || !btn.offsetParent) return;
        btn.setAttribute('aria-expanded', row.classList.toggle('expanded') ? 'true' : 'false');
    });

    // Server renders newest first.
    buildChips();
    refresh();
})();

// Ratings chart ---------------------------------------------------------------
let activeDisc = 'overall';

// Helpers
function fmtTime(s) {
    if (!s || s <= 0) return null;
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.round(s % 60);
    return h > 0
        ? `${h}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`
        : `${m}:${String(sec).padStart(2,'0')}`;
}
function fmtDiff(s) {
    const t = fmtTime(s);
    return t ? `+${t}` : null;
}
// SVG chevron helpers - matches STYLE.md inline SVG convention
function _chevronSvg(up, size, col) {
    const pts = up ? '18 15 12 9 6 15' : '6 9 12 15 18 9';
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${col}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-bottom:1px"><polyline points="${pts}"></polyline></svg>`;
}
// Chevron + number, no +/- prefix (STYLE.md convention)
function fmtChangeArrow(n) {
    if (n == null) return '';
    const col = n >= 0 ? '#5eead4' : '#f87171';  // teal-300 / red-400 - legible on dark navy
    return `<span style="color:${col};font-size:11px;font-weight:600;white-space:nowrap">${_chevronSvg(n >= 0, 11, col)}${Math.abs(n)}</span>`;
}
// World rank change: positive = improved (moved up). Lower rank number = better.
function fmtRankChange(n) {
    if (n == null || n === 0) return '';
    const col = n > 0 ? '#5eead4' : '#f87171';
    return `<span style="color:${col};font-size:10px;font-weight:600;margin-left:3px;white-space:nowrap">${_chevronSvg(n > 0, 10, col)}${Math.abs(n)}</span>`;
}
const DNF_STATUSES = new Set(['DNF', 'LAP', 'NC', 'DNS', 'DQ']);

// Shared HTML tooltip element
const ratingsTooltipEl = (() => {
    const existing = document.getElementById('ratings-chart-tooltip');
    if (existing) return existing;
    const el = document.createElement('div');
    el.id = 'ratings-chart-tooltip';
    Object.assign(el.style, {
        position: 'fixed', pointerEvents: 'none', opacity: '0',
        background: '#1a1a2e', borderRadius: '10px',
        fontFamily: "'Plus Jakarta Sans', sans-serif",
        border: '1px solid rgba(255,255,255,0.1)',
        boxShadow: '0 6px 24px rgba(0,0,0,0.4)',
        transition: 'opacity 0.12s', width: '240px', zIndex: '100',
        overflow: 'hidden',
    });
    document.body.appendChild(el);
    return el;
})();

function ratingsExternalTooltip(context) {
    const { chart, tooltip } = context;
    if (tooltip.opacity === 0) { ratingsTooltipEl.style.opacity = '0'; return; }

    const d      = tooltip.dataPoints[0].raw;
    const disc   = activeDisc;
    const color  = DISC_COLORS[disc];
    const label  = disc.charAt(0).toUpperCase() + disc.slice(1);
    const date   = new Date(d.x).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    const isDNF  = d.status && DNF_STATUSES.has(d.status);
    const noTime = disc === 'transition';

    // Rating change: skip for DNF/LAP/NC
    const changeHtml = isDNF ? '' : fmtChangeArrow(d.change);

    // Status badge for non-finished results
    const statusBadge = isDNF
        ? `<span style="display:inline-block;background:rgba(220,38,38,0.2);color:#f87171;font-size:10px;font-weight:700;padding:1px 5px;border-radius:3px;margin-left:6px">${d.status}</span>`
        : '';

    // Time/diff rows: transition shows T1+T2, others show discipline time
    let timeRows = '';
    if (!isDNF) {
        if (noTime) {
            // transition disc - show T1 and T2 individually
            const mkRow = (lbl, t, diff) => {
                if (!t) return '';
                const timeR = `<div style="display:flex;justify-content:space-between;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">${lbl} time</span><span style="color:#fff;font-size:13px;font-weight:600">${fmtTime(t)}</span></div>`;
                const diffR = diff == null ? '' : diff > 0
                    ? `<div style="display:flex;justify-content:space-between;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">${lbl} behind</span><span style="color:#f87171;font-size:12px;font-weight:500">${fmtDiff(diff)}</span></div>`
                    : `<div style="display:flex;justify-content:space-between;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">${lbl} behind</span><span style="color:#5eead4;font-size:12px;font-weight:500">Leader</span></div>`;
                return timeR + diffR;
            };
            timeRows = mkRow('T1', d.t1_s, d.t1_diff) + mkRow('T2', d.t2_s, d.t2_diff);
        } else if (d.time_s) {
            timeRows = `<div style="display:flex;justify-content:space-between;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">${label} time</span><span style="color:#fff;font-size:13px;font-weight:600">${fmtTime(d.time_s)}</span></div>`;
            timeRows += d.diff_s > 0
                ? `<div style="display:flex;justify-content:space-between;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">Behind leader</span><span style="color:#f87171;font-size:12px;font-weight:500">${fmtDiff(d.diff_s)}</span></div>`
                : d.diff_s != null
                    ? `<div style="display:flex;justify-content:space-between;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">Behind leader</span><span style="color:#5eead4;font-size:12px;font-weight:500">Leader</span></div>`
                    : '';
        }
    }

    // World rank section
    const rankHtml = d.world_rank ? `
        <div style="text-align:right">
            <div style="font-size:18px;font-weight:700;color:#fff;line-height:1">#${d.world_rank}${fmtRankChange(d.world_rank_chg)}</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.4);margin-top:2px">World rank</div>
        </div>` : '';

    // Race name as link
    const raceLink = `<a href="/race/${d.race_id}" style="color:#fff;text-decoration:none;font-weight:700;font-size:13px;line-height:1.2;display:block" onmouseover="this.style.color='#E87722'" onmouseout="this.style.color='#fff'">${escapeHtml(d.race_name)}</a>`;

    ratingsTooltipEl.innerHTML = `
        <div style="padding:7px 12px;border-bottom:1px solid rgba(255,255,255,0.08)">
            <div style="margin-bottom:1px">${raceLink}</div>
            <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-size:11px;color:rgba(255,255,255,0.4)">${date}</span>
                ${statusBadge}
            </div>
        </div>
        <div style="padding:10px 12px;${timeRows ? 'border-bottom:1px solid rgba(255,255,255,0.08);' : ''}display:flex;justify-content:space-between;align-items:flex-end">
            <div>
                <div style="font-size:22px;font-weight:800;color:${color};line-height:1">${d.y} ${changeHtml}</div>
                <div style="font-size:11px;color:rgba(255,255,255,0.4);margin-top:3px">${label} rating</div>
            </div>
            ${rankHtml}
        </div>
        ${timeRows ? `<div style="padding:8px 12px;display:flex;flex-direction:column;gap:4px">${timeRows}</div>` : ''}
    `;

    _positionTooltip(ratingsTooltipEl, chart, tooltip);
}

// Rating and rank ---------------------------------------------------------------
// One chart for the rating, world rank or national rank in any discipline.
// Switching swaps the data and the y scale on the same Chart instance, so the
// line animates to its new shape. Ranks use a reversed log scale with the top
// 10 shaded. The peak (best rank) and current value are labelled.
const rankTooltipEl = _makeRankTooltipEl('world-ranking-tooltip');
const RR_STEPS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000];
const rrSeries = {
    rating:   getJSON('ratings-chart-data'),
    world:    getJSON('world-rankings-chart-data'),
    national: getJSON('national-rankings-chart-data'),
};
let rrMode = 'rating', rrChart = null;
const rrNow = getJSON('ranks-now-data');

function _rrData(mode, disc) {
    const pts = (rrSeries[mode]?.[disc] || []).filter(p => p.y != null);
    if (!pts.length) return [];
    // Hold the last value to today, as the step line does between races. A
    // rank ends on today's live rank (the Ratings table's): athletes leaving
    // the 18-month pool can move it without a race.
    const today = new Date().toISOString().slice(0, 10);
    const live = mode !== 'rating' && rrNow?.[mode]?.[disc];
    return [...pts, { ...pts[pts.length - 1], x: today, now: true, ...(live ? { y: live } : {}) }];
}

function _rrScale(mode, data) {
    if (mode === 'rating') {
        return { type: 'linear', reverse: false, min: undefined, max: undefined, beginAtZero: false,
                 grid: { color: 'rgba(0,0,0,0.05)' },
                 afterBuildTicks: s => applyNiceTicks(s),
                 ticks: { color: '#999', autoSkip: false, callback: v => v.toLocaleString('en-GB') } };
    }
    const ys = data.map(p => p.y);
    const best = Math.min(...ys), worst = Math.max(...ys);
    const top = best <= 2 ? 1 : [...RR_STEPS].reverse().find(v => v <= best);
    const bot = RR_STEPS.find(v => v >= worst * 1.15) || worst * 1.5;
    return { type: 'logarithmic', reverse: true, min: top, max: bot,
             grid: { color: 'rgba(0,0,0,0.05)' },
             afterBuildTicks: s => { s.ticks = RR_STEPS.filter(v => v >= top && v <= bot).map(v => ({ value: v })); },
             ticks: { color: '#999', autoSkip: false, callback: v => '#' + v.toLocaleString('en-GB') } };
}

// Top-10 band on rank scales, plus the peak / best and "now" labels.
const rrDecor = {
    id: 'rrDecor',
    beforeDatasetsDraw(chart) {
        const y = chart.scales.y, area = chart.chartArea, ctx = chart.ctx;
        // Only when the axis reaches above #10, so the band has height.
        if (rrMode === 'rating' || y.min >= 10) return;
        const y10 = y.getPixelForValue(10);
        ctx.save();
        ctx.fillStyle = 'rgba(232, 93, 4, 0.07)';
        ctx.fillRect(area.left, area.top, area.right - area.left, y10 - area.top);
        ctx.fillStyle = 'rgba(196, 77, 3, 0.75)';
        ctx.font = "600 11px 'Plus Jakarta Sans', sans-serif";
        // Inside the band when it fits, else just under its edge.
        ctx.fillText('Top 10', area.left + 6, y10 - area.top >= 16 ? y10 - 6 : y10 + 13);
        ctx.restore();
    },
    afterDatasetsDraw(chart) {
        if (chart.width < 480) return;
        const meta = chart.getDatasetMeta(0), data = chart.data.datasets[0].data;
        if (!data.length || !meta.data.length) return;
        const real = data.filter(p => !p.now);
        const better = rrMode === 'rating' ? (a, b) => b.y > a.y : (a, b) => b.y < a.y;
        const peak = real.reduce((a, b) => (better(a, b) ? b : a));
        const pi = data.indexOf(peak), li = data.length - 1;
        const fmt = v => rrMode === 'rating' ? v.toLocaleString('en-GB') : '#' + v.toLocaleString('en-GB');
        const ctx = chart.ctx;
        ctx.save();
        ctx.font = "600 11.5px 'Plus Jakarta Sans', sans-serif";
        ctx.lineJoin = 'round';
        const label = (text, x, y, align, color) => {
            ctx.textAlign = align;
            ctx.strokeStyle = '#fff'; ctx.lineWidth = 4; ctx.strokeText(text, x, y);
            ctx.fillStyle = color; ctx.fillText(text, x, y);
        };
        const pp = meta.data[pi], lp = meta.data[li];
        const month = _rrMonth;
        const peakText = rrMode === 'rating' ? `Peak ${fmt(peak.y)} · ${month(peak.x)}` : _rrBestText(data, peak.y);
        // Above or below the point, whichever keeps the label inside the
        // plot (a peak on the top edge would otherwise sit in the switches).
        const area = chart.chartArea;
        const yFor = (py, preferAbove) => {
            const up = py - 10, down = py + 18;
            if (preferAbove) return up - 11 < area.top ? down : up;
            return down > area.bottom - 3 ? up : down;
        };
        label(peakText, Math.max(area.left + 4, Math.min(pp.x, area.right - 4)), yFor(pp.y, rrMode === 'rating'),
              pp.x > area.left + area.width * 0.6 ? 'right' : 'left', '#1a1a2e');
        // No "now" label when the peak label already covers today: the rating
        // is still its peak, or the best rank is held "since" a date.
        if (data[li].y !== peak.y || (rrMode !== 'rating' && !peakText.includes(' since '))) {
            label(`${fmt(data[li].y)} now`, lp.x - 2, yFor(lp.y, rrMode !== 'rating'), 'right', '#6b7280');
        }
        ctx.restore();
    },
};

// "Sep 2024": fixed short months (en-GB now gives "Sept" in some browsers).
const _RR_MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const _rrMonth = x => { const d = new Date(x); return `${_RR_MONTHS[d.getMonth()]} ${d.getFullYear()}`; };

// The best rank with how long it was held, from the step line: "#1 since
// May 2024" (held now, "· first ..." if it was lost and regained), "#1 for
// 8 months · from May 2023", or "#1 for 2.2 years in total · first May 2023"
// when it was held in several spells.
function _rrBestText(data, best) {
    const month = _rrMonth;
    const spells = [];
    data.forEach((p, i) => {
        if (p.now || p.y !== best) return;
        const end = data[i + 1] ? data[i + 1].x : p.x;
        const last = spells[spells.length - 1];
        if (last && last.endIdx === i - 1) { last.end = end; last.endIdx = i; }
        else spells.push({ start: p.x, end, endIdx: i });
    });
    const days = spells.reduce((t, sp) => t + (new Date(sp.end) - new Date(sp.start)) / 864e5, 0);
    const held = days < 60 ? `${Math.max(1, Math.round(days / 7))} weeks`
               : days < 730 ? `${Math.round(days / 30.44)} months`
               : `${(days / 365.25).toFixed(1)} years`;
    const rank = '#' + best.toLocaleString('en-GB');
    // "Since" only when the last race is in the current spell; a rank regained
    // between races (the pool changing) has no start date to give.
    const lastRace = data.filter(p => !p.now).pop();
    const current = data[data.length - 1].y === best && lastRace.y === best;
    const first = month(spells[0].start);
    if (current) {
        const since = month(spells[spells.length - 1].start);
        return spells.length === 1 ? `${rank} since ${since}` : `${rank} since ${since} · first ${first}`;
    }
    return spells.length === 1 ? `${rank} for ${held} · from ${first}` : `${rank} for ${held} in total · first ${first}`;
}

function rrTooltip(context) {
    const { chart, tooltip } = context;
    const tipEl = rrMode === 'rating' ? ratingsTooltipEl : rankTooltipEl;
    const other = rrMode === 'rating' ? rankTooltipEl : ratingsTooltipEl;
    other.style.opacity = '0';
    if (tooltip.opacity === 0 || !tooltip.dataPoints.length) { tipEl.style.opacity = '0'; return; }
    if (rrMode === 'rating') { ratingsExternalTooltip(context); return; }
    _fillRankTooltip(tipEl, tooltip.dataPoints[0].raw, activeDisc, rrMode === 'world' ? 'world ranking' : 'national ranking');
    _positionTooltip(tipEl, chart, tooltip);
}

function rrRender() {
    const data = _rrData(rrMode, activeDisc);
    const hex = DISC_COLORS[activeDisc];
    const yearGap = (a, b) => (new Date(b.x) - new Date(a.x)) > 365 * 864e5;
    if (!rrChart) {
        rrChart = new Chart(document.getElementById('rr-canvas'), {
            type: 'line',
            data: { datasets: [{ data }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                animation: { duration: 600, easing: 'easeInOutCubic' },
                layout: { padding: { top: 8, right: 6 } },
                interaction: { mode: 'nearest', axis: 'x', intersect: false },
                onClick: (e, els) => {
                    const p = els.length && rrChart.data.datasets[0].data[els[0].index];
                    if (p && !p.now) location.href = '/race/' + p.race_id;
                },
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: false, external: rrTooltip, filter: item => !item.raw.now },
                },
                scales: {
                    x: { type: 'time', grid: { display: false }, ticks: { display: false } },
                    y: _rrScale(rrMode, data),
                },
            },
            plugins: [rrDecor],
        });
    } else {
        rrChart.data.datasets[0].data = data;
        rrChart.options.scales.y = _rrScale(rrMode, data);
    }
    Object.assign(rrChart.data.datasets[0], {
        borderColor: hex, backgroundColor: 'transparent', borderWidth: 2,
        stepped: true, fill: false, clip: false,
        pointRadius: ctx => (ctx.raw?.now ? 0 : 2.5), pointBackgroundColor: hex,
        pointHoverRadius: ctx => (ctx.raw?.now ? 0 : 5), pointHoverBackgroundColor: '#fff',
        pointHoverBorderColor: hex, pointHoverBorderWidth: 2,
        // Dashed over a gap of more than a year without racing.
        segment: { borderDash: ctx => (yearGap(ctx.p0.raw, ctx.p1.raw) ? [4, 4] : undefined) },
    });
    rrChart.update();
}

(function initRatingRank() {
    if (!rrSeries.rating || !document.getElementById('rr-canvas')) return;
    const press = (group, btn) => group.forEach(b => {
        b.classList.toggle('active', b === btn);
        b.setAttribute('aria-pressed', b === btn ? 'true' : 'false');
    });
    const modeBtns = [...document.querySelectorAll('#rr-mode [data-mode]')];
    const discBtns = [...document.querySelectorAll('#rr-disc [data-disc]')];
    // No national rank (no nationality pool): drop its button.
    if (!Object.values(rrSeries.national || {}).some(a => a.length)) modeBtns.find(b => b.dataset.mode === 'national').remove();
    modeBtns.forEach(b => b.addEventListener('click', () => {
        if (rrMode === b.dataset.mode) return;
        rrMode = b.dataset.mode; press(modeBtns, b); rrRender();
    }));
    discBtns.forEach(b => b.addEventListener('click', () => {
        if (activeDisc === b.dataset.disc) return;
        activeDisc = b.dataset.disc; press(discBtns, b); rrRender();
    }));
    rrRender();
})();

// Versus prediction ---------------------------------------------------------
// Predicted place (across) against actual place (down, 1st at the top), on
// linear scales, overall or per leg. The dashed diagonal is "as predicted";
// the shaded side above it is beating the prediction. Non-finishes (or legs
// with no split) sit on a DNF row underneath, as on the race page. Podium
// places take their medal colour; the two biggest beats and misses are
// ringed and labelled. Switching discipline moves the dots on the same chart.
(function initVsPrediction() {
    const all = getJSON('vp-chart-data');
    const canvas = document.getElementById('vp-canvas');
    if (!all || !canvas) return;
    const MEDAL = { 1: '#f5c842', 2: '#c8d8e0', 3: '#d4a870' };
    const tipEl = _makeRankTooltipEl('vp-tooltip');
    const ord = n => n + (n % 100 >= 11 && n % 100 <= 13 ? 'th' : { 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
    // tojson sorts the keys, so take the discipline order explicitly.
    let disc = ['overall', 'swim', 'bike', 'run'].find(d => all[d]);
    const st = {};   // the current discipline's points, scale and highlights

    function load(d) {
        const v = all[d];
        st.pts = v.points.map(p => ({ ...p, gain: p.pred - p.pos, x: p.pred, y: p.pos }));
        const max = Math.max(...st.pts.map(p => Math.max(p.x, p.y)), ...v.dnf.map(p => p.pred));
        st.step = [1, 2, 5, 10, 20].find(s => max / s <= 8) || 50;
        st.top = Math.max(st.step, Math.ceil(max / st.step) * st.step);
        // The DNF row sits a clear gap below the last place.
        st.dnfY = st.top + Math.max(1.5, st.top * 0.1);
        st.dnf = v.dnf.map(p => ({ ...p, x: p.pred, y: st.dnfY }));
        const byGain = [...st.pts].sort((a, b) => b.gain - a.gain);
        st.ringed = new Set([...byGain.slice(0, 2).filter(p => p.gain > 0), ...byGain.slice(-2).filter(p => p.gain < 0)]);
    }

    const guide = {
        id: 'vpGuide',
        beforeDatasetsDraw(chart) {
            const { ctx, chartArea: a, scales: { x, y } } = chart;
            const p = (u, v) => [x.getPixelForValue(u), y.getPixelForValue(v)];
            ctx.save();
            // Above the diagonal: placed ahead of the prediction.
            ctx.fillStyle = 'rgba(5, 150, 105, 0.06)';
            ctx.beginPath(); ctx.moveTo(...p(1, 1)); ctx.lineTo(...p(st.top, 1)); ctx.lineTo(...p(st.top, st.top)); ctx.closePath(); ctx.fill();
            ctx.strokeStyle = 'rgba(0,0,0,0.3)'; ctx.setLineDash([4, 4]);
            ctx.beginPath(); ctx.moveTo(...p(1, 1)); ctx.lineTo(...p(st.top, st.top)); ctx.stroke();
            ctx.setLineDash([]);
            if (st.dnf.length) {
                ctx.fillStyle = 'rgba(26, 26, 46, 0.05)';
                ctx.fillRect(a.left, y.getPixelForValue(st.dnfY) - 10, a.right - a.left, 20);
            }
            // Corner names, top right in the shaded triangle and bottom left
            // below the diagonal (left out on the narrowest charts).
            if (chart.width >= 380) {
                ctx.font = "600 11px 'Plus Jakarta Sans', sans-serif";
                ctx.fillStyle = 'rgba(4, 120, 87, 0.8)'; ctx.textAlign = 'right';
                ctx.fillText('Beat prediction', a.right - 6, a.top + 14);
                ctx.fillStyle = 'rgba(185, 28, 28, 0.7)'; ctx.textAlign = 'left';
                ctx.fillText('Missed', a.left + 6, y.getPixelForValue(st.top) - 8);
            }
            ctx.restore();
        },
        afterDatasetsDraw(chart) {
            const meta = chart.getDatasetMeta(0), ctx = chart.ctx, a = chart.chartArea;
            ctx.save();
            ctx.font = "600 11px 'Plus Jakarta Sans', sans-serif";
            ctx.lineJoin = 'round';
            // The corner name counts as placed, so labels steer around it.
            const cw = ctx.measureText('Beat prediction').width;
            const placed = chart.width >= 380 ? [{ x: a.right - 6 - cw, y: a.top + 14, w: cw }] : [];
            st.pts.forEach((pt, i) => {
                if (!st.ringed.has(pt) || !meta.data[i]) return;
                const el = meta.data[i];
                ctx.strokeStyle = '#1a1a2e'; ctx.lineWidth = 1.3;
                ctx.beginPath(); ctx.arc(el.x, el.y, 9, 0, Math.PI * 2); ctx.stroke();
                if (chart.width < 380) return;
                const text = `${ord(pt.pred)} → ${ord(pt.pos)}`;
                const w = ctx.measureText(text).width, h = 12;
                const right = el.x > a.left + a.width * 0.6;
                const sx = right ? el.x - 6 - w : el.x + 6;
                // Above, below, then beside the ring: the first spot that
                // stays in the plot and clears the labels already placed.
                const spots = [[sx, el.y - 13], [sx, el.y + 21], [right ? el.x - 14 - w : el.x + 14, el.y + 4]];
                const fits = ([x, y]) => x >= a.left && x + w <= a.right && y - h >= a.top && y <= a.bottom
                    && !placed.some(b => x < b.x + b.w && x + w > b.x && y - h < b.y && y > b.y - h);
                const [tx, ty] = spots.find(fits) || spots[0];
                placed.push({ x: tx, y: ty, w });
                ctx.textAlign = 'left';
                ctx.strokeStyle = '#fff'; ctx.lineWidth = 4; ctx.strokeText(text, tx, ty);
                ctx.fillStyle = '#1a1a2e'; ctx.fillText(text, tx, ty);
            });
            ctx.restore();
        },
    };

    // Short label / value rows. Times are shown but not compared: a predicted
    // time is for a typical course, so the places are the fair comparison.
    function tooltip(context) {
        const { chart, tooltip: t } = context;
        if (t.opacity === 0 || !t.dataPoints.length) { tipEl.style.opacity = '0'; return; }
        const d = t.dataPoints[0].raw;
        const row = (k, v) => `<div style="display:flex;justify-content:space-between;gap:12px;align-items:baseline"><span style="color:rgba(255,255,255,0.5);font-size:11px">${k}</span><span style="color:#fff;font-size:12.5px;font-weight:600;text-align:right">${v}</span></div>`;
        const place = (r, time) => (r ? ord(r) : '-') + (time ? `<span style="color:rgba(255,255,255,0.5);font-weight:500"> · ${time}</span>` : '');
        const result = d.status
            ? `<span style="color:#f87171">${d.status}</span>`
            : d.gain > 0 ? `<span style="color:#5eead4">${d.gain} place${d.gain === 1 ? '' : 's'} better</span>`
            : d.gain < 0 ? `<span style="color:#f87171">${-d.gain} place${d.gain === -1 ? '' : 's'} worse</span>`
            : 'As predicted';
        tipEl.innerHTML = `
            <div style="padding:7px 12px;border-bottom:1px solid rgba(255,255,255,0.08)">
                <div style="color:#fff;font-weight:700;font-size:13px;line-height:1.2">${escapeHtml(d.race)}</div>
                <div style="font-size:11px;color:rgba(255,255,255,0.4)">${d.date} · ${DISC_LABELS[disc]}</div>
            </div>
            <div style="padding:8px 12px;display:flex;flex-direction:column;gap:4px">
                ${row('Predicted', place(d.pred, d.pred_t))}
                ${row(disc === 'overall' ? 'Finished' : 'Split', d.status ? '-' : place(d.pos, d.act_t))}
                ${row('Result', result)}
                ${d.chg != null ? row('Rating', fmtChangeArrow(d.chg) || '0') : ''}
                ${d.win_pct != null ? row('Win chance', `${(d.win_pct * 100).toFixed(0)}%`) : ''}
            </div>`;
        _positionTooltip(tipEl, chart, t);
    }

    const ticks = withDnf => s => {
        const t = [{ value: 1 }];
        for (let v = st.step; v <= st.top; v += st.step) if (v > 1) t.push({ value: v });
        if (withDnf && st.dnf.length) t.push({ value: st.dnfY });
        s.ticks = t;
    };
    const scales = () => ({
        // Axes start at 1st; the dots on it overhang the edge (clip off).
        x: { min: 1, max: st.top * 1.03, grid: { color: 'rgba(0,0,0,0.05)' }, afterBuildTicks: ticks(false),
             ticks: { color: '#999', autoSkip: false },
             title: { display: true, text: 'Predicted place', color: '#6b7280', font: { size: 11, weight: '600' } } },
        y: { min: 1, max: st.dnf.length ? st.dnfY + st.top * 0.06 : st.top * 1.03, reverse: true,
             grid: { color: 'rgba(0,0,0,0.05)' }, afterBuildTicks: ticks(true),
             ticks: { color: '#999', autoSkip: false, callback: v => (v === st.dnfY ? 'DNF' : v) },
             title: { display: true, text: disc === 'overall' ? 'Finished' : `${DISC_LABELS[disc]} split place`,
                      color: '#6b7280', font: { size: 11, weight: '600' } } },
    });

    load(disc);
    const chart = new Chart(canvas, {
        type: 'scatter',
        data: { datasets: [
            { data: st.pts, clip: false,
              pointRadius: ctx => (ctx.raw?.pos <= 3 ? 5.5 : 4),
              pointHoverRadius: ctx => (ctx.raw?.pos <= 3 ? 7 : 5.5),
              pointBackgroundColor: ctx => MEDAL[ctx.raw?.pos] || 'rgba(107, 114, 128, 0.6)',
              pointBorderColor: ctx => (ctx.raw?.pos <= 3 ? 'rgba(0,0,0,0.25)' : 'transparent'),
              pointBorderWidth: 1 },
            { data: st.dnf, clip: false,
              pointRadius: 4, pointHoverRadius: 5.5, pointBackgroundColor: '#fff',
              pointBorderColor: 'rgba(107, 114, 128, 0.8)', pointBorderWidth: 1.5 },
        ] },
        options: {
            responsive: true, maintainAspectRatio: true, aspectRatio: 1,
            animation: { duration: 500, easing: 'easeInOutCubic' },
            layout: { padding: { top: 8, right: 8 } },
            interaction: { mode: 'nearest', intersect: true },
            onClick: (e, els) => {
                if (!els.length) return;
                location.href = '/race/' + chart.data.datasets[els[0].datasetIndex].data[els[0].index].race_id;
            },
            plugins: { legend: { display: false }, yearBands: false, tooltip: { enabled: false, external: tooltip } },
            scales: scales(),
        },
        plugins: [guide],
    });

    const btns = [...document.querySelectorAll('#vp-disc [data-disc]')];
    btns.forEach(btn => btn.addEventListener('click', () => {
        if (btn.dataset.disc === disc) return;
        disc = btn.dataset.disc;
        btns.forEach(b => { b.classList.toggle('active', b === btn); b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'); });
        document.querySelectorAll('.vp-score').forEach(dl => { dl.hidden = dl.dataset.disc !== disc; });
        tipEl.style.opacity = '0';
        load(disc);
        chart.data.datasets[0].data = st.pts;
        chart.data.datasets[1].data = st.dnf;
        chart.options.scales = scales();
        chart.update();
    }));
})();

// % Behind Leader chart -------------------------------------------------------
const pctBehindData = getJSON('pct-behind-chart-data');
let activePctDisc = 'overall';
let mainPctChart  = null;

const pctTooltipEl = (() => {
    const existing = document.getElementById('pct-behind-tooltip');
    if (existing) return existing;
    const el = document.createElement('div');
    el.id = 'pct-behind-tooltip';
    Object.assign(el.style, {
        position: 'fixed', pointerEvents: 'none', opacity: '0',
        background: '#1a1a2e', borderRadius: '10px',
        fontFamily: "'Plus Jakarta Sans', sans-serif",
        border: '1px solid rgba(255,255,255,0.1)',
        boxShadow: '0 6px 24px rgba(0,0,0,0.4)',
        transition: 'opacity 0.12s', width: '220px', zIndex: '100',
        overflow: 'hidden',
    });
    document.body.appendChild(el);
    return el;
})();

function pctExternalTooltip(context) {
    const { chart, tooltip } = context;
    if (tooltip.opacity === 0) { pctTooltipEl.style.opacity = '0'; return; }
    const d     = tooltip.dataPoints[0].raw;
    const color = DISC_COLORS[activePctDisc];
    const label = DISC_LABELS[activePctDisc];
    const date  = new Date(d.x).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    const raceLink = `<a href="/race/${d.race_id}" style="color:#fff;text-decoration:none;font-weight:700;font-size:13px;line-height:1.2;display:block" onmouseover="this.style.color='#E87722'" onmouseout="this.style.color='#fff'">${escapeHtml(d.race_name)}</a>`;
    const pctDisplay = d.y === 0
        ? `<span style="color:#5eead4;font-size:22px;font-weight:800;line-height:1">Leader</span>`
        : `<span style="color:${color};font-size:22px;font-weight:800;line-height:1">+${d.y.toFixed(1)}%</span>`;
    pctTooltipEl.innerHTML = `
        <div style="padding:7px 12px;border-bottom:1px solid rgba(255,255,255,0.08)">
            <div style="margin-bottom:1px">${raceLink}</div>
            <span style="font-size:11px;color:rgba(255,255,255,0.4)">${date}</span>
        </div>
        <div style="padding:10px 12px">
            ${pctDisplay}
            <div style="font-size:11px;color:rgba(255,255,255,0.4);margin-top:3px">${label} % behind leader</div>
        </div>
    `;
    _positionTooltip(pctTooltipEl, chart, tooltip);
}

function buildMainPctBehindChart(disc) {
    const canvas = document.getElementById('pct-behind-main-canvas');
    if (mainPctChart) mainPctChart.destroy();
    const hex  = DISC_COLORS[disc];
    const data = pctBehindData[disc];
    const delayPerPoint = Math.min(600 / Math.max(data.length, 1), 30);
    const prevY = (ctx) => ctx.index === 0
        ? ctx.chart.scales.y.getPixelForValue(data[0]?.y ?? 0)
        : ctx.chart.getDatasetMeta(0).data[ctx.index - 1]?.getProps(['y'], true).y;
    mainPctChart = new Chart(canvas, {
        type: 'line',
        data: {
            datasets: [{
                data,
                borderColor: hex, backgroundColor: 'transparent',
                pointBackgroundColor: hex,
                pointHoverBackgroundColor: '#fff', pointHoverBorderColor: hex, pointHoverBorderWidth: 2,
                borderWidth: 2, pointRadius: 3, pointHoverRadius: 5,
                fill: false, showLine: false, clip: false,
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: 'nearest', axis: 'x', intersect: false },
            onClick: (e, els) => { if (els.length) location.href = '/race/' + data[els[0].index].race_id; },
            animation: {
                x: { type: 'number', easing: 'linear', duration: delayPerPoint, from: NaN,
                     delay: (ctx) => { if (ctx.type !== 'data' || ctx.xStarted) return 0; ctx.xStarted = true; return ctx.index * delayPerPoint; } },
                y: { type: 'number', easing: 'linear', duration: delayPerPoint, from: prevY,
                     delay: (ctx) => { if (ctx.type !== 'data' || ctx.yStarted) return 0; ctx.yStarted = true; return ctx.index * delayPerPoint; } },
            },
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false, external: pctExternalTooltip },
            },
            scales: {
                x: { type: 'time', grid: { display: false }, ticks: { display: false } },
                y: {
                    min: 0,
                    grid: { color: 'rgba(0,0,0,0.05)' },
                    afterBuildTicks: s => applyNiceTicks(s),
                    ticks: { color: '#999', autoSkip: false, callback: v => +v.toFixed(2) + '%' },
                }
            }
        }
    });
}

function buildMiniPctBehindChart(disc) {
    const canvas = document.getElementById(`pct-behind-mini-${disc}`);
    if (!canvas) return;
    new Chart(canvas, {
        type: 'line',
        data: {
            datasets: [{
                data: pctBehindData[disc],
                borderColor: DISC_COLORS[disc], borderWidth: 1.5,
                pointRadius: 0, tension: 0, fill: false, backgroundColor: 'transparent', clip: false,
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false }, yearBands: false },
            scales: {
                x: { type: 'time', display: false },
                y: { min: 0, display: false, grid: { display: false }, border: { display: false } },
            },
            animation: false,
        }
    });
}

function switchPctBehindDisc(disc) {
    if (disc === activePctDisc) return;
    ['overall', 'swim', 'bike', 'run'].forEach(d => {
        const existing = Chart.getChart(document.getElementById(`pct-behind-mini-${d}`));
        if (existing) existing.destroy();
    });
    const card = document.getElementById('pct-behind-main-canvas').closest('.collapsible-card');
    card.querySelectorAll('.ratings-mini').forEach(el => el.classList.remove('active'));
    card.querySelector(`.ratings-mini[data-disc="${disc}"]`).classList.add('active');
    activePctDisc = disc;
    const heading = document.getElementById('pct-behind-section-title');
    if (heading) heading.textContent = `% Behind Leader - ${DISC_LABELS[disc]}`;
    buildMainPctBehindChart(disc);
    ['overall', 'swim', 'bike', 'run'].forEach(buildMiniPctBehindChart);
}

// Init
if (pctBehindData) {
    buildMainPctBehindChart('overall');
    ['overall', 'swim', 'bike', 'run'].forEach(buildMiniPctBehindChart);
}

// Expose functions referenced from inline HTML onclick attributes. The IIFE
// wrap above makes these locally scoped, so we hoist them back onto window.
window.switchPctBehindDisc = switchPctBehindDisc;
window.toggleNotableResults = toggleNotableResults;

})(); // end IIFE
