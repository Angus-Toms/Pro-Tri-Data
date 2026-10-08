// Home page: rankings tabs, and the personal layer for logged-in users.
// The page itself is identical for everyone (cacheable); /home/mine is a
// no-store partial injected above "This weekend" once /me says who you are.

document.querySelectorAll('[data-rank-tab]').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('[data-rank-tab]').forEach(t => t.classList.toggle('active', t === tab));
        document.querySelectorAll('[data-rank-pane]').forEach(p => { p.hidden = p.dataset.rankPane !== tab.dataset.rankTab; });
    });
});

window.ptdUser.load().then(me => {
    if (!me) return;
    document.querySelectorAll('[data-home-anon]').forEach(el => { el.hidden = true; });
    const slot = document.querySelector('[data-home-mine]');
    fetch('/home/mine').then(r => r.ok ? r.text() : '').then(html => {
        if (!html) return;
        slot.innerHTML = html;
        slot.hidden = false;
        initFollowButtons(slot);
    });
});
