// Chart.js global defaults - match site typography and colour palette
Chart.defaults.font.family = "'Plus Jakarta Sans', sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.color = '#6b7280'; // --text-light

Chart.defaults.plugins.tooltip.backgroundColor = '#1a1a2e'; // --navy
Chart.defaults.plugins.tooltip.titleColor = '#ffffff';
Chart.defaults.plugins.tooltip.bodyColor = 'rgba(255,255,255,0.7)';
Chart.defaults.plugins.tooltip.padding = { x: 10, y: 8 };
Chart.defaults.plugins.tooltip.cornerRadius = 6;
Chart.defaults.plugins.tooltip.displayColors = false;
Chart.defaults.plugins.tooltip.titleFont = { family: "'Plus Jakarta Sans', sans-serif", weight: '600', size: 12 };
Chart.defaults.plugins.tooltip.bodyFont = { family: "'Plus Jakarta Sans', sans-serif", size: 11 };

function _debounce(fn, ms) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// Sort table click listeners - safe to call multiple times after partial swaps
function initSortableListeners() {
    document.querySelectorAll('table.sortable-table').forEach(table => {
        const allHeaders = Array.from(table.querySelectorAll('th'));
        const sortableHeaders = table.querySelectorAll('th.sortable');
        sortableHeaders.forEach((header) => {
            header.addEventListener('click', () => {
                const colIndex = allHeaders.indexOf(header);
                const isAsc = header.classList.contains('asc');
                sortableHeaders.forEach(h => h.classList.remove('asc', 'desc'));
                header.classList.add(isAsc ? 'desc' : 'asc');
                sortTable(table, colIndex, !isAsc);
            });
        });
    });
}

// Start-list histograms (predicted times, current ratings) - destroys existing
// instances before recreating
function initRaceCharts() {
    const charts = [
        // Time histograms
        { id: 'overall-times-canvas', data: 'overall-time-hist-data', label: 'Overall Time', fmt: 'time' },
        { id: 'swim-times-canvas',    data: 'swim-time-hist-data',    label: 'Swim Time',    fmt: 'time' },
        { id: 'bike-times-canvas',    data: 'bike-time-hist-data',    label: 'Bike Time',    fmt: 'time' },
        { id: 'run-times-canvas',     data: 'run-time-hist-data',     label: 'Run Time',     fmt: 'time' },
        // Rating histograms
        { id: 'overall-ratings-canvas',    data: 'overall-ratings-hist-data',    label: 'Overall Rating',    fmt: 'rating' },
        { id: 'swim-ratings-canvas',       data: 'swim-ratings-hist-data',       label: 'Swim Rating',       fmt: 'rating' },
        { id: 'bike-ratings-canvas',       data: 'bike-ratings-hist-data',       label: 'Bike Rating',       fmt: 'rating' },
        { id: 'run-ratings-canvas',        data: 'run-ratings-hist-data',        label: 'Run Rating',        fmt: 'rating' },
        { id: 'transition-ratings-canvas', data: 'transition-ratings-hist-data', label: 'Transition Rating', fmt: 'rating' },
    ];

    charts.forEach(({ id, data: dataId, label, fmt }) => {
        const canvas = document.getElementById(id);
        if (!canvas) return;
        const existing = Chart.getChart(canvas);
        if (existing) existing.destroy();
        const data = getJSON(dataId);
        if (!data || !data.datasets) return;

        new Chart(canvas, {
            type: 'bar',
            data,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                parsing: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        mode: 'index',
                        callbacks: {
                            title: ctx => ctx[0].raw.label,
                            label: ctx => `Athletes: ${ctx.raw.y}`,
                        }
                    }
                },
                scales: {
                    x: {
                        beginAtZero: false,
                        type: 'linear',
                        title: { display: true, text: label },
                        ticks: fmt === 'time'
                            ? { callback: v => isNaN(+v) ? v : formatTime(+v) }
                            : { stepSize: 100, callback: v => Math.round(v) }
                    },
                    y: {
                        beginAtZero: true,
                        type: 'linear',
                        title: { display: true, text: 'Number of Athletes' }
                    }
                }
            }
        });
    });
}

// ============================================================
//  ATHLETE PREDICTION
// ============================================================

// Results-table column key for each discipline a prediction can be made in
const _DISC_KEY = { overall: 't-overall', swim: 't-swim', bike: 't-bike', run: 't-run' };

function _raceCol(table, key) {
    return [...table.tHead.rows[0].cells].findIndex(th => th.dataset.key === key);
}

function _fitWLS(xs, ys, ws) {
    const W   = ws.reduce((a, b) => a + b, 0);
    const sX  = ws.reduce((s, w, i) => s + w * xs[i], 0);
    const sY  = ws.reduce((s, w, i) => s + w * ys[i], 0);
    const sXY = ws.reduce((s, w, i) => s + w * xs[i] * ys[i], 0);
    const sXX = ws.reduce((s, w, i) => s + w * xs[i] * xs[i], 0);
    const d   = W * sXX - sX * sX;
    if (!d) return null;
    const slope = (W * sXY - sX * sY) / d;
    return { slope, intercept: (sY - slope * sX) / W };
}

