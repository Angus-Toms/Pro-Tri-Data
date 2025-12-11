// Store references to charts, allows for reloading once they've been created
let overallRatingsChart = null;  
let swimRatingsChart = null;
let bikeRatingsChart = null;
let runRatingsChart = null;
let transitionRatingsChart = null;

function initOverallChart() {
    const ctx = document.getElementById('overall-ratings-canvas');
    if (!ctx) return;

    const data = getJSON('overall-ratings-data');

    if (overallRatingsChart) {
        overallRatingsChart.destroy();
    }

    overallRatingsChart = new Chart(ctx, {
        type: 'line',
        data: data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            elements: {
                line: {
                    tension: 0
                }
            },
            plugins: {
                legend: { display: true },
                tooltip: { 
                    mode: 'nearest',
                    intersect: true,
                    callbacks: {
                        title: function(context) {
                            const dataPoint = context[0].raw;
                            const date = new Date(dataPoint.x);
                            return [
                                dataPoint.race_name,
                                date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
                            ];
                        },
                        label: function(context) {
                            return context.dataset.label + ": " + context.parsed.y;
                        }
                    }
                },
            },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'year', tooltipFormat: 'dd-MM-yyyy' },
                    title: { display: true, text: 'Date' }
                },
                y: {
                    beginAtZero: false,
                    title: { display: true, text: 'Rating' }
                }
            }
        }
    });
}

function initSwimChart() {
    const ctx = document.getElementById('swim-ratings-canvas');
    if (!ctx) return;

    const data = getJSON('swim-ratings-data');

    if (swimRatingsChart) {
        swimRatingsChart.destroy();
    }

    swimRatingsChart = new Chart(ctx, {
        type: 'line',
        data: data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            elements: {
                line: {
                    tension: 0
                }
            },
            plugins: {
                legend: { display: true },
                tooltip: { 
                    mode: 'nearest',
                    intersect: true,
                    callbacks: {
                        title: function(context) {
                            const dataPoint = context[0].raw;
                            const date = new Date(dataPoint.x);
                            return [
                                dataPoint.race_name,
                                date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
                            ];
                        },
                        label: function(context) {
                            return context.dataset.label + ": " + context.parsed.y;
                        }
                    }
                },
            },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'year', tooltipFormat: 'dd-MM-yyyy' },
                    title: { display: true, text: 'Date' }
                },
                y: {
                    beginAtZero: false,
                    title: { display: true, text: 'Rating' }
                }
            }
        }
    });
}

function initBikeChart() {
    const ctx = document.getElementById('bike-ratings-canvas');
    if (!ctx) return;

    const data = getJSON('bike-ratings-data');

    if (bikeRatingsChart) {
        bikeRatingsChart.destroy();
    }

    bikeRatingsChart = new Chart(ctx, {
        type: 'line',
        data: data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            elements: {
                line: {
                    tension: 0
                }
            },
            plugins: {
                legend: { display: true },
                tooltip: { 
                    mode: 'nearest',
                    intersect: true,
                    callbacks: {
                        title: function(context) {
                            const dataPoint = context[0].raw;
                            const date = new Date(dataPoint.x);
                            return [
                                dataPoint.race_name,
                                date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
                            ];
                        },
                        label: function(context) {
                            return context.dataset.label + ": " + context.parsed.y;
                        }
                    }
                },
            },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'year', tooltipFormat: 'dd-MM-yyyy' },
                    title: { display: true, text: 'Date' }
                },
                y: {
                    beginAtZero: false,
                    title: { display: true, text: 'Rating' }
                }
            }
        }
    });
}

function initRunChart() {
    const ctx = document.getElementById('run-ratings-canvas');
    if (!ctx) return;

    const data = getJSON('run-ratings-data');

    if (runRatingsChart) {
        runRatingsChart.destroy();
    }

    runRatingsChart = new Chart(ctx, {
        type: 'line',
        data: data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            elements: {
                line: {
                    tension: 0
                }
            },
            plugins: {
                legend: { display: true },
                tooltip: { 
                    mode: 'nearest',
                    intersect: true,
                    callbacks: {
                        title: function(context) {
                            const dataPoint = context[0].raw;
                            const date = new Date(dataPoint.x);
                            return [
                                dataPoint.race_name,
                                date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
                            ];
                        },
                        label: function(context) {
                            return context.dataset.label + ": " + context.parsed.y;
                        }
                    }
                },
            },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'year', tooltipFormat: 'dd-MM-yyyy' },
                    title: { display: true, text: 'Date' }
                },
                y: {
                    beginAtZero: false,
                    title: { display: true, text: 'Rating' }
                }
            }
        }
    });
}

function initTransitionChart() {
    const ctx = document.getElementById('transition-ratings-canvas');
    if (!ctx) return;

    const data = getJSON('transition-ratings-data');

    if (transitionRatingsChart) {
        transitionRatingsChart.destroy();
    }

    transitionRatingsChart = new Chart(ctx, {
        type: 'line',
        data: data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            elements: {
                line: {
                    tension: 0
                }
            },
            plugins: {
                legend: { display: true },
                tooltip: { 
                    mode: 'nearest',
                    intersect: true,
                    callbacks: {
                        title: function(context) {
                            const dataPoint = context[0].raw;
                            const date = new Date(dataPoint.x);
                            return [
                                dataPoint.race_name,
                                date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
                            ];
                        },
                        label: function(context) {
                            return context.dataset.label + ": " + context.parsed.y;
                        }
                    }
                },
            },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'year', tooltipFormat: 'dd-MM-yyyy' },
                    title: { display: true, text: 'Date' }
                },
                y: {
                    beginAtZero: false,
                    title: { display: true, text: 'Rating' }
                }
            }
        }
    });
}
