// Home page: tabbed cards (risers, rankings), and the personal layer for
// logged-in users. The page itself is identical for everyone (cacheable);
// /home/mine is a no-store partial injected above "This weekend" once /me
// says who you are.

// Phones open the calendar strip on the latest result, with the next race
// beside it, rather than on the oldest result off-screen to the left.
// After load, so a reload's restored scroll position doesn't override it.
window.addEventListener('load', () => {
    const strip = document.querySelector('.home-schedule');
    const latest = strip?.querySelector('a.next')?.previousElementSibling;
    if (latest && matchMedia('(max-width: 480px)').matches)
        strip.scrollLeft += latest.getBoundingClientRect().left - strip.getBoundingClientRect().left;
});

// data-tab="group:key" buttons switch the data-pane="group:key" panes of the same group.
document.querySelectorAll('[data-tab]').forEach(tab => {
    tab.addEventListener('click', () => {
        const group = tab.dataset.tab.split(':')[0];
        document.querySelectorAll(`[data-tab^="${group}:"]`).forEach(t => t.classList.toggle('active', t === tab));
        document.querySelectorAll(`[data-pane^="${group}:"]`).forEach(p => { p.hidden = p.dataset.pane !== tab.dataset.tab; });
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
