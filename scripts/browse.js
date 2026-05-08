const savedUser = localStorage.getItem("netflixCloneUser");
const savedSession = localStorage.getItem("netflixCloneSession");
const PLACEHOLDER_POSTER = "https://via.placeholder.com/400x600/2a2a2a/b3b3b3?text=No+Poster";

if (!savedUser) {
  window.location.href = "/signin";
} else {
  const user = JSON.parse(savedUser);
  const welcomeText = document.getElementById("welcome-text");
  const logoutButton = document.getElementById("logout-btn");
  const moviesStatus = document.getElementById("movies-status");
  const moviesGrid = document.getElementById("movies-grid");
  const searchInput = document.getElementById("movie-search");
  const searchButton = document.getElementById("search-btn");
  const searchSuggestions = document.getElementById("search-suggestions");
  const categoryList = document.getElementById("category-list");
  const languageFilterList = document.getElementById("language-filter-list");
  const categoriesSection = document.querySelector(".categories-section");
  const filtersSection = document.querySelector(".filters-section");
  const recommendStatus = document.getElementById("recommend-status");
  const recommendScroll = document.getElementById("recommend-scroll");
  const genreRowsEl = document.getElementById("genre-rows");
  const catalogSection = document.getElementById("catalog-section");
  const catalogHeading = document.getElementById("catalog-heading");
  const recommendSection = document.getElementById("recommend-section");
  const infiniteSentinel = document.getElementById("infinite-sentinel");
  const playerModal = document.getElementById("player-modal");
  const playerBackdrop = document.getElementById("player-backdrop");
  const closePlayerBtn = document.getElementById("close-player-btn");
  const playerTitle = document.getElementById("player-title");
  const playerStatus = document.getElementById("player-status");
  const playerIframe = document.getElementById("player-iframe");
  const playerVideo = document.getElementById("player-video");
  const planCta = document.getElementById("plan-cta");
  const episodeControls = document.getElementById("episode-controls");
  const seasonSelect = document.getElementById("season-select");
  const episodeSelect = document.getElementById("episode-select");
  const playEpisodeBtn = document.getElementById("play-episode-btn");

  let allCatalog = [];
  let allPremiumPreview = [];
  let activeCategory = "All";
  let searchResults = null;
  let suggestTimer = null;
  let activeSeriesSeasons = [];
  let activeSeriesMovie = null;
  let activeLanguage = "All";
  let homeRows = [];
  let renderedRowCount = 0;
  let homeObserver = null;

  const WATCH_HISTORY_KEY = "netflixCloneWatchHistory";
  const ROWS_PER_BATCH = 4;
  const LANGUAGE_FILTERS = ["All", "Hindi / Indian", "English", "Korean", "Japanese", "Spanish", "Anime"];

  function planLabelFor(plan, expiresAt) {
    const p = String(plan || "free").toLowerCase();
    const exp = Number(expiresAt || 0);
    const expired = exp ? exp * 1000 < Date.now() : false;
    if (expired) return "EXPIRED";
    if (p === "free") return "FREE";
    if (p === "m149") return "₹149/MO";
    if (p === "m349") return "₹349/MO";
    if (p === "y5000") return "₹5000/YR";
    if (p === "premium") return "PREMIUM";
    return p.toUpperCase();
  }

  function renderWelcome() {
    const label = planLabelFor(user.plan, user.plan_expires_at);
    welcomeText.innerHTML = `Welcome, ${user.full_name} (<button type="button" class="plan-pill" id="plan-pill" aria-label="View plans">${label}</button>)`;
    const pill = document.getElementById("plan-pill");
    if (pill) {
      pill.addEventListener("click", () => {
        window.location.href = "/plan";
      });
    }
  }

  renderWelcome();

  logoutButton.addEventListener("click", () => {
    localStorage.removeItem("netflixCloneUser");
    const sessionId = localStorage.getItem("netflixCloneSession");
    localStorage.removeItem("netflixCloneSession");
    if (sessionId) {
      fetch("/api/signout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      }).catch(() => {});
    }
    window.location.href = "/signin";
  });

  function normalizeGenre(genre) {
    return genre || "General";
  }

  function uniqueById(items) {
    const seen = new Set();
    const out = [];
    items.forEach((item) => {
      const id = String(item?.id || "");
      if (!id || seen.has(id)) return;
      seen.add(id);
      out.push(item);
    });
    return out;
  }

  function hashText(text) {
    let hash = 0;
    const src = String(text || "");
    for (let i = 0; i < src.length; i += 1) {
      hash = (hash * 31 + src.charCodeAt(i)) >>> 0;
    }
    return hash;
  }

  function rotated(items, seed = 0) {
    if (!items.length) return [];
    const offset = seed % items.length;
    return [...items.slice(offset), ...items.slice(0, offset)];
  }

  function getWatchHistory() {
    try {
      const raw = JSON.parse(localStorage.getItem(WATCH_HISTORY_KEY) || "[]");
      return Array.isArray(raw) ? raw : [];
    } catch {
      return [];
    }
  }

  function pushWatchHistory(movie) {
    const history = getWatchHistory();
    const next = [
      {
        id: String(movie.id),
        title: movie.title || "",
        genres: movie.genres || [],
        type: movie.type || "movie",
        watchedAt: Date.now(),
      },
      ...history.filter((entry) => String(entry.id) !== String(movie.id)),
    ].slice(0, 40);
    localStorage.setItem(WATCH_HISTORY_KEY, JSON.stringify(next));
  }

  function detectLanguageBucket(movie) {
    const blob = `${movie.title || ""} ${(movie.genres || []).join(" ")}`.toLowerCase();
    if (/(bollywood|hindi|indian|tollywood|kollywood)/.test(blob)) return "Hindi / Indian";
    if (/(korean|k-drama|k drama|parasite|squid game|train to busan)/.test(blob)) return "Korean";
    if (/(japanese|japan|anime|naruto|one piece|demon slayer|pokemon)/.test(blob)) return "Japanese";
    if (/(anime|animation)/.test(blob)) return "Anime";
    if (/(spanish|espanol|spain|latin|money heist|casa de papel|elite|berlin|roma)/.test(blob)) return "Spanish";
    return "English";
  }

  function applyLanguageFilter(items) {
    if (activeLanguage === "All") return items;
    if (activeLanguage === "Anime") {
      return items.filter((m) => detectLanguageBucket(m) === "Anime" || /anime/i.test((m.genres || []).join(" ")));
    }
    return items.filter((m) => detectLanguageBucket(m) === activeLanguage);
  }

  function topGenresFrom(movies, limit = 10) {
    const count = {};
    movies.forEach((m) => (m.genres || []).forEach((g) => (count[g] = (count[g] || 0) + 1)));
    return Object.keys(count).sort((a, b) => count[b] - count[a]).slice(0, limit);
  }

  function renderCard(movie) {
    const poster = movie.poster || PLACEHOLDER_POSTER;
    const rating = Number(movie.rating);
    const ratingText = Number.isFinite(rating) ? rating.toFixed(1) : "N/A";
    const hasFullMovie = Boolean(movie.full_movie_available);
    const isFree = String(user.plan || "free").toLowerCase() === "free";
    const lock = false;
    const badgeLabel = hasFullMovie ? "Full Movie Available" : "Trailer Only";
    const badgeClass = hasFullMovie ? "availability-badge full" : "availability-badge trailer";
    const buttonLabel = isFree
      ? "Take a plan"
      : lock
      ? "Upgrade to Play full movie"
      : hasFullMovie
        ? "Play full movie"
        : "Watch trailer";
    return `
      <article class="movie-card">
        <img class="movie-poster" src="${poster}" alt="${movie.title}" loading="lazy">
        <span class="${badgeClass}">${badgeLabel}</span>
        <div class="movie-content">
          <h3 class="movie-title">${movie.title}</h3>
          <p class="movie-meta">${movie.year || "N/A"} · ${(movie.type || "movie").toUpperCase()} · Rating ${ratingText}</p>
          <p class="movie-genres">${(movie.genres || []).join(", ") || "General"}</p>
          <button type="button" class="play-btn" data-id="${movie.id}">${buttonLabel}</button>
        </div>
      </article>
    `;
  }

  function getMovieById(id) {
    return [...allCatalog, ...allPremiumPreview, ...(searchResults || [])].find((m) => String(m.id) === String(id));
  }

  function closePlayer() {
    playerModal.classList.add("hidden");
    playerIframe.removeAttribute("src");
    playerIframe.classList.remove("hidden");
    planCta?.classList.add("hidden");
    try {
      playerVideo.pause();
    } catch {}
    playerVideo.removeAttribute("src");
    playerVideo.load();
    playerVideo.classList.add("hidden");
    playerStatus.textContent = "";
    episodeControls.classList.add("hidden");
    seasonSelect.innerHTML = "";
    episodeSelect.innerHTML = "";
    activeSeriesSeasons = [];
    activeSeriesMovie = null;
    document.body.style.overflow = "";
  }

  function renderEpisodeOptions(seasonNumber) {
    const selectedSeason = activeSeriesSeasons.find((s) => Number(s.season) === Number(seasonNumber));
    const episodes = selectedSeason ? selectedSeason.episodes || [] : [];
    episodeSelect.innerHTML = episodes
      .map(
        (ep) =>
          `<option value="${ep.episode}">E${ep.episode}: ${ep.title}</option>`
      )
      .join("");
  }

  async function playUrlForTitle(title, year) {
    let watchUrl = "";
    let sourceType = "embed";
    let note = "";
    let quality = "";
    let matchedTitle = "";
    try {
      const yearParam = year ? `&year=${encodeURIComponent(year)}` : "";
      const sessionParam = savedSession ? `&session_id=${encodeURIComponent(savedSession)}` : "";
      const res = await fetch(`/api/watch-link?title=${encodeURIComponent(title)}${yearParam}${sessionParam}`);
      const data = await res.json();
      if (!res.ok) {
        playerStatus.textContent = data.error || "Playback is unavailable. Please choose a plan.";
        planCta?.classList.remove("hidden");
        return;
      }
      watchUrl = data.watch_url || "";
      sourceType = data.source_type || "embed";
      note = data.note || "";
      quality = data.quality || "";
      matchedTitle = data.matched_title || "";
    } catch {
      watchUrl = "";
    }
    planCta?.classList.add("hidden");
    if (watchUrl) {
      if (sourceType === "video") {
        playerIframe.removeAttribute("src");
        playerIframe.classList.add("hidden");
        playerVideo.classList.remove("hidden");
        playerVideo.src = watchUrl;
        try {
          await playerVideo.play();
        } catch {
          // User gesture/codec restrictions may block autoplay; controls remain visible.
        }
      } else {
        try {
          playerVideo.pause();
        } catch {}
        playerVideo.removeAttribute("src");
        playerVideo.load();
        playerVideo.classList.add("hidden");
        playerIframe.classList.remove("hidden");
        playerIframe.src = watchUrl;
      }
      const details = [note, matchedTitle ? `Source: ${matchedTitle}` : "", quality ? `Quality: ${quality}` : ""]
        .filter(Boolean)
        .join(" ");
      playerStatus.textContent = details || "Playing.";
      return;
    }
    playerStatus.textContent = "Playback link is unavailable for this title.";
  }

  async function loadSeriesEpisodes(movie) {
    if (movie.type !== "tv") {
      episodeControls.classList.add("hidden");
      return;
    }
    playerStatus.textContent = "Loading seasons and episodes...";
    try {
      const res = await fetch(`/api/series-episodes?id=${encodeURIComponent(movie.id)}`);
      const data = await res.json();
      const seasons = data.seasons || [];
      if (!res.ok || !seasons.length) {
        episodeControls.classList.add("hidden");
        playerStatus.textContent = data.error || "Episode list is unavailable.";
        return;
      }
      activeSeriesSeasons = seasons;
      activeSeriesMovie = movie;
      seasonSelect.innerHTML = seasons
        .map((s) => `<option value="${s.season}">Season ${s.season}</option>`)
        .join("");
      renderEpisodeOptions(Number(seasonSelect.value || seasons[0].season));
      episodeControls.classList.remove("hidden");
      playerStatus.textContent = "Select season and episode to play.";
    } catch {
      episodeControls.classList.add("hidden");
      playerStatus.textContent = "Could not load episodes for this series.";
    }
  }

  async function openPlayer(movie) {
    const currentPlan = String(user.plan || "free").toLowerCase();
    const expiresAt = Number(user.plan_expires_at || 0);
    const isExpired = expiresAt ? expiresAt * 1000 < Date.now() : false;
    if (currentPlan === "free" || isExpired) {
      playerModal.classList.remove("hidden");
      document.body.style.overflow = "hidden";
      playerIframe.removeAttribute("src");
      playerIframe.classList.add("hidden");
      try {
        playerVideo.pause();
      } catch {}
      playerVideo.removeAttribute("src");
      playerVideo.load();
      playerVideo.classList.add("hidden");
      episodeControls.classList.add("hidden");
      planCta?.classList.remove("hidden");
      playerTitle.textContent = movie.title;
      playerStatus.textContent = "To watch trailers, movies, or series, please take a plan.";
      return;
    }

    pushWatchHistory(movie);
    playerTitle.textContent = movie.title;
    playerStatus.textContent = "Loading...";
    playerModal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
    playerIframe.removeAttribute("src");

    if (movie.type === "tv") {
      await loadSeriesEpisodes(movie);
      return;
    }

    episodeControls.classList.add("hidden");
    await playUrlForTitle(movie.title, movie.year);
  }

  function renderCategoryButtons(genres) {
    const categories = ["All", ...genres];
    categoryList.innerHTML = categories
      .map((category) => `<button type="button" role="tab" class="category-btn ${activeCategory === category ? "active" : ""}" data-category="${category}">${category}</button>`)
      .join("");
    categoryList.querySelectorAll(".category-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeCategory = btn.dataset.category;
        renderCategoryButtons(genres);
        renderBrowse();
      });
    });
  }

  function renderLanguageButtons() {
    languageFilterList.innerHTML = LANGUAGE_FILTERS.map(
      (label) =>
        `<button type="button" class="language-filter-btn ${activeLanguage === label ? "active" : ""}" data-language="${label}">${label}</button>`
    ).join("");
    languageFilterList.querySelectorAll(".language-filter-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeLanguage = btn.dataset.language || "All";
        renderLanguageButtons();
        searchResults = null;
        renderBrowse();
      });
    });
  }

  function sectionRow(label, items) {
    const safeItems = uniqueById(items).slice(0, 48);
    if (!safeItems.length) return null;
    return {
      title: label,
      html: `
      <section class="row-section">
        <h2 class="row-heading">${label}</h2>
        <div class="row-scroll">${safeItems.map(renderCard).join("")}</div>
      </section>`,
    };
  }

  function uniqueNotUsed(items, usedIds, limit = 48) {
    const out = [];
    uniqueById(items).forEach((item) => {
      const id = String(item?.id || "");
      if (!id || usedIds.has(id)) return;
      usedIds.add(id);
      out.push(item);
    });
    return out.slice(0, limit);
  }

  function appendNextRows() {
    if (renderedRowCount >= homeRows.length) return;
    const nextRows = homeRows.slice(renderedRowCount, renderedRowCount + ROWS_PER_BATCH);
    genreRowsEl.insertAdjacentHTML("beforeend", nextRows.map((r) => r.html).join(""));
    renderedRowCount += nextRows.length;
    if (renderedRowCount >= homeRows.length) {
      moviesStatus.textContent = `${allCatalog.length}+ titles loaded. End of rows reached for now.`;
    }
  }

  function renderBrowse() {
    const query = searchInput.value.trim().toLowerCase();
    const isSearchMode = Boolean(searchResults);
    const base = isSearchMode ? (searchResults || []) : applyLanguageFilter(allCatalog);
    const filtered = base.filter((m) => {
      const inCategory = activeCategory === "All" || (m.genres || []).map(normalizeGenre).includes(activeCategory);
      if (!inCategory) return false;
      if (!query) return true;
      const blob = `${m.title || ""} ${(m.genres || []).join(" ")} ${m.year || ""}`.toLowerCase();
      return blob.includes(query);
    });

    // Catalog grid mode: search results or typed query. Category filtering stays in grid mode,
    // but we keep the category/filter controls visible so the user can return to "All".
    if (query || isSearchMode || activeCategory !== "All") {
      genreRowsEl.classList.add("hidden");
      infiniteSentinel.classList.add("hidden");
      catalogSection.classList.remove("hidden");
      categoriesSection.classList.remove("hidden");
      filtersSection.classList.remove("hidden");
      recommendSection.classList.add("hidden");
      catalogHeading.textContent = query ? `Results for "${query}"` : activeCategory;
      moviesGrid.innerHTML = filtered.map(renderCard).join("") || `<p class="empty-hint">No titles found.</p>`;
      moviesStatus.textContent = `Showing ${filtered.length} titles`;
      if (query.length >= 2) {
        catalogSection.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      return;
    }

    catalogSection.classList.add("hidden");
    genreRowsEl.classList.remove("hidden");
    infiniteSentinel.classList.remove("hidden");
    categoriesSection.classList.remove("hidden");
    filtersSection.classList.remove("hidden");
    recommendSection.classList.remove("hidden");
    const seed = hashText(`${user.email || ""}|${user.id || ""}`);
    const scopedCatalog = applyLanguageFilter(allCatalog);
    const freeTitles = scopedCatalog.filter((m) => !m.is_premium);
    const premiumPool = user.plan === "premium" ? scopedCatalog.filter((m) => m.is_premium) : applyLanguageFilter(allPremiumPreview);
    const trending = rotated(scopedCatalog, seed).slice(0, 48);
    const bollywoodTitles = scopedCatalog.filter((m) => {
      const blob = `${m.title || ""} ${(m.genres || []).join(" ")}`.toLowerCase();
      return /(bollywood|hindi|indian|tollywood|kollywood)/.test(blob);
    });
    const tvPicks = scopedCatalog.filter((m) => (m.type || "").toLowerCase() === "tv");
    const moviePicks = scopedCatalog.filter((m) => (m.type || "").toLowerCase() !== "tv");
    const topGenres = topGenresFrom(scopedCatalog, 16);
    const continueWatching = uniqueById([
      ...rotated(tvPicks, seed + 11).slice(0, 20),
      ...rotated(moviePicks, seed + 23).slice(0, 20),
    ]);
    const history = getWatchHistory();
    const watchedGenreSet = new Set(history.flatMap((item) => item.genres || []).map((g) => String(g)));
    const becauseYouWatched = rotated(
      scopedCatalog.filter((item) => (item.genres || []).some((g) => watchedGenreSet.has(g))),
      seed + 51
    ).slice(0, 48);
    const premiumTitles = rotated(premiumPool, seed + 17).slice(0, 40);
    const usedRowIds = new Set();
    const filteredLabel = activeLanguage === "All" ? "" : ` (${activeLanguage})`;
    const genreRows = topGenres
      .map((genre, idx) =>
        sectionRow(
          genre,
          uniqueNotUsed(
            rotated(
              scopedCatalog.filter((m) => (m.genres || []).includes(genre)),
              seed + idx * 7
            ),
            usedRowIds,
            40
          )
        )
      )
      .filter(Boolean);
    let rows = [
      sectionRow(`Trending now${filteredLabel}`, uniqueNotUsed(trending, usedRowIds, 40)),
      sectionRow("Free section", uniqueNotUsed(rotated(freeTitles, seed + 5), usedRowIds, 40)),
      sectionRow("Popular movies", uniqueNotUsed(rotated(moviePicks, seed + 13), usedRowIds, 40)),
      sectionRow("Popular series", uniqueNotUsed(rotated(tvPicks, seed + 19), usedRowIds, 40)),
      sectionRow("Bollywood & Indian cinema", uniqueNotUsed(rotated(bollywoodTitles, seed + 29), usedRowIds, 40)),
      sectionRow("Continue watching picks", uniqueNotUsed(continueWatching, usedRowIds, 40)),
      history.length ? sectionRow("Because you watched", uniqueNotUsed(becauseYouWatched, usedRowIds, 40)) : null,
      sectionRow("Premium section", uniqueNotUsed(premiumTitles, usedRowIds, 40)),
      ...genreRows,
    ].filter(Boolean);
    if (!rows.length) {
      rows = [
        sectionRow("No exact language matches, showing global trending", rotated(allCatalog, seed)),
        sectionRow("Popular movies", rotated(allCatalog.filter((m) => (m.type || "").toLowerCase() !== "tv"), seed + 9)),
      ].filter(Boolean);
    }
    homeRows = rows;
    renderedRowCount = 0;
    genreRowsEl.innerHTML = "";
    appendNextRows();
    if (!homeObserver) {
      while (renderedRowCount < homeRows.length) {
        appendNextRows();
      }
    }
    recommendSection.classList.remove("hidden");
    recommendStatus.textContent =
      user.plan === "premium"
        ? "Your premium access includes full catalog."
        : "Upgrade to premium to unlock the full catalog.";
    recommendScroll.innerHTML = uniqueById([
      ...rotated(scopedCatalog, seed + 3).slice(0, 25),
      ...rotated(bollywoodTitles, seed + 37).slice(0, 15),
      ...rotated(tvPicks, seed + 41).slice(0, 15),
    ])
      .slice(0, 55)
      .map(renderCard)
      .join("");
    moviesStatus.textContent = `${scopedCatalog.length}+ titles in current filter. Scroll to load more rows.`;
  }

  function hideSuggestions() {
    searchSuggestions.classList.add("hidden");
    searchSuggestions.innerHTML = "";
  }

  function renderSuggestions(items) {
    if (!items.length) {
      hideSuggestions();
      return;
    }
    searchSuggestions.innerHTML = items
      .slice(0, 8)
      .map(
        (item) => `
          <button type="button" class="suggestion-item" data-title="${(item.title || "").replace(/"/g, "&quot;")}">
            <div>${item.title || "Untitled"}</div>
            <div class="suggestion-sub">${item.year || "N/A"} · ${(item.type || "movie").toUpperCase()}</div>
          </button>
        `
      )
      .join("");
    searchSuggestions.classList.remove("hidden");
  }

  async function loadSuggestions(query) {
    if (query.length < 2) {
      hideSuggestions();
      return;
    }
    const local = allCatalog.filter((m) => (m.title || "").toLowerCase().includes(query.toLowerCase())).slice(0, 8);
    if (local.length >= 5) {
      renderSuggestions(local);
      return;
    }
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(query)}&plan=${encodeURIComponent(user.plan || "free")}`);
      const data = await res.json();
      renderSuggestions((data.results || []).slice(0, 8));
    } catch {
      renderSuggestions(local);
    }
  }

  async function loadAllCatalog(plan, forceRefresh = false) {
    let page = 1;
    const out = [];
    while (page <= 20) {
      const refreshFlag = forceRefresh && page === 1 ? "&refresh=1" : "";
      const res = await fetch(`/api/catalog?plan=${encodeURIComponent(plan)}&page=${page}&limit=120${refreshFlag}`);
      const data = await res.json();
      out.push(...(data.results || []));
      if (!data.has_next) break;
      page += 1;
    }
    return out;
  }

  async function runSearch() {
    const query = searchInput.value.trim();
    hideSuggestions();
    if (query.length < 2) {
      searchResults = null;
      renderBrowse();
      return;
    }
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(query)}&plan=${encodeURIComponent(user.plan || "free")}`);
      const data = await res.json();
      searchResults = data.results || [];
    } catch {
      searchResults = null;
    }
    renderBrowse();
  }

  searchButton.addEventListener("click", runSearch);
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runSearch();
    }
  });
  searchInput.addEventListener("input", () => {
    const value = searchInput.value.trim();
    if (!value) {
      searchResults = null;
      hideSuggestions();
      renderBrowse();
      return;
    }
    clearTimeout(suggestTimer);
    suggestTimer = setTimeout(() => {
      loadSuggestions(value);
    }, 220);
  });
  searchSuggestions.addEventListener("click", (event) => {
    const button = event.target.closest(".suggestion-item");
    if (!button) return;
    const title = button.dataset.title || "";
    searchInput.value = title;
    runSearch();
  });
  document.addEventListener("click", (event) => {
    if (event.target === searchInput || searchSuggestions.contains(event.target)) return;
    hideSuggestions();
  });

  function onClick(event) {
    const button = event.target.closest(".play-btn");
    if (!button) return;
    const movie = getMovieById(button.dataset.id);
    if (movie) openPlayer(movie);
  }

  genreRowsEl.addEventListener("click", onClick);
  recommendScroll.addEventListener("click", onClick);
  moviesGrid.addEventListener("click", onClick);
  closePlayerBtn.addEventListener("click", closePlayer);
  playerBackdrop.addEventListener("click", closePlayer);
  seasonSelect.addEventListener("change", () => {
    renderEpisodeOptions(Number(seasonSelect.value));
  });
  playEpisodeBtn.addEventListener("click", async () => {
    if (!activeSeriesMovie || !activeSeriesSeasons.length) return;
    const seasonNum = Number(seasonSelect.value);
    const episodeNum = Number(episodeSelect.value);
    const season = activeSeriesSeasons.find((s) => Number(s.season) === seasonNum);
    const episode = (season?.episodes || []).find((e) => Number(e.episode) === episodeNum);
    if (!episode) {
      playerStatus.textContent = "Could not find selected episode.";
      return;
    }
    const queryTitle = `${activeSeriesMovie.title} season ${seasonNum} episode ${episodeNum}`;
    playerStatus.textContent = "Loading selected episode...";
    await playUrlForTitle(queryTitle);
  });

  if (infiniteSentinel && "IntersectionObserver" in window) {
    homeObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const query = searchInput.value.trim();
          if (query || activeCategory !== "All") return;
          appendNextRows();
        });
      },
      { root: null, rootMargin: "420px 0px 420px 0px", threshold: 0.01 }
    );
    homeObserver.observe(infiniteSentinel);
  }

  (async function init() {
    moviesStatus.textContent = "Loading catalog from RapidAPI...";
    try {
      allCatalog = await loadAllCatalog(user.plan || "free", true);
      if (!allCatalog.length) {
        moviesStatus.textContent = "No titles available. Check RapidAPI key and host.";
        return;
      }
      allPremiumPreview = [];
      renderCategoryButtons(topGenresFrom(allCatalog, 16));
      renderLanguageButtons();
      renderBrowse();
    } catch {
      moviesStatus.textContent = "Network error while loading catalog.";
    }
  })();

  if (savedSession) {
    const ping = () =>
      fetch("/api/session/ping", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: savedSession }),
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (!data || !data.user) return;
          Object.assign(user, data.user);
          localStorage.setItem("netflixCloneUser", JSON.stringify(user));
          renderWelcome();
        })
        .catch(() => {});
    ping();
    setInterval(ping, 30_000);
  }
}