function initPrediction() {
    const predData = getJSON('prediction-data');
    if (!predData || predData.length < 3) return;

    // Fit a WLS model for each discipline from the race's existing data
    const RATING_KEY = { overall: 'rating',      swim: 'swim_rating', bike: 'bike_rating', run: 'run_rating' };
    const TIME_KEY   = { overall: 'time',         swim: 'swim_time',   bike: 'bike_time',   run: 'run_time'  };
    const models = {};
    for (const disc of ['overall', 'swim', 'bike', 'run']) {
        const rk = RATING_KEY[disc], tk = TIME_KEY[disc];
        const pts = predData.filter(d => d[rk] != null && d[tk] != null && d[tk] > 0);
        if (pts.length >= 3)
            models[disc] = _fitWLS(pts.map(d => d[rk]), pts.map(d => d[tk]), pts.map(d => d.w || 1));
    }

    const existingIds   = new Set(getJSON('race-athlete-ids') || []);
    const raceYear      = getJSON('race-year');
    const gender        = document.getElementById('add-prediction-btn').dataset.gender;
    const course        = document.getElementById('add-prediction-btn').dataset.course || 'short';
    const table         = document.getElementById('race-table');
    const addBtn        = document.getElementById('add-prediction-btn');
    const modal         = document.getElementById('prediction-modal');
    const backdrop      = modal.querySelector('.prediction-modal-backdrop');
    const searchInput   = document.getElementById('prediction-search-input');
    const searchResults = document.getElementById('prediction-search-results');

    const getDisc    = () => modal.querySelector('input[name="pred-disc"]:checked')?.value || 'overall';
    const openModal  = () => { modal.classList.remove('hidden'); searchInput.focus(); };
    const closeModal = () => {
        modal.classList.add('hidden');
        searchInput.value = '';
        searchResults.innerHTML = '';
        searchResults.classList.remove('active');
    };

    addBtn.addEventListener('click', openModal);
    backdrop.addEventListener('click', closeModal);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

    searchInput.addEventListener('input', _debounce(async (e) => {
        const q = e.target.value.trim();
        if (q.length < 2) { searchResults.classList.remove('active'); searchResults.innerHTML = ''; return; }
        try {
            const res      = await fetch(`/athlete-compare/search?q=${encodeURIComponent(q)}&gender=${encodeURIComponent(gender)}&course=${encodeURIComponent(course)}`);
            const data     = await res.json();
            const filtered = data.filter(a => !existingIds.has(a.athlete_id));
            _renderPredictionResults(filtered, searchResults);
            searchResults.querySelectorAll('.pred-result-item[data-id]').forEach(item => {
                item.addEventListener('click', async () => {
                    const disc = getDisc();
                    closeModal();
                    await _addPredictionRow(
                        { id: parseInt(item.dataset.id), name: item.dataset.name,
                          country_alpha3: item.dataset.alpha3, yob: item.dataset.yob },
                        models, disc, existingIds, table, raceYear
                    );
                });
            });
        } catch (err) { console.error('Prediction search failed:', err); }
    }, 300));
}

function _renderPredictionResults(athletes, container) {
    if (!athletes.length) {
        container.innerHTML = '<div class="pred-result-item pred-no-results">No matching athletes</div>';
        container.classList.add('active');
        return;
    }
    const base = window.STATIC_BASE_URL || '';
    container.innerHTML = athletes.slice(0, 8).map(a => `
        <div class="pred-result-item" data-id="${a.athlete_id}"
             data-name="${escapeHtml(a.name)}" data-alpha3="${a.country_alpha3 || ''}"
             data-yob="${a.year_of_birth || ''}">
            <img class="pred-result-avatar"
                 src="${base}athlete_imgs/128/${a.athlete_id}.webp"
                 onerror="this.src='${base}imgs/default_user.jpg'" alt="">
            <div>
                <div class="pred-result-name">${escapeHtml(a.name)}</div>
                <div class="pred-result-meta">${flagImg(a.country_alpha3, a.country_name)} ${escapeHtml(a.country_name)}</div>
            </div>
        </div>`).join('');
    container.classList.add('active');
}

function _getDiscWinnerTime(table, disc) {
    const col = _raceCol(table, _DISC_KEY[disc]);
    let min = Infinity;
    for (const row of table.tBodies[0].querySelectorAll('tr:not(.predicted-row)')) {
        const t = parseTime(row.cells[col]?.getAttribute('data-value') || '');
        if (isFinite(t) && t > 0 && t < min) min = t;
    }
    return isFinite(min) ? min : null;
}

