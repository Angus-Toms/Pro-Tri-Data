let selectedAthletes = {
    athlete1: null,
    athlete2: null
};

// Debounce function for search
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Initialize search for both search boxes
function initSearch(searchId, resultsId, selectedId, athleteKey) {
    const searchInput = document.getElementById(searchId);
    const resultsDiv = document.getElementById(resultsId);
    const selectedDiv = document.getElementById(selectedId);

    const performSearch = debounce(async (query) => {
        if (query.length < 2) {
            resultsDiv.classList.remove('active');
            return;
        }

        try {
            const response = await fetch(`/compare/search?q=${encodeURIComponent(query)}`);
            const data = await response.json();

            if (data && data.length > 0) {
                resultsDiv.innerHTML = data.map(athlete => `
                    <div class="search-result-item" 
                            data-id="${athlete.athlete_id}" 
                            data-name="${athlete.name}" 
                            data-country="${athlete.country}"
                            data-country-alpha3="${athlete.country_alpha3}"
                            data-yob="${athlete.year_of_birth || ''}">
                        <span>${athlete.country}</span>
                        <strong>${athlete.name}</strong>
                        ${athlete.year_of_birth ? `<span style="color: var(--text-light);">(${athlete.year_of_birth})</span>` : ''}
                    </div>
                `).join('');
                resultsDiv.classList.add('active');

                // Add click handlers
                resultsDiv.querySelectorAll('.search-result-item').forEach(item => {
                    item.addEventListener('click', () => {
                        selectAthlete(athleteKey, {
                            id: parseInt(item.dataset.id),
                            name: item.dataset.name,
                            country: item.dataset.country,
                            country_alpha3: item.dataset.countryAlpha3,
                            year_of_birth: item.dataset.yob
                        }, searchInput, resultsDiv, selectedDiv);
                    });
                });
            } else {
                resultsDiv.innerHTML = '<div class="search-result-item">No athletes found</div>';
                resultsDiv.classList.add('active');
            }
        } catch (error) {
            console.error('Search error:', error);
        }
    }, 300);

    searchInput.addEventListener('input', (e) => {
        performSearch(e.target.value);
    });

    // Close results when clicking outside
    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !resultsDiv.contains(e.target)) {
            resultsDiv.classList.remove('active');
        }
    });
}

function selectAthlete(athleteKey, athlete, searchInput, resultsDiv, selectedDiv) {
    selectedAthletes[athleteKey] = athlete;
    
    searchInput.value = athlete.name;
    resultsDiv.classList.remove('active');
    
    selectedDiv.innerHTML = `
        <div class="selected-athlete-name">${athlete.country} ${athlete.name}</div>
        <div class="selected-athlete-info">
            ${athlete.year_of_birth ? `Born: ${athlete.year_of_birth}` : ''}
        </div>
    `;
    selectedDiv.classList.add('active');

    updateCompareButton();
}

function updateCompareButton() {
    const btn = document.getElementById('compareBtn');
    btn.disabled = !(selectedAthletes.athlete1 && selectedAthletes.athlete2);
}

function showError(message) {
    const errorDiv = document.getElementById('errorMsg');
    errorDiv.textContent = message;
    errorDiv.classList.add('active');
    setTimeout(() => {
        errorDiv.classList.remove('active');
    }, 5000);
}

async function performComparison() {
    const loadingDiv = document.getElementById('loading');
    const resultsDiv = document.getElementById('comparisonResults');
    
    loadingDiv.classList.add('active');
    resultsDiv.classList.remove('active');

    try {
        const response = await fetch(
            `/compare/${selectedAthletes.athlete1.id}/${selectedAthletes.athlete2.id}`
        );
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Comparison failed');
        }

        // Get the HTML content directly from the server
        const html = await response.text();
        resultsDiv.innerHTML = html;
        resultsDiv.classList.add('active');
    } catch (error) {
        showError(error.message);
    } finally {
        loadingDiv.classList.remove('active');
    }
}

// Initialize
initSearch('search1', 'results1', 'selected1', 'athlete1');
initSearch('search2', 'results2', 'selected2', 'athlete2');

document.getElementById('compareBtn').addEventListener('click', performComparison);