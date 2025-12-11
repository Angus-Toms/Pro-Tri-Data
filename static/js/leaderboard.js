let leaderboardOffset = 50;

function initLoadMore() {
    const loadMoreBtn = document.getElementById("loadMoreBtn");
    if (!loadMoreBtn) return;

    loadMoreBtn.addEventListener("click", async() => {
        const params = new URLSearchParams(window.location.search);
        params.append("offset", leaderboardOffset);

        try {
            const res = await fetch(`/leaderboard/more?${params.toString()}`);
            const html = await res.text();

            const container = document.querySelector(".leaderboard-grid");

            // Append results
            container.insertAdjacentHTML("beforeend", html);

            leaderboardOffset += 50;

            // If less than 50 rows returned, no more athletes to load, turn off button
            if (html.trim().length === 0) {
                loadMoreBtn.style.display = "none";
            }
        } catch (err) {
            console.err("Error loading more athletes", err);
        }
    });
}

initLoadMore();