async function _addPredictionRow(athlete, models, disc, existingIds, table, raceYear) {
    existingIds.add(athlete.id);
    const tbody = table.tBodies[0];

    const ATHLETE_RATING_KEY = { overall: 'overall_rating', swim: 'swim_rating', bike: 'bike_rating', run: 'run_rating' };
    let athleteRating = null;
    try {
        const data   = await fetch(`/athlete-compare/athlete/${athlete.id}`).then(r => r.json());
        athleteRating = data[ATHLETE_RATING_KEY[disc]];
    } catch (_) {}

    const model        = models[disc];
    const predTimeSecs = (model && athleteRating != null)
        ? Math.round(model.slope * athleteRating + model.intercept)
        : null;

    const winnerTime = _getDiscWinnerTime(table, disc);
    let gapHtml = '';
    if (predTimeSecs != null && winnerTime != null) {
        const diff = predTimeSecs - winnerTime;
        if (diff > 0)
            gapHtml = `<span class="pred-time-gap pred-behind">+${formatTime(diff)}</span>`;
        else if (diff < 0)
            gapHtml = `<span class="pred-time-gap pred-ahead">−${formatTime(-diff)}</span>`;
    }

    const label   = disc === 'overall' ? '(predicted)' : `(predicted ${disc})`;
    const age     = athlete.yob && raceYear ? `Age ${raceYear - parseInt(athlete.yob)} · ` : '';
    const timeStr = predTimeSecs != null ? formatTime(predTimeSecs) : '-';
    const timeDataVal = predTimeSecs != null ? formatTime(predTimeSecs) : '';

    const deleteSvg = `<svg viewBox="0 0 16 16" fill="currentColor" width="13" height="13" aria-hidden="true">
        <path d="M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm2.5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm3 .5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0V6z"/>
        <path fill-rule="evenodd" d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1v1zM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4H4.118zM2.5 3V2h11v1h-11z"/>
    </svg>`;

    // Predictions are in times, so show the Times view, then build a cell for
    // every column (same classes as its header) with only the predicted one filled.
    document.querySelector('.race-view-btn[data-view="times"]')?.click();
    const key = _DISC_KEY[disc];
    const cells = [...table.tHead.rows[0].cells].map(th => {
        const k = th.dataset.key;
        if (k === 'pos')
            return `<td class="position-col pred-pos-col" data-value="9999">
                <button class="pred-delete-btn" title="Remove prediction" aria-label="Remove prediction">${deleteSvg}</button></td>`;
        if (k === 'name')
            return `<td class="athlete-col" data-value="${escapeHtml(athlete.name)}">
                <span class="pred-name">${escapeHtml(athlete.name)}</span> <span class="pred-label">${label}</span> ${flagImg(athlete.country_alpha3)}
                <span class="athlete-sub">${age}${athlete.country_alpha3 || ''}</span></td>`;
        const cls = th.className.replace(/\b(sortable|asc|desc)\b/g, '').trim();
        if (k !== key) return `<td class="${cls}" data-value=""></td>`;
        return `<td class="${cls}" data-value="${timeDataVal}"><span class="cell-label">${th.dataset.label}</span>` +
               `<span class="${disc === 'overall' ? 'overall-time' : 'time-cell-main'}">${timeStr}</span>${gapHtml}</td>`;
    }).join('') + '<td class="toggle-col"></td>';

    const row = document.createElement('tr');
    row.className = 'predicted-row';
    row.dataset.athleteId = athlete.id;
    row.dataset.predDisc  = disc;
    if (predTimeSecs != null) row.dataset.predSecs = predTimeSecs;
    row.innerHTML = cells;

    // Sort by the predicted discipline, then insert before the first real
    // finisher slower in it.
    const col = _raceCol(table, key);
    const th  = table.tHead.rows[0].cells[col];
    [...table.tHead.rows[0].cells].forEach(h => h.classList.remove('asc', 'desc'));
    th.classList.add('asc');
    sortTable(table, col, true);

    let inserted = false;
    if (predTimeSecs != null) {
        for (const existing of tbody.querySelectorAll('tr:not(.predicted-row)')) {
            const posVal = parseInt(existing.cells[0]?.getAttribute('data-value'), 10);
            if (!isNaN(posVal) && posVal < 9000) {
                const t = parseTime(existing.cells[col]?.getAttribute('data-value') || '');
                if (isFinite(t) && t > 0 && predTimeSecs < t) {
                    tbody.insertBefore(row, existing); inserted = true; break;
                }
            }
        }
    }
    if (!inserted) tbody.appendChild(row);

    _renumberPredictions(table);
    // Show the whole field so the new row sits among the athletes around it.
    table.dispatchEvent(new CustomEvent('race-table:refresh', { detail: { showAll: true } }));

    row.querySelector('.pred-delete-btn').addEventListener('click', () => {
        existingIds.delete(athlete.id);
        row.remove();
        _renumberPredictions(table);
        table.dispatchEvent(new CustomEvent('race-table:refresh'));
    });

    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    row.classList.add('predicted-row-flash');
    setTimeout(() => row.classList.remove('predicted-row-flash'), 1200);
}

