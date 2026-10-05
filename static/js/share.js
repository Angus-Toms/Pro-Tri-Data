// Race page share dialog: builds a /share/card request from the form,
// previews it, and downloads the result.
(function () {
    const dlg = document.getElementById('share-dialog');
    if (!dlg) return;
    const raceId   = dlg.dataset.raceId;
    const img      = document.getElementById('share-img');
    const preview  = img.parentElement;
    const dl       = document.getElementById('share-download');
    const athField = document.getElementById('share-athlete-field');
    const athSel   = document.getElementById('share-athlete');
    const photoField = document.getElementById('share-photo-field');
    const photoIn  = document.getElementById('share-photo');
    const photoName = document.getElementById('share-photo-name');
    const form     = dlg.querySelector('form');
    const MAX_PHOTO_BYTES = 30 * 1024 * 1024;
    let blobUrl = null, blobExt = 'png', seq = 0;

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
        preview.classList.add('loading');
        let res;
        if (s.mode === 'photo') {
            const file = photoIn.files[0];
            photoName.textContent = file ? file.name : 'No photo chosen';
            photoName.classList.remove('share-error');
            if (!file) { img.removeAttribute('src'); preview.classList.remove('loading'); return; }
            if (file.size > MAX_PHOTO_BYTES) {   // mirrors the server cap so the user hears it before the upload
                photoName.textContent = `${file.name} is too big (${(file.size / 1048576).toFixed(0)}MB, max 30MB). Choose a smaller photo.`;
                photoName.classList.add('share-error');
                img.removeAttribute('src'); preview.classList.remove('loading'); return;
            }
            const fd = new FormData(); fd.append('photo', photoIn.files[0]);
            res = await fetch(`/share/card?${q}`, { method: 'POST', body: fd });
        } else {
            q.set('mode', s.mode);
            res = await fetch(`/share/card?${q}`);
        }
        if (my !== seq) return;
        if (!res.ok) {
            preview.classList.remove('loading');
            if (res.status === 413) { photoName.textContent = 'Photo too big (max 30MB). Choose a smaller photo.'; photoName.classList.add('share-error'); return; }
            throw new Error(`card render failed: ${res.status}`);
        }
        if (blobUrl) URL.revokeObjectURL(blobUrl);
        const blob = await res.blob();
        blobExt = blob.type === 'image/jpeg' ? 'jpg' : 'png';
        blobUrl = URL.createObjectURL(blob);
        img.src = blobUrl;
        img.classList.toggle('transparent', s.mode === 'transparent');
        preview.classList.remove('loading');
        dl.disabled = false;
    }

    form.addEventListener('change', refresh);
    // Picking "Your photo" opens the file chooser straight away; the field's
    // own button only exists to swap the photo afterwards.
    form.addEventListener('change', (e) => {
        if (e.target.name === 'style' && e.target.value.startsWith('photo') && !photoIn.files[0]) photoIn.click();
    });
    document.getElementById('share-photo-change').addEventListener('click', () => photoIn.click());
    dl.addEventListener('click', () => {
        const s = state();
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = `ptd-${raceId}-${s.design}${s.subject === 'athlete' ? '-' + s.athlete : ''}.${blobExt}`;
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
