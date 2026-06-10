// User-state hydration. Pages render anonymously and correct themselves from
// /me, cached in sessionStorage for a few minutes.

window.ptdUser = (function () {
    const KEY = 'ptd_me';
    const TTL_MS = 5 * 60 * 1000;
    let promise = null;

    function load() {
        if (promise) return promise;
        const cached = sessionStorage.getItem(KEY);
        if (cached) {
            const { t, me } = JSON.parse(cached);
            if (Date.now() - t < TTL_MS) {
                promise = Promise.resolve(me);
                return promise;
            }
        }
        promise = fetch('/me')
            .then(r => r.ok ? r.json() : null)
            .then(me => {
                sessionStorage.setItem(KEY, JSON.stringify({ t: Date.now(), me }));
                return me;
            });
        return promise;
    }

    function invalidate() {
        sessionStorage.removeItem(KEY);
        promise = null;
    }

    return { load, invalidate };
})();

// --- Follow buttons ---------------------------------------------------------
// Neutral server render; state corrected from /me. Call again after swapping
// in new DOM (e.g. the race page's switchRace).
function initFollowButtons(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-follow-kind]').forEach(btn => {
        if (btn.dataset.followInit) return;
        btn.dataset.followInit = '1';
        btn.addEventListener('click', (e) => {
            // Buttons can sit inside card links (leaderboard); don't navigate.
            e.preventDefault();
            e.stopPropagation();
            handleFollowClick(btn);
        });
    });
    window.ptdUser.load().then(me => {
        if (me) syncFollowButtons(me, scope);
    });
}

function setFollowState(btn, following) {
    btn.classList.toggle('following', following);
    btn.setAttribute('aria-pressed', String(following));
    const label = btn.querySelector('.follow-label');
    if (label) label.textContent = following ? 'Following' : 'Follow';
}

function syncFollowButtons(me, root) {
    (root || document).querySelectorAll('[data-follow-kind]').forEach(btn => {
        const ids = btn.dataset.followKind === 'athlete' ? me.follows.athletes : me.follows.races;
        setFollowState(btn, ids.includes(Number(btn.dataset.followId)));
    });
}

async function handleFollowClick(btn) {
    const me = await window.ptdUser.load();
    if (!me) {
        location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
        return;
    }
    const res = await fetch('/follow', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: btn.dataset.followKind, ref_id: Number(btn.dataset.followId) }),
    });
    if (!res.ok) return;
    const { following } = await res.json();
    setFollowState(btn, following);
    window.ptdUser.invalidate();
}

// --- Race comments ------------------------------------------------------
// The race page renders an empty #race-comments host (past races only);
// the partial is fetched here so race HTML never contains user state.
function initComments() {
    const host = document.getElementById('race-comments');
    if (!host || host.dataset.commentsInit) return;
    host.dataset.commentsInit = '1';
    loadComments(host, 0);
}

async function loadComments(host, offset) {
    const res = await fetch(`/race/${host.dataset.raceId}/comments?offset=${offset}`);
    if (!res.ok) return;
    host.innerHTML = await res.text();
    hydrateComments(host);
}

function hydrateComments(host) {
    const card = host.querySelector('[data-comments]');
    if (!card) return;
    const raceId = card.dataset.raceId;

    window.ptdUser.load().then(me => {
        const form = card.querySelector('[data-comment-form]');
        const cta = card.querySelector('[data-comment-login]');
        if (me) {
            if (form) form.hidden = false;
        } else if (cta) {
            cta.hidden = false;
            const link = cta.querySelector('a');
            if (link) link.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
        }
        card.querySelectorAll('.comment').forEach(el => {
            if (!me) return;
            const own = Number(el.dataset.authorId) === me.user_id;
            const del = el.querySelector('[data-comment-delete]');
            const rep = el.querySelector('[data-comment-report]');
            if (del && (own || me.is_admin)) del.hidden = false;
            if (rep && !own) rep.hidden = false;
        });
    });

    const form = card.querySelector('[data-comment-form]');
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const body = form.querySelector('.comment-textarea').value;
            const res = await fetch(`/race/${raceId}/comments`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams({ body }),
            });
            host.innerHTML = await res.text();
            hydrateComments(host);
        });
    }

    card.querySelectorAll('[data-comment-delete]').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Delete this comment?')) return;
            const id = btn.closest('.comment').dataset.commentId;
            const res = await fetch(`/comments/${id}/delete`, { method: 'POST' });
            if (res.ok) loadComments(host, 0);
        });
    });

    card.querySelectorAll('[data-comment-report]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.closest('.comment').dataset.commentId;
            const res = await fetch(`/comments/${id}/report`, { method: 'POST' });
            if (res.ok) {
                btn.textContent = 'Reported';
                btn.disabled = true;
            }
        });
    });

    card.querySelectorAll('[data-comments-page]').forEach(btn => {
        btn.addEventListener('click', () => loadComments(host, Number(btn.dataset.offset)));
    });
}

// Nav account chip + feed link + follow buttons
document.addEventListener('DOMContentLoaded', () => {
    window.ptdUser.load().then(me => {
        if (!me) return;
        document.querySelectorAll('[data-account-chip]').forEach(chip => {
            chip.textContent = me.display_name;
            chip.href = '/account';
        });
        document.querySelectorAll('[data-feed-link]').forEach(l => { l.hidden = false; });
    });
    initFollowButtons();
    initComments();
});
