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
            // Only logged-in payloads are cached: a cached null would keep the
            // page anonymous for minutes after logging in, and the anonymous
            // /me round trip is a cookie-less 401 that costs nothing.
            if (me && Date.now() - t < TTL_MS) {
                promise = Promise.resolve(me);
                return promise;
            }
        }
        promise = fetch('/me')
            .then(r => r.ok ? r.json() : null)
            .then(me => {
                if (me) sessionStorage.setItem(KEY, JSON.stringify({ t: Date.now(), me }));
                else sessionStorage.removeItem(KEY);
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
    const lists = { athlete: me.follows.athletes, race: me.follows.races, user: me.follows.users };
    (root || document).querySelectorAll('[data-follow-kind]').forEach(btn => {
        const id = Number(btn.dataset.followId);
        // No following yourself: hide the button on your own profile and card.
        if (btn.dataset.followKind === 'user' && id === me.user_id) { btn.hidden = true; return; }
        setFollowState(btn, lists[btn.dataset.followKind].includes(id));
    });
}

// Every follower figure for this target on the page: counts beside buttons,
// profile header stats and hover cards.
function setFollowerCount(kind, id, n) {
    document.querySelectorAll(`[data-follower-count="${kind}:${id}"]`).forEach(el => {
        el.querySelector('[data-num]').textContent = n;
        el.querySelector('[data-label]').textContent = n === 1 ? 'follower' : 'followers';
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
    const { following, followers } = await res.json();
    document.querySelectorAll(`[data-follow-kind="${btn.dataset.followKind}"][data-follow-id="${btn.dataset.followId}"]`)
        .forEach(b => setFollowState(b, following));
    setFollowerCount(btn.dataset.followKind, btn.dataset.followId, followers);
    window.ptdUser.invalidate();
}

// --- Race comments ------------------------------------------------------
// The race page renders an empty #race-comments host (past races only);
// the partial is fetched here so race HTML never contains user state.
function initComments() {
    const host = document.getElementById('race-comments');
    if (!host || host.dataset.commentsInit) return;
    host.dataset.commentsInit = '1';
    // Top-level comment ids whose replies are expanded; reapplied after every render.
    host.openThreads = new Set();
    loadComments(host, 0).then(() => {
        // The section is empty until the partial lands, so a #race-comments
        // link scrolls once there is something to scroll to.
        if (location.hash === '#race-comments') host.scrollIntoView();
        flashLinkedComment();
    });
    // A notification for the race already open only changes the hash.
    window.addEventListener('hashchange', flashLinkedComment);
    document.addEventListener('click', (e) => { if (!e.target.closest('[data-popover]')) closeCommentMenus(host); });
}

// The "more" menu and the reaction picker are both small popovers.
function closeCommentMenus(host) {
    host.querySelectorAll('[data-popover-menu]').forEach(m => {
        m.hidden = true;
        m.previousElementSibling.setAttribute('aria-expanded', 'false');
    });
}

function setThreadOpen(thread, open) {
    const replies = thread.querySelector(':scope > [data-replies]');
    const toggle = thread.querySelector(':scope > .comment-row [data-replies-toggle]');
    if (!replies) return;  // no replies yet
    replies.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    const n = Number(toggle.dataset.count);
    toggle.querySelector('span').textContent = open ? 'Hide replies' : `${n} ${n === 1 ? 'reply' : 'replies'}`;
    const host = thread.closest('#race-comments');
    if (open) host.openThreads.add(thread.dataset.commentId);
    else host.openThreads.delete(thread.dataset.commentId);
}

function threadOf(comment) {
    return comment.classList.contains('comment--reply') ? comment.parentElement.closest('.comment') : comment;
}

function flashLinkedComment() {
    const target = location.hash.startsWith('#comment-') && document.querySelector(location.hash);
    if (!target) return;
    setThreadOpen(threadOf(target), true);
    target.scrollIntoView({ block: 'center' });
    target.classList.remove('comment--flash');
    void target.offsetWidth;  // restart the animation on repeat visits
    target.classList.add('comment--flash');
}

async function loadComments(host, offset) {
    const res = await fetch(`/race/${host.dataset.raceId}/comments?offset=${offset}`);
    if (!res.ok) return;
    host.innerHTML = await res.text();
    hydrateComments(host);
}

function loginRedirect() {
    location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
}

function showFormError(form, msg) {
    const el = form.querySelector('[data-form-error]');
    el.textContent = msg;
    el.className = 'comment-error';
}

function hydrateComments(host) {
    const card = host.querySelector('[data-comments]');
    if (!card) return;
    const raceId = card.dataset.raceId;
    const mainForm = card.querySelector('[data-comment-form]');
    // Reply composers are clones of the main form, taken before it is wired up.
    const replyTemplate = mainForm.cloneNode(true);

    window.ptdUser.load().then(me => {
        const cta = card.querySelector('[data-comment-login]');
        if (me) {
            mainForm.hidden = false;
        } else {
            cta.hidden = false;
            cta.querySelector('a').href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
            return;
        }
        card.querySelectorAll('.comment').forEach(el => {
            const foot = el.querySelector(':scope > .comment-row > .comment-content > .comment-foot');
            if (!foot) return;  // removed-comment placeholder
            const own = Number(el.dataset.authorId) === me.user_id;
            // Delete for own comments or admins, Report for everyone else's.
            if (own || me.is_admin) foot.querySelector('[data-comment-delete]').hidden = false;
            if (!own) foot.querySelector('[data-comment-report]').hidden = false;
            foot.querySelector('[data-comment-more]').hidden = false;
            foot.querySelector('[data-comment-reply]').hidden = false;
        });
    });

    card.querySelectorAll(':scope > .comment').forEach(thread => {
        if (host.openThreads.has(thread.dataset.commentId)) setThreadOpen(thread, true);
    });
    const closeMenus = () => closeCommentMenus(host);

    wireComposer(mainForm, host, raceId, null);

    // One delegated handler; the card is replaced wholesale on every reload.
    card.addEventListener('click', async (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        const comment = btn.closest('.comment');

        if (btn.matches('[data-comment-reply]')) {
            const slot = comment.querySelector(':scope > .comment-row > .comment-content > .reply-slot');
            if (slot.firstChild) { slot.querySelector('.comment-editor').focus(); return; }
            // One reply box at a time.
            card.querySelectorAll('.reply-slot').forEach(other => { other.innerHTML = ''; });
            const form = replyTemplate.cloneNode(true);
            form.hidden = false;
            form.classList.add('comment-form--reply');
            form.querySelector('.comment-editor').dataset.placeholder = 'Reply to ' + comment.dataset.authorName;
            form.querySelector('.comment-form-actions').innerHTML =
                '<span class="comment-hint" data-form-error></span>' +
                '<span class="comment-form-buttons">' +
                '<button type="button" class="btn-secondary btn-small" data-reply-cancel>Cancel</button>' +
                '<button type="submit" class="btn-primary btn-small">Reply</button></span>';
            slot.appendChild(form);
            wireComposer(form, host, raceId, comment.dataset.commentId);
            const editor = form.querySelector('.comment-editor');
            // Start the reply by tagging whoever is being answered, unless it's yourself.
            const me = await window.ptdUser.load();
            if (comment.dataset.authorId && Number(comment.dataset.authorId) !== me.user_id) {
                editor.append(makeChip({ kind: 'user', id: comment.dataset.authorId, label: comment.dataset.authorName }),
                              document.createTextNode('\u00a0'));
            }
            editor.focus();
            const end = document.createRange();
            end.selectNodeContents(editor);
            end.collapse(false);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(end);
        } else if (btn.matches('[data-reply-cancel]')) {
            btn.closest('form').remove();
        } else if (btn.matches('[data-replies-toggle]')) {
            setThreadOpen(comment, btn.getAttribute('aria-expanded') !== 'true');
        } else if (btn.matches('[data-react]')) {
            const me = await window.ptdUser.load();
            if (!me) { loginRedirect(); return; }
            closeMenus();
            const res = await fetch(`/comments/${comment.dataset.commentId}/react`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ kind: btn.dataset.react }),
            });
            if (!res.ok) return;
            const state = await res.json();
            // Server returns every kind in use; pills for the rest reset to empty.
            comment.querySelectorAll(':scope > .comment-row .reactions > .reaction[data-react]').forEach(pill => {
                const r = state[pill.dataset.react];
                pill.classList.toggle('mine', !!(r && r.mine));
                pill.setAttribute('aria-pressed', String(!!(r && r.mine)));
                pill.querySelector('.reaction-n').textContent = r ? r.n : '';
                if (!['up', 'down'].includes(pill.dataset.react)) pill.hidden = !r;
            });
        } else if (btn.matches('[data-popover-toggle]')) {
            const menu = btn.nextElementSibling;
            const open = menu.hidden;
            closeMenus();
            menu.hidden = !open;
            btn.setAttribute('aria-expanded', String(open));
        } else if (btn.matches('[data-comment-delete]')) {
            if (!confirm('Delete this comment?')) return;
            const res = await fetch(`/comments/${comment.dataset.commentId}/delete`, { method: 'POST' });
            if (res.ok) loadComments(host, 0);
        } else if (btn.matches('[data-comment-report]')) {
            const res = await fetch(`/comments/${comment.dataset.commentId}/report`, { method: 'POST' });
            if (res.ok) { btn.textContent = 'Reported'; btn.disabled = true; }
            closeMenus();
        } else if (btn.matches('[data-comments-page]')) {
            loadComments(host, Number(btn.dataset.offset));
        }
    });
}

