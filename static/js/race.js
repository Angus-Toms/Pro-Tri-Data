// Add click handlers to sortable headers
document.addEventListener('DOMContentLoaded', () => {
    const tables = document.querySelectorAll('table.sortable-table');
    if (!tables.length) return;

    tables.forEach(table => {
        const headers = table.querySelectorAll('th.sortable');

        headers.forEach((header, index) => {
            header.addEventListener('click', () => {
                // Toggle sort direction
                const isAsc = header.classList.contains('asc');
                
                // Remove all sorting classes
                headers.forEach(h => h.classList.remove('asc', 'desc'));
                
                // Add appropriate class
                if (isAsc) {
                    header.classList.add('desc');
                    sortTable(table, index, false);
                } else {
                    header.classList.add('asc');
                    sortTable(table, index, true);
                }
            });
        });
    });
});