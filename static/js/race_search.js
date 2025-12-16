// Search functionality
let searchTimeout;
const searchInput = document.getElementById('raceSearch');
const searchResults = document.getElementById('searchResults');

if (searchInput && searchResults) {
    searchInput.addEventListener('input', function() {
        const query = this.value.trim();
        
        // Clear previous timeout
        clearTimeout(searchTimeout);
        
        // Hide results if query is too short
        if (query.length < 2) {
            searchResults.style.display = 'none';
            return;
        }
        
        // Show loading state
        searchResults.innerHTML = '<div class="search-loading">Searching...</div>';
        searchResults.style.display = 'block';
        
        // Debounce search
        searchTimeout = setTimeout(() => {
            performSearch(query);
        }, 300);
    });
}

async function performSearch(query) {
    try {
        const response = await fetch(`/races/search?q=${encodeURIComponent(query)}`);
        const results = await response.json();
        
        displayResults(results);
    } catch (error) {
        console.error('Search error:', error);
        searchResults.innerHTML = '<div class="no-results">Error performing search</div>';
    }
}

function displayResults(results) {
    if (results.length === 0) {
        searchResults.innerHTML = '<div class="no-results">No races found</div>';
        return;
    }
    
    const html = results.map(race => `
        <a href="/race/${race.race_id}" class="search-result-item">
            <div class="result-info">
                <div class="result-race-title">${escapeHtml(race.race_title)}</div>
                <div class="result-prog-name">${escapeHtml(race.prog_name)}</div>
                <div class="result-meta">
                    ${escapeHtml(race.race_country)} • ${race.prog_date}
                </div>
            </div>
        </a>
    `).join('');
    
    searchResults.innerHTML = html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Close search results when clicking outside
document.addEventListener('click', function(event) {
    if (!searchResults || !searchInput) return;
    if (!event.target.closest('.search-container')) {
        searchResults.style.display = 'none';
    }
});

// Reopen results when focusing on input with existing query
if (searchInput && searchResults) {
    searchInput.addEventListener('focus', function() {
        if (this.value.trim().length >= 2 && searchResults.innerHTML.trim() !== '') {
            searchResults.style.display = 'block';
        }
    });
}

// Load more races
function initRaceLoadMore() {
    const loadMoreBtn = document.getElementById('loadMoreRaces');
    const raceGrid = document.getElementById('raceGrid');
    const pageSize = 30;

    if (!loadMoreBtn || !raceGrid) return;

    let offset = parseInt(loadMoreBtn.dataset.offset, 10) || 0;

    loadMoreBtn.addEventListener('click', async () => {
        loadMoreBtn.disabled = true;
        const originalText = loadMoreBtn.textContent;
        loadMoreBtn.textContent = 'Loading...';

        try {
            const res = await fetch(`/races/more?offset=${offset}`);
            if (!res.ok) {
                throw new Error('Failed to fetch more races');
            }

            const html = await res.text();
            if (html.trim().length === 0) {
                loadMoreBtn.style.display = 'none';
                return;
            }

            raceGrid.insertAdjacentHTML('beforeend', html);
            offset += pageSize;
            loadMoreBtn.dataset.offset = offset;
            loadMoreBtn.textContent = originalText;
        } catch (err) {
            console.error('Error loading more races', err);
            loadMoreBtn.textContent = 'Try again';
        } finally {
            loadMoreBtn.disabled = false;
        }
    });
}

initRaceLoadMore();
