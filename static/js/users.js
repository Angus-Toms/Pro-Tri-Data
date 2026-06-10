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

// Nav account chip + feed link
document.addEventListener('DOMContentLoaded', () => {
    window.ptdUser.load().then(me => {
        if (!me) return;
        document.querySelectorAll('[data-account-chip]').forEach(chip => {
            chip.textContent = me.display_name;
            chip.href = '/account';
        });
        document.querySelectorAll('[data-feed-link]').forEach(l => { l.hidden = false; });
    });
});