function wireComposer(form, host, raceId, parentId) {
    const editor = form.querySelector('.comment-editor');
    initMentionEditor(editor, raceId);
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const body = serializeEditor(editor).trim();
        if (!body) { editor.focus(); return; }
        if (body.length > 2000) { showFormError(form, 'Comments must be 1 to 2000 characters.'); return; }
        const params = new URLSearchParams({ body });
        if (parentId) params.set('parent_id', parentId);
        const submit = form.querySelector('[type="submit"]');
        submit.disabled = true;
        const res = await fetch(`/race/${raceId}/comments`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: params,
        });
        const html = await res.text();
        submit.disabled = false;
        if (!res.ok) {
            // Keep the draft: show the error in place instead of re-rendering.
            const err = new DOMParser().parseFromString(html, 'text/html').querySelector('.comment-error');
            showFormError(form, err ? err.textContent : 'Could not post. Try again.');
            return;
        }
        if (parentId) host.openThreads.add(threadOf(form.closest('.comment')).dataset.commentId);
        host.innerHTML = html;
        hydrateComments(host);
    });
}

// --- @mentions ------------------------------------------------------------
// The comment box is contenteditable so tags render as the same chips the
// posted comment shows. Chips carry kind/id/label and serialise to
// @[Label](kind:id) tokens, which the server validates and re-labels.
const AT_ICON = '<svg class="mention-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/></svg>';
const RACE_ICON = '<svg class="mention-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 21V4"/><path d="M4 4h12l-2 4 2 4H4"/></svg>';

function escHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function serializeEditor(el) {
    let out = '';
    el.childNodes.forEach(n => {
        if (n.nodeType === Node.TEXT_NODE) out += n.textContent;
        else if (n.dataset && n.dataset.kind) out += `@[${n.dataset.label}](${n.dataset.kind}:${n.dataset.id})`;
        else if (n.nodeName === 'BR') out += '\n';
        else {
            // Block wrappers some browsers insert on Enter mean a new line.
            if (out && !out.endsWith('\n')) out += '\n';
            out += serializeEditor(n);
        }
    });
    return out.replace(/ /g, ' ');
}

function makeChip(item) {
    const chip = document.createElement('span');
    chip.className = `mention mention-${item.kind}`;
    chip.contentEditable = 'false';
    chip.dataset.kind = item.kind;
    chip.dataset.id = item.id;
    chip.dataset.label = item.label;
    if (item.kind === 'athlete') {
        chip.innerHTML = `<img class="mention-photo" src="${item.img}" alt=""><span>${escHtml(item.label)}</span>`
                       + flagImg(item.country, item.sub, 'mention-flag');
    } else {
        chip.innerHTML = `${item.kind === 'race' ? RACE_ICON : AT_ICON}<span>${escHtml(item.label)}</span>`;
    }
    return chip;
}