function _renumberPredictions(table) {
    const tbody = table.tBodies[0];
    for (const predRow of tbody.querySelectorAll('tr.predicted-row')) {
        const disc     = predRow.dataset.predDisc || 'overall';
        const col      = _raceCol(table, _DISC_KEY[disc]);
        const predSecs = parseInt(predRow.dataset.predSecs, 10);
        if (isNaN(predSecs)) continue;

        let pos = 1;
        // Real finishers faster in this discipline
        for (const row of tbody.querySelectorAll('tr:not(.predicted-row)')) {
            const t = parseTime(row.cells[col]?.getAttribute('data-value') || '');
            if (isFinite(t) && t > 0 && t < predSecs) pos++;
        }
        // Other predictions in the same discipline that are faster
        for (const other of tbody.querySelectorAll('tr.predicted-row')) {
            if (other === predRow) continue;
            if ((other.dataset.predDisc || 'overall') !== disc) continue;
            const o = parseInt(other.dataset.predSecs, 10);
            if (!isNaN(o) && o < predSecs) pos++;
        }
        predRow.cells[0].setAttribute('data-value', pos);
    }
}

// ============================================================
//  RACE TABLE
// ============================================================
// One table with several views of the same rows (Times, Positions, Ratings,
// Predictions). Each view's cells carry `vc v-<view>` and the current view's
// are marked `on`; CSS hides the rest (partials/_race_table.html). A column's
// first click sorts in its data-first direction: places and times lowest
// first, ratings and percentages highest first. The table shows the top 20
// until "Show all" or a search; predicted (added) rows always show.
const RACE_TABLE_TOP = 20;
const _CHIP_CHEVRON = '<svg class="chip-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';

function initRaceTable() {
    const table = document.getElementById('race-table');
    if (!table) return;
    const tbody   = table.tBodies[0];
    const ths     = [...table.tHead.rows[0].cells];
    const buttons = document.querySelectorAll('.race-view-btn');
    const chipRow = document.querySelector('.race-table-chips');
    const find    = document.getElementById('race-find-input');
    const count   = document.querySelector('.race-table-count');
    const more    = document.querySelector('.race-show-all');
    const norm    = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
    let showAll = false;

    function refresh() {
        const q = norm(find.value.trim());
        let shown = 0, matched = 0, total = 0;
        for (const row of tbody.rows) {
            const added = row.classList.contains('predicted-row');
            if (!added) total++;
            const match = added || !q || norm(row.dataset.name).includes(q) || row.dataset.country.toLowerCase() === q;
            if (match && !added) matched++;
            const visible = match && (added || q || showAll || matched <= RACE_TABLE_TOP);
            row.classList.toggle('is-hidden', !visible);
            if (visible) row.classList.toggle('stripe', shown++ % 2 === 1);
        }
        const limited = !q && !showAll && total > RACE_TABLE_TOP;
        count.textContent = q ? `${matched} of ${total} athletes match`
                          : limited ? `Showing ${RACE_TABLE_TOP} of ${total} athletes` : `${total} athletes`;
        more.hidden = !!q || total <= RACE_TABLE_TOP;
        more.textContent = showAll ? `Show top ${RACE_TABLE_TOP}` : `Show all ${total} athletes`;
        chipRow.querySelectorAll('.sort-chip').forEach(chip => {
            chip.classList.toggle('selected', chip._th.matches('.asc, .desc'));
            chip.classList.toggle('asc', chip._th.classList.contains('asc'));
            chip.classList.toggle('desc', chip._th.classList.contains('desc'));
        });
    }

    function sortBy(th, asc) {
        ths.forEach(h => h.classList.remove('asc', 'desc'));
        th.classList.add(asc ? 'asc' : 'desc');
        sortTable(table, ths.indexOf(th), asc);
        refresh();
    }
    // Re-clicking flips the direction; a fresh column starts in its data-first direction.
    const clickSort = th => sortBy(th, th.classList.contains('desc') ||
        (!th.classList.contains('asc') && th.dataset.first !== 'desc'));

    // Phone chips stand in for the hidden header: Position plus the view's
    // columns still on screen at phone width, on the row or in its drawer.
    function buildChips() {
        chipRow.innerHTML = '';
        for (const th of ths) {
            const onPhone = th.classList.contains('on') && (th.classList.contains('drawer') || !th.matches('.hide-768, .hide-1024'));
            if (th.dataset.key !== 'pos' && !onPhone) continue;
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'sort-chip';
            chip.innerHTML = th.dataset.label + _CHIP_CHEVRON;
            chip._th = th;
            chip.addEventListener('click', () => clickSort(th));
            chipRow.appendChild(chip);
        }
    }

    function setView(view) {
        table.dataset.view = view;
        table.querySelectorAll('.vc').forEach(c => c.classList.toggle('on', c.classList.contains('v-' + view)));
        buttons.forEach(b => {
            b.classList.toggle('active', b.dataset.view === view);
            b.setAttribute('aria-pressed', b.dataset.view === view ? 'true' : 'false');
        });
        document.querySelectorAll('.race-view-sub').forEach(p => { p.hidden = p.dataset.viewSub !== view; });
        buildChips();
        // Each view opens in its natural order: predicted order for a finished
        // race's predictions, otherwise the Pos column.
        const predicted = view === 'predictions' && ths.find(th => th.dataset.key === 'pr-pos');
        sortBy(predicted || ths[0], true);
    }

    ths.forEach(th => th.addEventListener('click', () => clickSort(th)));
    buttons.forEach(b => b.addEventListener('click', () => setView(b.dataset.view)));
    find.addEventListener('input', refresh);
    more.addEventListener('click', () => { showAll = !showAll; refresh(); });
    table.addEventListener('race-table:refresh', e => {
        if (e.detail?.showAll) showAll = true;
        refresh();
    });
    // Phone: tap a row (or its chevron) to open the rest of the view's values.
    tbody.addEventListener('click', e => {
        if (e.target.closest('a, .pred-delete-btn')) return;
        const row = e.target.closest('tr');
        const btn = row?.querySelector('.row-toggle');
        if (!btn || !btn.offsetParent) return;
        btn.setAttribute('aria-expanded', row.classList.toggle('expanded') ? 'true' : 'false');
    });

    // Server renders the default view in Pos order.
    ths[0].classList.add('asc');
    buildChips();
    refresh();
}

