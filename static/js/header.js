// Header behavior: hamburger and the global search modal.
// Loaded at the end of <body> on every page, before utils.js; flagImg comes
// from utils.js but is only called after the user types.
(function () {
    // ---------- Hamburger ----------
    // Dropdowns are pure hover on desktop; on mobile they render expanded
    // inline inside the hamburger panel, so they need no JS.
    const toggle = document.querySelector('.nav-toggle');
    const nav = document.getElementById('main-nav');
    const setNavOpen = (open) => {
        toggle.setAttribute('aria-expanded', String(open));
        nav.classList.toggle('open', open);
    };
    toggle.addEventListener('click', (e) => {
        e.stopPropagation();
        setNavOpen(toggle.getAttribute('aria-expanded') !== 'true');
    });
    nav.addEventListener('click', (e) => {
        if (e.target.closest('a.nav-dropdown-item') || (e.target.closest('a.nav-link') && !e.target.closest('.nav-dropdown-toggle'))) {
            setNavOpen(false);
        }
    });
    document.addEventListener('click', (e) => {
        if (toggle.getAttribute('aria-expanded') === 'true' && !e.target.closest('.site-header')) setNavOpen(false);
    });
    window.addEventListener('resize', () => {
        if (window.innerWidth > 768 && toggle.getAttribute('aria-expanded') === 'true') setNavOpen(false);
    });

    // ---------- Global search modal ----------
    const modal   = document.getElementById('gs');
    const panel   = modal.querySelector('.gs-panel');
    const input   = document.getElementById('gs-input');
    const tabs    = modal.querySelectorAll('[data-gs-tab]');
    const panes   = modal.querySelectorAll('[data-gs-pane]');
    const emptyEl = modal.querySelector('[data-gs-empty]');
    const IMG     = window.STATIC_BASE_URL;
    const cache   = new Map();
    let activeTab = 'all';
    let data      = null;
    let tokens    = [];
    let timer     = 0;
    let reqToken  = 0;
    let cursor    = -1;

    const openModal = () => {
        modal.hidden = false;
        document.body.classList.add('gs-locked');
        setNavOpen(false);
        // Synchronous, inside the tap: iOS only raises the keyboard then.
        input.focus();
        input.select();
    };
    const closeModal = () => {
        modal.hidden = true;
        document.body.classList.remove('gs-locked');
    };
    document.querySelectorAll('[data-search-open]').forEach(t => t.addEventListener('click', openModal));
    modal.querySelectorAll('[data-gs-close]').forEach(c => c.addEventListener('click', closeModal));
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.hidden) { e.preventDefault(); closeModal(); }
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openModal(); }
    });

    // ---------- Formatting ----------
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const fold = (s) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    // Wrap every query word in <mark>, matching accent-insensitively like the
    // server does. Folding per character keeps match offsets on the original.
    const hl = (text) => {
        const chars = [...String(text || '')];
        let flat = '';
        const owner = [];
        chars.forEach((c, i) => { const f = fold(c); flat += f; for (let k = 0; k < f.length; k++) owner.push(i); });
        const marked = new Array(chars.length).fill(false);
        tokens.forEach(t => {
            for (let p = flat.indexOf(t); p >= 0; p = flat.indexOf(t, p + 1)) {
                for (let k = p; k < p + t.length; k++) marked[owner[k]] = true;
            }
        });
        let out = '';
        chars.forEach((c, i) => {
            if (marked[i] && !marked[i - 1]) out += '<mark>';
            out += esc(c);
            if (marked[i] && !marked[i + 1]) out += '</mark>';
        });
        return out;
    };
    const compact = (n) => n >= 1000 ? Math.floor(n / 1000) + 'k' : String(n);
    const avatar = (id, hasImg) => `${IMG}${hasImg ? `athlete_imgs/128/${id}.webp` : 'imgs/default_user_64.webp'}`;
    const span = (a, b) => b && a !== b ? `${a}-${b}` : (b || a);
    // Event names often lead with the year, which the date tile already shows.
    const noYear = (name) => String(name || '').replace(/^\d{4}\s+/, '');
    const DIST = { sprint: 'Sprint', standard: 'Standard', relay: 'Relay', middle: 'Middle', t100: 'T100', long: 'Long' };
    const dists = (list) => list.length ? `<span class="gs-dot">${list.map(d => DIST[d]).join(', ')}</span>` : '';
    const place = (venue, country) => [venue, country].filter(Boolean).map(hl).join(', ');
    const winners = (list) => list.length ? `<div class="gs-winners">${list.map(w => `
        <span class="gs-winner" title="Winner">
            <img class="gs-winner-img profile-img" src="${avatar(w.athlete_id, w.has_img)}" alt="" loading="lazy">
            <span class="gs-winner-name">${esc(w.name)}</span>${flagImg(w.country_alpha3, '')}
        </span>`).join('')}</div>` : '';
    const CHEVRON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';

    // ---------- Row renderers ----------
    const athleteRow = (a) => {
        const r = a.rank;
        let rank = '';
        if (r) {
            const what = r.ag ? 'age group' : r.course === 'long' ? 'long course' : 'short course';
            rank = r.current
                ? `<div class="gs-rank" title="World rank, ${what}"><b>#${r.rank}</b><span>${what}</span></div>`
                : `<div class="gs-rank is-past" title="Best world rank, ${what} (not raced in 18 months)"><b>#${r.rank}</b><span>best, ${what}</span></div>`;
        }
        return `
        <a class="gs-row" href="/athlete/${a.athlete_id}">
            <img class="gs-avatar profile-img" src="${avatar(a.athlete_id, a.has_img)}" alt="" loading="lazy">
            <div class="gs-main">
                <div class="gs-title">${hl(a.name)}</div>
                <div class="gs-sub">${flagImg(a.country_alpha3, a.country_full)}<span class="gs-ellip">${esc(a.country_full)}</span>${a.age ? `<span class="gs-dot">Age ${a.age}</span>` : ''}</div>
            </div>
            ${rank}
        </a>`;
    };
    const eventRow = (e) => {
        const [day, mon, yr] = e.date.split(' ');
        return `
        <a class="gs-row" href="/event/${e.event_id}">
            <div class="gs-tile gs-date${e.upcoming ? ' is-upcoming' : ''}"><b>${day}</b><span>${mon}</span><span>${yr}</span></div>
            <div class="gs-main">
                <div class="gs-title">${hl(noYear(e.name))}</div>
                <div class="gs-sub">${flagImg(e.country_alpha3, e.country)}<span class="gs-ellip">${place(e.venue, e.country)}</span>${dists(e.distances)}</div>
                ${e.upcoming ? '<div class="gs-sub"><span class="gs-next">Upcoming</span></div>' : winners(e.winners)}
            </div>
        </a>`;
    };
    // A recurring race is one row (to its directory page) with a dropdown
    // of its latest editions, each a link to that year's event.
    const groupRow = (g) => {
        const eds = g.editions_list.map(e => {
            const [day, mon, yr] = e.date.split(' ');
            const who = e.upcoming ? '<span class="gs-next">Upcoming</span>'
                : e.winners.map(w => `<span class="gs-ed-winner">${esc(w.name)}${flagImg(w.country_alpha3, '')}</span>`).join('');
            const moved = e.venue && e.venue !== g.venue ? `<span class="gs-ed-venue">${esc(e.venue)}</span>` : '';
            return `
            <a class="gs-edition" href="/event/${e.event_id}">
                <b>${yr}</b>
                <span class="gs-ed-main">${who}${moved}</span>
                <span class="gs-ed-date">${day} ${mon}</span>
            </a>`;
        }).join('');
        const all = g.editions > g.editions_list.length
            ? `<a class="gs-ed-all" href="/recurring/${encodeURIComponent(g.slug)}">All ${g.editions} editions</a>` : '';
        return `
        <div class="gs-group">
            <div class="gs-group-head">
                <a class="gs-row" href="/recurring/${encodeURIComponent(g.slug)}">
                    <div class="gs-tile"><b>${g.editions}</b><span>editions</span></div>
                    <div class="gs-main">
                        <div class="gs-title">${hl(g.name)}</div>
                        <div class="gs-sub">${flagImg(g.country_alpha3, g.country)}<span class="gs-ellip">${place(g.venue, g.country)}</span><span class="gs-dot">${span(g.first_year, g.last_year)}</span>${dists(g.distances)}</div>
                        ${g.next_date ? `<div class="gs-sub"><span class="gs-next">Next ${esc(g.next_date)}</span></div>` : winners(g.winners)}
                    </div>
                </a>
                <button type="button" class="gs-expand" data-gs-expand aria-expanded="false" aria-label="Show editions">${CHEVRON}</button>
            </div>
            <div class="gs-editions" hidden>${eds}${all}</div>
        </div>`;
    };
    const seriesRow = (s) => `
        <a class="gs-row" href="/series/${encodeURIComponent(s.slug)}">
            <div class="gs-tile"><b>${s.events}</b><span>events</span></div>
            <div class="gs-main">
                <div class="gs-title">${hl(s.name)}</div>
                <div class="gs-sub"><span>${span(s.first_year, s.last_year)}</span>${s.next_date ? `<span class="gs-next">Next ${esc(s.next_venue)}, ${esc(s.next_date)}</span>` : ''}</div>
            </div>
        </a>`;

    const setOpen = (group, open) => {
        group.classList.toggle('is-open', open);
        group.querySelector('.gs-editions').hidden = !open;
        group.querySelector('[data-gs-expand]').setAttribute('aria-expanded', String(open));
    };

    // ---------- Render ----------
    // Races: recurring races first, then one-off events (or a single year,
    // when the query names one).
    const GROUPS = {
        athletes: { label: 'Athletes', noun: 'athletes', top: 4, total: d => d.athletes_total,
                    items: d => d.athletes.map(athleteRow) },
        races:    { label: 'Races',    noun: 'races',    top: 4, total: d => d.groups_total + d.events_total,
                    items: d => d.groups.map(groupRow).concat(d.events.map(eventRow)) },
        series:   { label: 'Series',   noun: 'series',   top: 2, total: d => d.series.length,
                    items: d => d.series.map(seriesRow) },
    };

    const render = () => {
        emptyEl.hidden = !!data;
        panes.forEach(p => p.innerHTML = '');
        tabs.forEach(t => {
            const g = GROUPS[t.dataset.gsTab];
            const n = g && data ? g.total(data) : 0;
            t.querySelector('.gs-tab-count').textContent = n ? compact(n) : '';
            t.classList.toggle('is-empty', !!g && !!data && !n);
        });
        if (!data) { setActiveTab(activeTab); return; }

        const q = esc(input.value.trim());
        const rows = Object.fromEntries(Object.entries(GROUPS).map(([k, g]) => [k, g.items(data)]));

        // All: series, then races, except that a well-known athlete leads.
        // An athlete who never made the world top 100 goes last, so "kona"
        // opens on Kona, not on someone named Konami. A lone group shows in
        // full, not as a teaser.
        const r0 = data.athletes.length && data.athletes[0].rank;
        const order = r0 && !r0.ag && r0.rank <= 100 ? ['athletes', 'series', 'races'] : ['series', 'races', 'athletes'];
        const lone = order.filter(k => rows[k].length).length === 1;
        modal.querySelector('[data-gs-pane="all"]').innerHTML = order.map(k => {
            const g = GROUPS[k], total = g.total(data);
            if (!rows[k].length) return '';
            const shown = lone ? rows[k].length : g.top;
            const more = total > shown ? `<button type="button" class="gs-more" data-gs-goto="${k}">All ${compact(total)}</button>` : '';
            return `<section class="gs-section"><div class="gs-section-head"><span>${g.label}</span>${more}</div>${rows[k].slice(0, shown).join('')}</section>`;
        }).join('') || `<div class="gs-message">No matches for "${q}".</div>`;

        Object.entries(GROUPS).forEach(([k, g]) => {
            const total = g.total(data), n = rows[k].length;
            const foot = total > n ? `<div class="gs-message gs-foot">Top ${n} of ${total.toLocaleString()} ${g.noun}. Keep typing to narrow it down.</div>` : '';
            modal.querySelector(`[data-gs-pane="${k}"]`).innerHTML = n
                ? rows[k].join('') + foot
                : `<div class="gs-message">No ${g.noun} match "${q}".</div>`;
        });
        // A single recurring race opens straight onto its editions.
        if (data.groups.length === 1) modal.querySelectorAll('.gs-group').forEach(el => setOpen(el, true));
        setActiveTab(activeTab);
    };

    const setActiveTab = (name) => {
        activeTab = name;
        tabs.forEach(t => {
            const on = t.dataset.gsTab === name;
            t.classList.toggle('is-active', on);
            t.setAttribute('aria-selected', String(on));
        });
        panes.forEach(p => p.hidden = !data || p.dataset.gsPane !== name);
        modal.querySelector('.gs-results').scrollTop = 0;
        setCursor(-1);
    };
    tabs.forEach(t => t.addEventListener('click', () => setActiveTab(t.dataset.gsTab)));
    modal.addEventListener('click', (e) => {
        const go = e.target.closest('[data-gs-goto]');
        if (go) setActiveTab(go.dataset.gsGoto);
        const ex = e.target.closest('[data-gs-expand]');
        if (ex) {
            const group = ex.closest('.gs-group');
            setOpen(group, !group.classList.contains('is-open'));
        }
    });

    // ---------- Keyboard ----------
    // Arrows move through the visible rows, Enter opens one, Right/Left
    // open and close a recurring race's editions.
    const visibleRows = () => [...modal.querySelectorAll('.gs-pane:not([hidden]) :is(.gs-row, .gs-edition, .gs-ed-all)')]
        .filter(r => !r.closest('.gs-editions[hidden]'));
    const setCursor = (i) => {
        const rows = visibleRows();
        cursor = Math.max(-1, Math.min(i, rows.length - 1));
        rows.forEach((r, k) => r.classList.toggle('is-cursor', k === cursor));
        if (cursor >= 0) rows[cursor].scrollIntoView({ block: 'nearest' });
    };
    input.addEventListener('keydown', (e) => {
        const row = visibleRows()[Math.max(cursor, 0)];
        const group = cursor >= 0 && row && row.closest('.gs-group');
        if (e.key === 'ArrowDown') { e.preventDefault(); setCursor(cursor + 1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor(cursor - 1); }
        else if (e.key === 'ArrowRight' && group && !group.classList.contains('is-open')) { e.preventDefault(); setOpen(group, true); }
        else if (e.key === 'ArrowLeft' && group && group.classList.contains('is-open')) {
            e.preventDefault();
            setOpen(group, false);
            setCursor(visibleRows().indexOf(group.querySelector('.gs-row')));
        }
        else if (e.key === 'Enter' && row) { e.preventDefault(); window.location.href = row.href; }
    });

    // ---------- Fetch ----------
    const show = (q, d) => {
        tokens = fold(q).split(/\s+/).filter(Boolean);
        data = d;
        render();
    };
    const runSearch = (q) => {
        const token = ++reqToken;
        if (cache.has(q)) { panel.classList.remove('is-loading'); show(q, cache.get(q)); return; }
        panel.classList.add('is-loading');
        fetch(`/search?q=${encodeURIComponent(q)}`)
            .then(r => { if (!r.ok) throw new Error(`Search failed: ${r.status}`); return r.json(); })
            .then(d => {
                cache.set(q, d);
                if (token === reqToken) show(q, d);
            })
            .finally(() => { if (token === reqToken) panel.classList.remove('is-loading'); });
    };
    input.addEventListener('input', () => {
        const q = input.value.trim().replace(/\s+/g, ' ');
        clearTimeout(timer);
        if (q.length < 2) {
            ++reqToken;
            panel.classList.remove('is-loading');
            data = null;
            render();
            return;
        }
        timer = setTimeout(() => runSearch(q), 150);
    });
    render();
})();
