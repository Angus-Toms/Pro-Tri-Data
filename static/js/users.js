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
});
