// Odometer counter: each digit is a column of 0-9 (twice over) ending in the target
// digit, and the column rolls up so the target lands in a one-digit window.
// Digits settle left to right, each rolling slightly longer than the one before.
function animateCounter(element) {
    const chars = parseInt(element.getAttribute('data-target')).toLocaleString().split('');
    element.innerHTML = '';
    const strips = [];
    chars.forEach(c => {
        if (!/\d/.test(c)) {
            element.appendChild(document.createTextNode(c));
            return;
        }
        const cell = document.createElement('span');
        cell.className = 'odo-cell';
        const strip = document.createElement('span');
        strip.className = 'odo-strip';
        let html = '';
        for (let l = 0; l < 2; l++) for (let d = 0; d < 10; d++) html += `<span>${d}</span>`;
        strip.innerHTML = html + `<span>${c}</span>`;
        cell.appendChild(strip);
        element.appendChild(cell);
        strips.push(strip);
    });
    // Force layout so the strips start at 0 before the transition is applied
    element.offsetHeight;
    strips.forEach((strip, i) => {
        strip.style.transition = `transform ${1500 + i * 140}ms cubic-bezier(.16,1,.3,1) ${i * 60}ms`;
        strip.style.transform = 'translateY(-20em)';
    });
}

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        // Stagger the stats slightly so they don't all move in lockstep
        entry.target.querySelectorAll('.stat-counter').forEach((counter, i) => {
            setTimeout(() => animateCounter(counter), i * 120);
        });
        observer.unobserve(entry.target);
    });
}, { threshold: 0.5 });

const hero = document.querySelector('.home-hero');
if (hero) {
    observer.observe(hero);
}
