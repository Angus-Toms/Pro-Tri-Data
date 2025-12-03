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


// Overall time histogram ------------------------------------------------------
const overallCtx = document.getElementById('overall-times-canvas');
const overallTimesData = getJSON('overall-hist-data');

new Chart(overallCtx, {
    type: 'bar',
    data: overallTimesData,
    options: {
        responsive: true,
        maintainAspectRatio: false,
        parsing: false,
        plugins: {
            legend: {
                display: false
            },
            tooltip: {
                mode: 'index',
                callbacks: {
                    title: function(context) {
                        const dataPoint = context[0].raw;
                        return dataPoint.label;
                    },
                    label: function(context) {
                        const athletes = context.raw.y;
                        return `Athletes: ${athletes}`;
                    }
                }
            }
        },
        scales: {
            x: {
                beginAtZero: false,
                type: 'linear',
                title: {
                    display: true,
                    text: 'Overall Time'
                },
                ticks: {
                    callback: function(value, index, ticks) {
                        const num = Number(value);
                        return isNaN(num) ? value : formatTime(num);
                    }
                }
            }, 
            y: {
                beginAtZero: true,
                type: 'linear',
                title: {
                    display: true,
                    text: 'Number of Athletes'
                }

            }
        }
    }
});

// Swim time histogram ---------------------------------------------------------
const swimCtx = document.getElementById('swim-times-canvas');
const swimTimesData = getJSON('swim-hist-data');

new Chart(swimCtx, {
    type: 'bar',
    data: swimTimesData,
    options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: false
            },
            tooltip: {
                mode: 'index',
                callbacks: {
                    title: function(context) {
                        const dataPoint = context[0].raw;
                        return dataPoint.label;
                    },
                    label: function(context) {
                        const athletes = context.raw.y;
                        return `Athletes: ${athletes}`;
                    }
                }
            }
        },
        scales: {
            x: {
                beginAtZero: false,
                type: 'linear',
                title: {
                    display: true,
                    text: 'Swim Time'
                },
                ticks: {
                    callback: function(value, index, ticks) {
                        const num = Number(value);
                        return isNaN(num) ? value : formatTime(num);
                    }
                }
            }, 
            y: {
                beginAtZero: true,
                type: 'linear',
                title: {
                    display: true,
                    text: 'Number of Athletes'
                }

            }
        }
    }
});

// Bike time histogram ---------------------------------------------------------
const bikeCtx = document.getElementById('bike-times-canvas');
const bikeTimesData = getJSON('bike-hist-data');

new Chart(bikeCtx, {
    type: 'bar',
    data: bikeTimesData,
    options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: false
            },
            tooltip: {
                mode: 'index',
                callbacks: {
                    title: function(context) {
                        const dataPoint = context[0].raw;
                        return dataPoint.label;
                    },
                    label: function(context) {
                        const athletes = context.raw.y;
                        return `Athletes: ${athletes}`;
                    }
                }
            }
        },
        scales: {
            x: {
                beginAtZero: false,
                type: 'linear',
                title: {
                    display: true,
                    text: 'Bike Time'
                },
                ticks: {
                    callback: function(value, index, ticks) {
                        const num = Number(value);
                        return isNaN(num) ? value : formatTime(num);
                    }
                }
            }, 
            y: {
                beginAtZero: true,
                type: 'linear',
                title: {
                    display: true,
                    text: 'Number of Athletes'
                }

            }
        }
    }
});

// Run time histogram ----------------------------------------------------------
const runCtx = document.getElementById('run-times-canvas');
const runTimesData = getJSON('run-hist-data');

new Chart(runCtx, {
    type: 'bar',
    data: runTimesData,
    options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: false
            },
            tooltip: {
                mode: 'index',
                callbacks: {
                    title: function(context) {
                        const dataPoint = context[0].raw;
                        return dataPoint.label;
                    },
                    label: function(context) {
                        const athletes = context.raw.y;
                        return `Athletes: ${athletes}`;
                    }
                }
            }
        },
        scales: {
            x: {
                beginAtZero: false,
                type: 'linear',
                title: {
                    display: true,
                    text: 'Run Time'
                },
                ticks: {
                    callback: function(value, index, ticks) {
                        const num = Number(value);
                        return isNaN(num) ? value : formatTime(num);
                    }
                }
            }, 
            y: {
                beginAtZero: true,
                type: 'linear',
                title: {
                    display: true,
                    text: 'Number of Athletes'
                }

            }
        }
    }
});

// T1 time histogram ----------------------------------------------------------- 
const t1Ctx = document.getElementById('t1-times-canvas');
const t1TimesData = getJSON('t1-hist-data');

new Chart(t1Ctx, {
    type: 'bar',
    data: t1TimesData,
    options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: false
            },
            tooltip: {
                mode: 'index',
                callbacks: {
                    title: function(context) {
                        const dataPoint = context[0].raw;
                        return dataPoint.label;
                    },
                    label: function(context) {
                        const athletes = context.raw.y;
                        return `Athletes: ${athletes}`;
                    }
                }
            }
        },
        scales: {
            x: {
                beginAtZero: false,
                type: 'linear',
                title: {
                    display: true,
                    text: 'T1 Time'
                },
                ticks: {
                    callback: function(value, index, ticks) {
                        const num = Number(value);
                        return isNaN(num) ? value : formatTime(num);
                    }
                }
            }, 
            y: {
                beginAtZero: true,
                type: 'linear',
                title: {
                    display: true,
                    text: 'Number of Athletes'
                }

            }
        }
    }
});

// T2 time histogram ----------------------------------------------------------- 
const t2Ctx = document.getElementById('t2-times-canvas');
const t2TimesData = getJSON('t2-hist-data');

new Chart(t2Ctx, {
    type: 'bar',
    data: t2TimesData,
    options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: false
            },
            tooltip: {
                mode: 'index',
                callbacks: {
                    title: function(context) {
                        const dataPoint = context[0].raw;
                        return dataPoint.label;
                    },
                    label: function(context) {
                        const athletes = context.raw.y;
                        return `Athletes: ${athletes}`;
                    }
                }
            }
        },
        scales: {
            x: {
                beginAtZero: false,
                type: 'linear',
                title: {
                    display: true,
                    text: 'T1 Time'
                },
                ticks: {
                    callback: function(value, index, ticks) {
                        const num = Number(value);
                        return isNaN(num) ? value : formatTime(num);
                    }
                }
            }, 
            y: {
                beginAtZero: true,
                type: 'linear',
                title: {
                    display: true,
                    text: 'Number of Athletes'
                }

            }
        }
    }
});