function initMentionEditor(editor, raceId) {
    const pop = document.createElement('div');
    pop.className = 'mention-pop';
    pop.hidden = true;
    editor.insertAdjacentElement('afterend', pop);

    let items = [], active = 0, trigger = null, timer = 0, reqToken = 0;

    function currentQuery() {
        const sel = window.getSelection();
        if (!sel.rangeCount) return null;
        const r = sel.getRangeAt(0);
        const node = r.startContainer;
        if (!r.collapsed || node.nodeType !== Node.TEXT_NODE || !editor.contains(node)) return null;
        const before = node.textContent.slice(0, r.startOffset);
        const at = before.lastIndexOf('@');
        if (at < 0 || (at > 0 && !/\s/.test(before[at - 1]))) return null;
        const q = before.slice(at + 1);
        if (q.length > 40) return null;
        return { node, start: at, end: r.startOffset, q };
    }

    function close() { pop.hidden = true; items = []; trigger = null; }

    function render() {
        if (!items.length) { close(); return; }
        pop.innerHTML = items.map((it, i) => {
            const lead = it.kind === 'athlete' ? `<img class="mention-pop-photo" src="${it.img}" alt="">`
                       : it.kind === 'race' ? RACE_ICON
                       : it.avatar;
            return `<button type="button" class="mention-pop-item${i === active ? ' active' : ''}" data-i="${i}">
                <span class="mention-pop-lead">${lead}</span>
                <span class="mention-pop-main">
                    <span class="mention-pop-label">${escHtml(it.label)}</span>
                    <span class="mention-pop-sub">${escHtml(it.sub)}</span>
                </span>
                <span class="mention-pop-kind">${it.kind === 'user' ? 'person' : it.kind}</span>
            </button>`;
        }).join('');
        pop.hidden = false;
    }

    function pick(item) {
        const { node, start, end } = trigger;
        const tail = node.splitText(end);
        node.textContent = node.textContent.slice(0, start);
        const space = document.createTextNode(' ');
        tail.parentNode.insertBefore(makeChip(item), tail);
        tail.parentNode.insertBefore(space, tail);
        const r = document.createRange();
        r.setStart(space, 1);
        r.collapse(true);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(r);
        editor.focus();
        close();
    }

    editor.addEventListener('input', () => {
        // Leftover <br> after clearing would hide the placeholder.
        if (!editor.textContent && !editor.querySelector('[data-kind]')) editor.innerHTML = '';
        clearTimeout(timer);
        const t = currentQuery();
        if (!t || t.q.length < 2) { close(); return; }
        trigger = t;
        timer = setTimeout(async () => {
            const token = ++reqToken;
            const res = await fetch(`/comments/mention-search?race_id=${raceId}&q=${encodeURIComponent(t.q)}`);
            if (!res.ok || token !== reqToken || trigger !== t) return;
            const d = await res.json();
            items = [
                ...d.users.map(u => ({ ...u, kind: 'user' })),
                ...d.athletes.map(a => ({ ...a, kind: 'athlete' })),
                ...d.races.map(r => ({ ...r, kind: 'race' })),
            ];
            active = 0;
            render();
        }, 150);
    });

    editor.addEventListener('keydown', (e) => {
        if (!pop.hidden) {
            if (e.key === 'ArrowDown')    { e.preventDefault(); active = (active + 1) % items.length; render(); return; }
            if (e.key === 'ArrowUp')      { e.preventDefault(); active = (active - 1 + items.length) % items.length; render(); return; }
            if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pick(items[active]); return; }
            if (e.key === 'Escape')       { e.preventDefault(); close(); return; }
        }
        if (e.key === 'Enter') {
            e.preventDefault();
            if (e.metaKey || e.ctrlKey) editor.closest('form').requestSubmit();
            else document.execCommand('insertLineBreak');
        }
    });

    // Plain text only, so pasted markup cannot smuggle in fake chips.
    editor.addEventListener('paste', (e) => {
        e.preventDefault();
        document.execCommand('insertText', false, e.clipboardData.getData('text/plain'));
    });

    // mousedown (not click) so the pick lands before the editor blurs
    pop.addEventListener('mousedown', (e) => {
        const btn = e.target.closest('[data-i]');
        if (!btn) return;
        e.preventDefault();
        pick(items[Number(btn.dataset.i)]);
    });
    editor.addEventListener('blur', () => setTimeout(close, 150));
}