// ============================================================
//  RESULT CHARTS
// ============================================================
// Bike groups, split times and rating change by finishing position, under the
// results table (race-chart-data, built in race_page.py; finishers only).
// Drawn as SVG at the container's own width and redrawn when it changes, so
// text stays legible from phone to desktop.
const _SVG_NS = 'http://www.w3.org/2000/svg';

function _svg(tag, attrs, parent, text) {
    const el = document.createElementNS(_SVG_NS, tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (text != null) el.textContent = text;
    if (parent) parent.appendChild(el);
    return el;
}

function _ordinal(n) {
    const t = n % 100;
    if (t >= 11 && t <= 13) return n + 'th';
    return n + ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
}

const _gapLabel = s => s === 0 ? 'Leader' : '+' + formatTime(s);
const _signed = c => (c > 0 ? '+' : c < 0 ? '−' : '') + Math.abs(Math.round(c));

// One floating tooltip shared by every chart mark
function _chartTip(target, html) {
    let tip = document.querySelector('.race-chart-tip');
    if (!tip) {
        tip = document.createElement('div');
        tip.className = 'race-chart-tip';
        tip.hidden = true;
        document.body.appendChild(tip);
        window.addEventListener('scroll', () => { tip.hidden = true; }, { passive: true });
    }
    const move = e => {
        const r = tip.getBoundingClientRect();
        let x = e.clientX + 12, y = e.clientY + 12;
        if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 12;
        if (y + r.height > innerHeight - 8) y = e.clientY - r.height - 12;
        tip.style.left = x + 'px';
        tip.style.top = y + 'px';
    };
    target.addEventListener('pointerenter', e => { tip.innerHTML = html(); tip.hidden = false; move(e); });
    target.addEventListener('pointermove', move);
    target.addEventListener('pointerleave', () => { tip.hidden = true; });
}

// A finisher's dot: podium in gold / silver / bronze, drawn bigger with a ring
// in its own darker tone, everyone else grey. A larger transparent circle on
// top is the hover target.
function _finisherDot(svg, a, cx, cy, r, tipHtml) {
    const pod = a.pos <= 3;
    _svg('circle', { cx, cy, r: pod ? r + 1.5 : r, class: pod ? `rc-pod pod-${a.pos}` : 'rc-dot' }, svg);
    _chartTip(_svg('circle', { cx, cy, r: r + 4, class: 'rc-hit' }, svg), tipHtml);
}

function _drawGroups(chart, athletes) {
    const plot = chart.querySelector('.race-chart-plot');
    const W = plot.clientWidth;
    const pts = athletes.filter(a => a.t2_gap !== null).sort((a, b) => a.t2_gap - b.t2_gap);
    const groups = [];
    pts.forEach((a, i) => {
        if (i && a.t2_gap - pts[i - 1].t2_gap <= 10) groups[groups.length - 1].push(a);
        else groups.push([a]);
    });

    const narrow = W < 560;
    const R = narrow ? 4 : 5, step = 2 * R + 2;
    const m = { l: 10, r: 10, t: 58, b: 26 };
    const last = pts[pts.length - 1].t2_gap;
    const tick = [15, 30, 60, 120, 300, 600].find(s => last / s <= (narrow ? 4 : 8)) || 600;
    const maxX = Math.max(tick, Math.ceil(last / tick) * tick);
    const x = v => m.l + v / maxX * (W - m.l - m.r);

    // Beeswarm: a dot that would overlap one already placed stacks above it
    const placed = [];
    for (const a of pts) {
        a._x = x(a.t2_gap);
        a._lvl = 0;
        while (placed.some(p => p.lvl === a._lvl && Math.abs(p.x - a._x) < step)) a._lvl++;
        placed.push({ x: a._x, lvl: a._lvl });
    }
    const H = m.t + (Math.max(...pts.map(a => a._lvl)) + 1) * step + m.b;
    const axisY = H - m.b + 2;
    const base = axisY - R - 4;

    plot.innerHTML = '';
    const svg = _svg('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img',
                              'aria-label': 'Gap to the leader at the start of the run, by finisher' }, plot);
    for (let v = 0; v <= maxX; v += tick) {
        _svg('line', { x1: x(v), x2: x(v), y1: m.t - 4, y2: axisY, class: 'rc-grid' }, svg);
        _svg('text', { x: x(v), y: H - 6, class: 'rc-axis',
                       'text-anchor': v === 0 ? 'start' : v === maxX ? 'end' : 'middle' }, svg, _gapLabel(v));
    }
    _svg('line', { x1: m.l, x2: W - m.r, y1: axisY, y2: axisY, class: 'rc-base' }, svg);

    // Brackets over each group, labelled on the first of two lines with room
    // (no room on either: bracket only, the list below names every group). A
    // lone leader is a story too, so it gets a label.
    const rowEnd = [-Infinity, -Infinity];
    const named = [];
    groups.forEach((g, i) => {
        if (g.length < 2 && i > 0) return;
        const name = i === 0 ? (g.length > 1 ? 'Front group' : 'Solo leader')
                   : named.length === 1 ? 'Chase' : 'Group ' + (named.length + 1);
        named.push({ name, g });
        const label = g.length > 1 ? `${name} (${g.length})` : name;
        const x1 = g[0]._x - R, x2 = g[g.length - 1]._x + R;
        const w = label.length * 6.3;
        // Left-aligned on its bracket, pulled in only at the right edge
        const lx = Math.min(Math.max(x1, m.l), W - m.r - w);
        _svg('path', { d: `M${x1},${m.t - 4} V${m.t - 10} H${x2} V${m.t - 4}`, class: 'rc-bracket' }, svg);
        const row = rowEnd.findIndex(end => lx > end + 8);
        if (row < 0) return;
        rowEnd[row] = lx + w;
        _svg('text', { x: lx, y: m.t - 16 - row * 16, class: 'rc-group' }, svg, label);
    });

    // Podium last so it sits on top
    for (const a of [...pts].sort((p, q) => (p.pos <= 3) - (q.pos <= 3))) {
        _finisherDot(svg, a, a._x, base - a._lvl * step, R,
            () => `<b>${escapeHtml(a.name)}</b> · finished ${_ordinal(a.pos)}<br>Start of run: ${a.t2_gap ? '+' + formatTime(a.t2_gap) : 'leading'}`);
    }

    chart.querySelector('.race-chart-notes').innerHTML = named.map(({ name, g }) => {
        const gaps = g.length > 1 ? `${_gapLabel(g[0].t2_gap)} to ${_gapLabel(g[g.length - 1].t2_gap)}` : _gapLabel(g[0].t2_gap);
        const places = g.map(a => a.pos).sort((p, q) => p - q)
            .map(p => p <= 3 ? `<span class="pod-text pod-${p}">${p}</span>` : p).join(', ');
        return `<li><b>${name}</b> · ${g.length} · ${gaps} · finished ${places}</li>`;
    }).join('');
}

