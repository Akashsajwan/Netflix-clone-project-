const slider = document.getElementById("trending-slider");
const PLACEHOLDER = "https://via.placeholder.com/300x450/1f1f1f/b3b3b3?text=No+Poster";

function initFaqAccordion() {
  const items = Array.from(document.querySelectorAll("[data-faq]"));
  if (!items.length) return;

  items.forEach((item) => {
    const btn = item.querySelector("button.faq");
    const answer = item.querySelector(".faq-answer");
    if (!btn || !answer) return;

    btn.addEventListener("click", () => {
      const isOpen = item.classList.toggle("open");
      btn.setAttribute("aria-expanded", String(isOpen));
      answer.hidden = !isOpen;
    });
  });
}

async function loadTrending() {
  if (!slider) return;
  slider.innerHTML = "<p>Loading trending titles...</p>";
  try {
    const response = await fetch("/api/home-trending");
    const data = await response.json();
    const titles = (data.results || []).slice(0, 10);
    if (!titles.length) {
      slider.innerHTML = "<p>Trending titles are unavailable right now.</p>";
      return;
    }

    slider.innerHTML = titles
      .map(
        (item, idx) => `
        <a class="card" href="/signup" title="Sign up to watch ${item.title}">
          <img src="${item.poster || PLACEHOLDER}" alt="${item.title}">
          <div class="number">${idx + 1}</div>
        </a>
      `
      )
      .join("");
  } catch {
    slider.innerHTML = "<p>Could not load trending titles.</p>";
  }
}

loadTrending();
initFaqAccordion();
