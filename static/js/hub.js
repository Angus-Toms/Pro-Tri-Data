// Hub pages (/races, /athletes). A tab shows its pane and hides its group's
// others; a section link marked data-follows="<group>" points at the active
// tab's page (data-link), and takes its wording (data-label) when it has one.
document.querySelectorAll('.hub-tab').forEach(tab => tab.addEventListener('click', () => {
    const group = tab.dataset.group;
    document.querySelectorAll(`.hub-tab[data-group="${group}"]`).forEach(t => {
        t.classList.toggle('active', t === tab);
        t.setAttribute('aria-selected', t === tab);
        document.querySelector(`[data-pane="${t.dataset.tab}"]`).hidden = t !== tab;
    });
    const link = document.querySelector(`[data-follows="${group}"]`);
    if (link) {
        link.href = tab.dataset.link;
        if (tab.dataset.label) link.textContent = tab.dataset.label;
    }
}));