function _drawSplits(chart, athletes) {
    const plot = chart.querySelector('.race-chart-plot');
    const W = plot.clientWidth;
    const narrow = W < 560;
    const R = narrow ? 3 : 3.6, step = 2 * R + 1;
    const x0 = narrow ? 56 : 72, x1 = W - (narrow ? 10 : 110);
    const rows = [['Swim', 0], ['Bike', 1], ['Run', 2], ['Overall', 3]]
        .map(([label, i]) => ({ label, pts: athletes.filter(a => a.splits[i] > 0).map(a => ({ a, v: a.splits[i] })) }))
        .filter(r => r.pts.length >= 3);

    plot.innerHTML = '';
    const svg = _svg('svg', { width: W, role: 'img', 'aria-label': 'Swim, bike, run and overall times of every finisher' }, plot);
    let y = 6;
    for (const row of rows) {
        const vals = row.pts.map(p => p.v).sort((a, b) => a - b);
        const lo = vals[0], hi = vals[vals.length - 1];
        const x = v => x0 + (v - lo) / Math.max(hi - lo, 1) * (x1 - x0);
        // Dots that would overlap alternate above and below the centre line
        const placed = [];
        for (const p of row.pts.sort((a, b) => a.v - b.v)) {
            p.x = x(p.v);
            p.k = 0;
            while (placed.some(q => q.k === p.k && Math.abs(q.x - p.x) < step)) p.k++;
            placed.push(p);
        }
        const off = k => (k % 2 ? -1 : 1) * Math.ceil(k / 2) * step;
        const reach = Math.ceil(Math.max(...placed.map(p => p.k)) / 2) * step + R + 2;
        const cy = y + reach;
        const axisY = cy + reach + 2;
        const med = vals[Math.floor(vals.length / 2)];

        _svg('text', { x: 0, y: cy + 4, class: 'rc-label' }, svg, row.label);
        _svg('line', { x1: x0, x2: x1, y1: axisY, y2: axisY, class: 'rc-base' }, svg);
        _svg('line', { x1: x(med), x2: x(med), y1: y, y2: axisY, class: 'rc-median' }, svg);
        _svg('text', { x: x0, y: axisY + 14, class: 'rc-axis' }, svg, formatTime(lo));
        _svg('text', { x: x1, y: axisY + 14, 'text-anchor': 'end', class: 'rc-axis' }, svg, formatTime(hi));
        if (!narrow) _svg('text', { x: x1 + 14, y: cy + 4, class: 'rc-axis' }, svg, 'median ' + formatTime(med));
        for (const p of [...placed].sort((p, q) => (p.a.pos <= 3) - (q.a.pos <= 3))) {
            const rank = vals.indexOf(p.v) + 1;
            _finisherDot(svg, p.a, p.x, cy + off(p.k), R,
                () => `<b>${escapeHtml(p.a.name)}</b> · finished ${_ordinal(p.a.pos)}<br>${row.label}: ${formatTime(p.v)} (${_ordinal(rank)})`);
        }
        y = axisY + 26;
    }
    svg.setAttribute('height', y - 6);
    svg.setAttribute('viewBox', `0 0 ${W} ${y - 6}`);
}