// --- Notification bell ----------------------------------------------------
// Unread count comes with /me; the list is fetched when the panel opens, and
// opening it marks everything read.
function initNotifications(me) {
    const wrap = document.querySelector('[data-notif]');
    const btn = wrap.querySelector('[data-notif-toggle]');
    const badge = wrap.querySelector('[data-notif-badge]');
    const panel = wrap.querySelector('[data-notif-panel]');
    wrap.hidden = false;
    if (me.unread) { badge.textContent = me.unread > 9 ? '9+' : me.unread; badge.hidden = false; }

    const close = () => { panel.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
    btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!panel.hidden) { close(); return; }
        panel.hidden = false;
        btn.setAttribute('aria-expanded', 'true');
        panel.innerHTML = '<div class="notif-empty">Loading</div>';
        const notes = await fetch('/notifications').then(r => r.json());
        panel.innerHTML = notes.length ? notes.map(n => {
            const text = n.kind === 'reply'
                ? `<strong>${escHtml(n.actor)}</strong> replied to your comment on <strong>${escHtml(n.race)}</strong>`
                : `<strong>${escHtml(n.actor)}</strong> mentioned you in a comment`;
            return `<a class="notif-item${n.unread ? ' unread' : ''}" href="${n.url}">
                <span class="notif-text">${text}</span>
                <span class="notif-when">${escHtml(n.when)}</span>
            </a>`;
        }).join('') : '<div class="notif-empty">No notifications yet. Replies to your comments and tags appear here.</div>';
        if (!badge.hidden) {
            badge.hidden = true;
            await fetch('/notifications/read', { method: 'POST' });
            window.ptdUser.invalidate();
        }
    });
    panel.addEventListener('click', (e) => { if (e.target.closest('.notif-item')) close(); });
    document.addEventListener('click', (e) => { if (!wrap.contains(e.target)) close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
}

// --- Header avatar menu ------------------------------------------------------
function initUserMenu(me) {
    const wrap = document.querySelector('[data-nav-user]');
    const btn = wrap.querySelector('[data-nav-user-toggle]');
    const menu = wrap.querySelector('[data-nav-user-menu]');
    btn.innerHTML = me.avatar_version
        ? `<img src="/avatar/${me.user_id}.webp?v=${me.avatar_version}" alt="">`
        : escHtml(me.display_name[0].toUpperCase());
    if (!me.avatar_version) btn.style.background = me.avatar_tone;
    wrap.querySelector('[data-nav-user-name]').textContent = me.display_name;
    wrap.querySelector('[data-nav-user-profile]').href = `/user/${me.user_id}`;
    document.querySelector('[data-nav-login]').hidden = true;
    wrap.hidden = false;

    const close = () => { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const open = menu.hidden;
        menu.hidden = !open;
        btn.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', (e) => { if (!wrap.contains(e.target)) close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
}

// Header account state + follow buttons
document.addEventListener('DOMContentLoaded', () => {
    window.ptdUser.load().then(me => {
        if (!me) return;
        initUserMenu(me);
        initNotifications(me);
    });
    initFollowButtons();
    initComments();
});

// --- Profile hover cards ------------------------------------------------------
// Hovering a commenter's name, photo or tag shows a compact profile. Mouse only:
// on touch screens a tap just follows the link to the full profile.
(function () {
    if (!window.matchMedia('(hover: hover)').matches) return;
    const SELECTOR = 'a.comment-author, a.comment-avatar-link, a.mention-user';
    const cache = new Map();  // user id -> Promise<html | null>
    let card = null, current = null, showTimer = 0, hideTimer = 0;

    function ensureCard() {
        if (card) return;
        card = document.createElement('div');
        card.className = 'user-card';
        card.hidden = true;
        document.body.appendChild(card);
        card.addEventListener('mouseenter', () => clearTimeout(hideTimer));
        card.addEventListener('mouseleave', scheduleHide);
    }

    function hide() {
        card.hidden = true;
        current = null;
    }

    function scheduleHide() {
        clearTimeout(showTimer);
        hideTimer = setTimeout(hide, 200);
    }

    function position(anchor) {
        const r = anchor.getBoundingClientRect();
        const w = card.offsetWidth, h = card.offsetHeight;
        const left = Math.max(12, Math.min(r.left, innerWidth - w - 12));
        // Below the link, or above it when there is no room underneath.
        const top = r.bottom + 8 + h > innerHeight - 12 ? r.top - h - 8 : r.bottom + 8;
        card.style.left = `${left}px`;
        card.style.top = `${top}px`;
    }

    async function show(anchor) {
        const id = anchor.getAttribute('href').match(/^\/user\/(\d+)/)[1];
        if (!cache.has(id)) cache.set(id, fetch(`/user/${id}/card`).then(r => r.ok ? r.text() : null));
        const html = await cache.get(id);
        if (!html || current !== anchor) return;
        card.innerHTML = html;
        card.hidden = false;
        position(anchor);
        initFollowButtons(card);
    }

    document.addEventListener('mouseover', (e) => {
        const anchor = e.target.closest(SELECTOR);
        if (!anchor) return;
        ensureCard();
        clearTimeout(hideTimer);
        if (anchor === current) return;
        clearTimeout(showTimer);
        current = anchor;
        showTimer = setTimeout(() => show(anchor), 350);
    });
    document.addEventListener('mouseout', (e) => {
        const anchor = e.target.closest(SELECTOR);
        if (!anchor || anchor.contains(e.relatedTarget)) return;
        scheduleHide();
    });
    window.addEventListener('scroll', () => { if (card && !card.hidden) hide(); }, { passive: true });
})();
