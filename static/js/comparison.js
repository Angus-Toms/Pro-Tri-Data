let selectedAthletes = {
    athlete1: null,
    athlete2: null
};
let comparisonGraphsLoaded = false;

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
    const searchWrapper = searchInput.closest('.search-input-wrapper');

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
                        data-country-emoji="${athlete.country_emoji}"
                        data-country-name="${athlete.country_name}"
                        data-country-alpha3="${athlete.country_alpha3}"
                        data-yob="${athlete.year_of_birth || ''}">
                        <div class="result-info">
                            <div class="result-name">${escapeHtml(athlete.name)}</div>
                            <div class="result-meta">
                                ${athlete.country_emoji} ${escapeHtml(athlete.country_alpha3)}
                                ${athlete.year_of_birth ? ` • ${athlete.year_of_birth}` : ''}
                            </div>
                        </div>
                    </div>
                `).join('');
                resultsDiv.classList.add('active');

                // Add click handlers
                resultsDiv.querySelectorAll('.search-result-item').forEach(item => {
                    item.addEventListener('click', () => {
                        selectAthlete(athleteKey, {
                            id: parseInt(item.dataset.id),
                            name: item.dataset.name,
                            country_emoji: item.dataset.countryEmoji,
                            country_name: item.dataset.countryName,
                            country_alpha3: item.dataset.countryAlpha3,
                            year_of_birth: item.dataset.yob
                        }, searchInput, resultsDiv, selectedDiv, searchWrapper);
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

function selectAthlete(athleteKey, athlete, searchInput, resultsDiv, selectedDiv, searchWrapper) {
    /* Store the selected athlete and build the athlete display card under the search box */
    selectedAthletes[athleteKey] = athlete;
    
    searchInput.value = '';
    resultsDiv.classList.remove('active');
    if (searchWrapper) {
        searchWrapper.classList.add('hidden');
    }
    
    const imgSrc = `/static/athlete_imgs/${athlete.id}.jpg`;
    const defaultImgSrc = `/static/default_user.jpg`
    selectedDiv.innerHTML = `
        <button class="selected-athlete-remove" aria-label="Clear selection">&times;</button>

        <div class="selected-athlete-container">
            <img 
                class="selected-athlete-img"
                src="${imgSrc}"
                onerror="${defaultImgSrc}"
                alt="${athlete.name}"
            >

            <div class="selected-athlete-text">
                <div class="selected-athlete-name">${athlete.name} ${athlete.country_emoji}</div>
                <div class="selected-athlete-info">
                    ${athlete.country_name} ${athlete.year_of_birth ? `YOB: ${athlete.year_of_birth}` : ''}
                </div>
            </div>
        </div>
    `;

    selectedDiv.classList.add('selected-athlete');
    selectedDiv.classList.add('active');
    const removeButton = selectedDiv.querySelector('.selected-athlete-remove');
    removeButton.addEventListener('click', () => {
        clearSelectedAthlete(athleteKey, searchInput, selectedDiv, searchWrapper);
    });

    updateCompareButton();
}

/* --- --- */
function clearSelectedAthlete(athleteKey, searchInput, selectedDiv, searchWrapper) {
    selectedAthletes[athleteKey] = null;
    selectedDiv.classList.remove('active');
    selectedDiv.innerHTML = '';
    if (searchWrapper) {
        searchWrapper.classList.remove('hidden');
    }
    searchInput.value = '';
    searchInput.focus();
    updateCompareButton();
}

function updateCompareButton() {
    /* Enable button if both athletes are selected */
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

        // --- Load the comparison_results.js dynamically ---
        loadComparisonResultsJs();

    } catch (error) {
        showError(error.message);
    } finally {
        loadingDiv.classList.remove('active');
    }
}

// --- Load comparison charts dynamically from their js ---
function loadComparisonResultsJs() {
    if (comparisonGraphsLoaded) {
        // If script already loaded, just re-init graphs, don't re-add the whole script
        initOverallChart();
        initSwimChart();
        initBikeChart();
        initRunChart();
        initTransitionChart();  
        return;
    }
    
    const script = document.createElement("script");
    script.src = "/static/js/comparison_results.js";
    document.body.appendChild(script);

    // Initialise all rating graphs
    script.onload = () => {
        comparisonGraphsLoaded = true;
        initOverallChart();
        initSwimChart();
        initBikeChart();
        initRunChart();
        initTransitionChart();
    };
}

// Initialize
initSearch('search1', 'results1', 'selected1', 'athlete1');
initSearch('search2', 'results2', 'selected2', 'athlete2');

document.getElementById('compareBtn').addEventListener('click', performComparison);