function _drawRatings(chart, athletes) {
    const plot = chart.querySelector('.race-chart-plot');
    const W = plot.clientWidth;
    const narrow = W < 560;
    const pts = athletes.filter(a => a.chg !== null);
    const m = { l: 40, r: 12, t: 22, b: 38 };
    const H = narrow ? 260 : 340;
    const R = narrow ? 3.5 : 4.5;
    const maxPos = Math.max(...pts.map(a => a.pos));
    const lo = Math.min(0, ...pts.map(a => a.chg)), hi = Math.max(0, ...pts.map(a => a.chg));
    const tick = [5, 10, 25, 50, 100].find(s => (hi - lo) / s <= 7) || 100;
    const yLo = Math.floor(lo / tick) * tick, yHi = Math.ceil(hi / tick) * tick;
    const x = p => m.l + (p - 1) / Math.max(maxPos - 1, 1) * (W - m.l - m.r);
    const y = v => m.t + (yHi - v) / Math.max(yHi - yLo, 1) * (H - m.t - m.b);

    plot.innerHTML = '';
    const svg = _svg('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img',
                              'aria-label': 'Overall rating change against finishing position' }, plot);
    for (let v = yLo; v <= yHi; v += tick) {
        _svg('line', { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: v === 0 ? 'rc-zero' : 'rc-grid' }, svg);
        _svg('text', { x: m.l - 8, y: y(v) + 4, 'text-anchor': 'end', class: 'rc-axis' }, svg, _signed(v) || '0');
    }
    const xStep = maxPos <= 12 ? 1 : maxPos <= 30 ? 5 : 10;
    const xTicks = [1];
    for (let p = xStep; p <= maxPos; p += xStep) if (p > 1) xTicks.push(p);
    for (const p of xTicks)
        _svg('text', { x: x(p), y: H - m.b + 16, 'text-anchor': 'middle', class: 'rc-axis' }, svg, p);
    _svg('text', { x: (m.l + W - m.r) / 2, y: H - 4, 'text-anchor': 'middle', class: 'rc-axis' }, svg, 'Finishing position');

    // Stand-out performances: the three biggest gains and losses
    const byChange = [...pts].sort((a, b) => b.chg - a.chg);
    const best = byChange.filter(a => a.chg > 0).slice(0, 3);
    const worst = byChange.filter(a => a.chg < 0).slice(-3).reverse();
    const standouts = new Set([...best, ...worst]);

    const tipHtml = a => () => `<b>${escapeHtml(a.name)}</b><br>Finished ${_ordinal(a.pos)}` +
        (a.pred ? `, predicted ${_ordinal(a.pred)}` : '') + `<br>Rating change: ${_signed(a.chg) || '0'}`;
    for (const a of pts) {
        const cx = x(a.pos), cy = y(a.chg);
        _svg('circle', { cx, cy, r: R, class: a.chg >= 0 ? 'rc-up' : 'rc-down' }, svg);
        if (standouts.has(a)) _svg('circle', { cx, cy, r: R + 3.5, class: 'rc-ring' }, svg);
        _chartTip(_svg('circle', { cx, cy, r: R + 5, class: 'rc-hit' }, svg), tipHtml(a));
    }

    // Name the stand-outs on the chart where there's room: try spots around
    // the dot and keep the first inside the plot that clears every dot and the
    // labels already placed. The list under the chart names them either way.
    if (!narrow) {
        const boxes = pts.map(a => ({ l: x(a.pos) - R - 3, r: x(a.pos) + R + 3, t: y(a.chg) - R - 3, b: y(a.chg) + R + 3 }));
        for (const a of [...best, ...worst]) {
            const text = `${a.name} ${_signed(a.chg)}`;
            const w = text.length * 6.4, h = 13, cx = x(a.pos), cy = y(a.chg);
            const spots = [[cx + R + 7, cy + 4, 'start'], [cx - R - 7, cy + 4, 'end'],
                           [cx + 4, cy - R - 8, 'start'], [cx - 4, cy - R - 8, 'end'],
                           [cx + 4, cy + R + 16, 'start'], [cx - 4, cy + R + 16, 'end'],
                           [cx + 4, cy - R - 22, 'start'], [cx - 4, cy - R - 22, 'end'],
                           [cx + 4, cy + R + 30, 'start'], [cx - 4, cy + R + 30, 'end'],
                           [cx + R + 7, cy - 10, 'start'], [cx - R - 7, cy - 10, 'end'],
                           [cx + R + 7, cy + 18, 'start'], [cx - R - 7, cy + 18, 'end']];
            for (const [tx, ty, anchor] of spots) {
                const left = anchor === 'start' ? tx : tx - w;
                const box = { l: left, r: left + w, t: ty - h + 2, b: ty + 3 };
                // Labels may use the top and right margins, not the axis labels
                const inside = box.l >= m.l && box.r <= W && box.t >= 0 && box.b <= H - m.b + 2;
                if (!inside || boxes.some(o => box.l < o.r && box.r > o.l && box.t < o.b && box.b > o.t)) continue;
                boxes.push(box);
                _svg('text', { x: tx, y: ty, 'text-anchor': anchor, class: 'rc-name' }, svg, text);
                break;
            }
        }
    }

    const item = a => `<li><b>${escapeHtml(a.name)}</b> <span class="${a.chg >= 0 ? 'rating-increase' : 'rating-decrease'}">${_signed(a.chg)}</span>` +
        ` · finished ${_ordinal(a.pos)}${a.pred ? `, predicted ${_ordinal(a.pred)}` : ''}</li>`;
    chart.querySelector('.race-chart-standouts').innerHTML =
        (best.length ? `<div><h5>Biggest gains</h5><ol>${best.map(item).join('')}</ol></div>` : '') +
        (worst.length ? `<div><h5>Biggest losses</h5><ol>${worst.map(item).join('')}</ol></div>` : '');
}

