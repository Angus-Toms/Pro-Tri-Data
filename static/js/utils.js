function formatTime(seconds) {
    const absSeconds = Math.abs(seconds);
    const hours = Math.floor(absSeconds / 3600);
    const minutes = Math.floor((absSeconds % 3600) / 60);
    const secs = Math.floor(absSeconds % 60);
    
    const sign = seconds < 0 ? '-' : '';
    
    if (hours > 0) {
        return `${sign}${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    } 
    
    return `${sign}${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

function toggleCollapse(toggle) {
    const content = toggle.closest('.collapsible-card').querySelector('.collapsible-content');
    content.classList.toggle('collapsed');
    toggle.textContent = content.classList.contains('collapsed') ? '+' : '−';
}

function parseTime(timeStr) {
    // Convert time string (HH:MM:SS or MM:SS) to seconds for sorting
    if (!timeStr || timeStr === 'DNF' || timeStr === 'DQ') return Infinity;
    const parts = timeStr.split(':').map(Number);
    if (parts.length === 3) {
        return parts[0] * 3600 + parts[1] * 60 + parts[2];
    } else if (parts.length === 2) {
        return parts[0] * 60 + parts[1];
    }
    return parseFloat(timeStr) || 0;
}

function sortTable(table, column, asc = true) {
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    
    // Skip if no data
    if (rows.length === 1 && rows[0].querySelector('.no-data')) return;
    
    const sortType = table.querySelectorAll('th')[column].getAttribute('data-sort');
    
    rows.sort((a, b) => {
        const aCell = a.cells[column];
        const bCell = b.cells[column];
        
        let aVal = aCell.getAttribute('data-value') || aCell.textContent.trim();
        let bVal = bCell.getAttribute('data-value') || bCell.textContent.trim();
        
        // Handle different data types
        if (sortType === 'time') {
            aVal = parseTime(aVal);
            bVal = parseTime(bVal);
        } else if ( sortType === 'rating') {
            aVal = parseFloat(aVal);
            bVal = parseFloat(bVal);
        } else if (sortType === 'position') {
            // Handle special cases for position
            const specialValues = { 'LAP': 9997, 'DNF': 9998, 'DQ': 9999 };
            aVal = specialValues[aVal] !== undefined ? specialValues[aVal] : parseInt(aVal) || Infinity;
            bVal = specialValues[bVal] !== undefined ? specialValues[bVal] : parseInt(bVal) || Infinity;
        } else if (sortType === 'race-id' || sortType === 'date' || sortType === 'string') {
            // String comparison for dates and IDs
            aVal = aVal.toString();
            bVal = bVal.toString();
        } else {
            // Try numeric, fallback to string
            const aNum = parseFloat(aVal);
            const bNum = parseFloat(bVal);
            if (!isNaN(aNum) && !isNaN(bNum)) {
                aVal = aNum;
                bVal = bNum;
            }
        }
        
        if (aVal < bVal) return asc ? -1 : 1;
        if (aVal > bVal) return asc ? 1 : -1;
        return 0;
    });
    
    // Reappend rows in sorted order
    rows.forEach(row => tbody.appendChild(row));
}

function getJSON(id) {
    const el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}