// Race page share dialog: builds a /share/card.png request from the form,
// previews it, and downloads the result.
(function () {
    const dlg = document.getElementById('share-dialog');
    if (!dlg) return;
    const raceId   = dlg.dataset.raceId;
    const img      = document.getElementById('share-img');
    const dl       = document.getElementById('share-download');
    const athField = document.getElementById('share-athlete-field');
    const athSel   = document.getElementById('share-athlete');
    const photoField = document.getElementById('share-photo-field');
    const photoIn  = document.getElementById('share-photo');
    const form     = dlg.querySelector('form');
    let blobUrl = null, seq = 0;

    function state() {
        const d = form.elements.design.value;
        const [mode, ink] = form.elements.style.value.split(':');
        const subject = form.querySelector(`input[name=design][value="${d}"]`).dataset.subject;
        return { design: d, mode, ink, subject, athlete: athSel.value };
    }

    async function refresh() {
        const s = state();
        athField.hidden = s.subject !== 'athlete';
        photoField.hidden = s.mode !== 'photo';
        const q = new URLSearchParams({ race: raceId, design: s.design, ink: s.ink });
        if (s.subject === 'athlete') q.set('athlete', s.athlete);
        const my = ++seq;
        dl.disabled = true;
        img.classList.add('loading');
        let res;
        if (s.mode === 'photo') {
            if (!photoIn.files[0]) { img.removeAttribute('src'); img.classList.remove('loading'); return; }
            const fd = new FormData(); fd.append('photo', photoIn.files[0]);
            res = await fetch(`/share/card.png?${q}`, { method: 'POST', body: fd });
        } else {
            q.set('mode', s.mode);
            res = await fetch(`/share/card.png?${q}`);
        }
        if (my !== seq) return;
        if (!res.ok) { img.classList.remove('loading'); throw new Error(`card render failed: ${res.status}`); }
        if (blobUrl) URL.revokeObjectURL(blobUrl);
        blobUrl = URL.createObjectURL(await res.blob());
        img.src = blobUrl;
        img.classList.toggle('transparent', s.mode === 'transparent');
        img.classList.remove('loading');
        dl.disabled = false;
    }

    form.addEventListener('change', refresh);
    dl.addEventListener('click', () => {
        const s = state();
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = `ptd-${raceId}-${s.design}${s.subject === 'athlete' ? '-' + s.athlete : ''}.png`;
        a.click();
    });
    img.addEventListener('click', () => { if (blobUrl) window.open(blobUrl, '_blank'); });

    // Openers: hero link (race cards) and table-header buttons (preselect athlete + design).
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-share]');
        if (!btn) return;
        e.preventDefault();
        const athleteId = btn.dataset.share;
        if (athleteId) {
            athSel.value = athleteId;
            const design = btn.dataset.shareDesign;
            (form.querySelector(`input[name=design][value="${design}"]`)
                || form.querySelector('input[name=design][data-subject=athlete]')).checked = true;
        } else {
            form.querySelector('input[name=design][data-subject=race]').checked = true;
        }
        dlg.showModal();
        refresh();
    });
})();