const _RESULT_CHARTS = { groups: _drawGroups, splits: _drawSplits, ratings: _drawRatings };
let _resultChartsResize = false;

function initResultCharts() {
    const data = getJSON('race-chart-data');
    if (!data) return;
    // Redraw only charts whose width changed (phones fire resize on scroll as
    // the address bar shows and hides).
    document.querySelectorAll('.race-chart[data-chart]').forEach(chart => {
        const plot = chart.querySelector('.race-chart-plot');
        if (plot.clientWidth === plot._drawnWidth) return;
        plot._drawnWidth = plot.clientWidth;
        _RESULT_CHARTS[chart.dataset.chart](chart, data.athletes);
    });
    if (!_resultChartsResize) {
        _resultChartsResize = true;
        window.addEventListener('resize', _debounce(initResultCharts, 150));
    }
}

// Race-switcher pills. They're links to the sibling races so crawlers can
// follow them, but a plain click swaps the content in place instead of
// navigating. Modified clicks (new tab, new window) fall through to the
// browser. Delegated so it survives the swap switchRace() does.
document.addEventListener('click', (e) => {
    const pill = e.target.closest('a.race-pill[data-switch-race]');
    if (!pill) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault();
    switchRace(+pill.dataset.switchRace);
});

// Year-picker dropdown in the race hero breadcrumb. Event delegation so
// it survives the partial swap done by switchRace().
document.addEventListener('click', (e) => {
    const trigger = e.target.closest('.race-year-trigger');
    if (trigger) {
        const picker = trigger.closest('.race-year-picker');
        document.querySelectorAll('.race-year-picker.open').forEach(p => {
            if (p !== picker) p.classList.remove('open');
        });
        picker.classList.toggle('open');
        return;
    }
    document.querySelectorAll('.race-year-picker.open').forEach(p => {
        if (!p.contains(e.target)) p.classList.remove('open');
    });
});

// Live countdown for upcoming-race hero. Each `.race-countdown[data-race-date]`
// ticks once per second to show d/h/m/s until the race date. When the delta
// hits zero we swap in a fixed "race is today" message until the page is
// reloaded. ISO date (no time) is assumed to refer to the start of the day
// in the venue's local time — we display the user's local interpretation,
// which is close enough for at-a-glance context.
function _tickCountdown(el) {
    const iso = el.dataset.raceDate;
    if (!iso) return;
    const target = new Date(iso + 'T00:00:00').getTime();
    const now = Date.now();
    const diff = target - now;
    if (diff <= 0) {
        el.textContent = "Race is today - results will be posted as soon as they're available.";
        el.dataset.done = '1';
        return;
    }
    const d = Math.floor(diff / 86400000);
    const h = Math.floor((diff % 86400000) / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    const s = Math.floor((diff % 60000) / 1000);
    // Sub-day: drop the days segment.
    el.textContent = d > 0
        ? `${d}d ${h}h ${m}m ${s}s until race`
        : `${h}h ${m}m ${s}s until race`;
}
function _initCountdowns() {
    const els = document.querySelectorAll('.race-countdown[data-race-date]:not([data-done])');
    if (!els.length) return;
    els.forEach(_tickCountdown);
}
_initCountdowns();
setInterval(_initCountdowns, 1000);

