const savedUser = localStorage.getItem("netflixCloneUser");
const savedSession = localStorage.getItem("netflixCloneSession");

if (!savedUser || !savedSession) {
  window.location.href = "/signin";
} else {
  const user = JSON.parse(savedUser);
  const currentPlanEl = document.getElementById("current-plan");
  const grid = document.getElementById("plans-grid");
  const msg = document.getElementById("plan-message");

  const PLANS = [
    {
      id: "free",
      name: "Free",
      price: "₹0",
      desc: "Browse the catalog. Playback is locked until you take a paid plan.",
    },
    {
      id: "m149",
      name: "Mobile",
      price: "₹149 / month",
      desc: "Unlock playback on supported devices. Great for starters.",
    },
    {
      id: "m349",
      name: "Standard",
      price: "₹349 / month",
      desc: "More screens and a smoother experience for everyday watching.",
    },
    {
      id: "y5000",
      name: "Yearly",
      price: "₹5000 / year",
      desc: "Best value plan for the whole year.",
    },
  ];

  function planLabel(p) {
    const plan = String(p || "free").toLowerCase();
    if (plan === "free") return "FREE";
    if (plan === "m149") return "₹149/MO";
    if (plan === "m349") return "₹349/MO";
    if (plan === "y5000") return "₹5000/YR";
    if (plan === "premium") return "PREMIUM";
    return plan.toUpperCase();
  }

  function isPaid(plan) {
    return ["m149", "m349", "y5000", "premium"].includes(String(plan || "free").toLowerCase());
  }

  function isExpired(expiresAt) {
    const exp = Number(expiresAt || 0);
    return exp ? exp * 1000 < Date.now() : false;
  }

  function setMessage(text) {
    msg.textContent = text || "";
  }

  function renderCurrent(status) {
    const label = planLabel(status.plan);
    if (status.plan === "free") {
      currentPlanEl.textContent = `Current plan: ${label}. Playback is locked on Free.`;
      return;
    }
    if (!status.active) {
      currentPlanEl.textContent = `Current plan: ${label} (expired). Choose a plan to watch again.`;
      return;
    }
    const days = Number.isFinite(status.remaining_days) ? status.remaining_days : null;
    currentPlanEl.textContent = `Current plan: ${label}. Validity: ${days !== null ? `${days} day(s) left` : "active"}.`;
  }

  function renderTiles(status) {
    grid.innerHTML = PLANS.map((p) => {
      const paidLocked = isPaid(status.plan) && status.active;
      const isCurrent = String(status.plan) === p.id && (p.id === "free" || status.active);
      const btnLabel = isCurrent ? "Current plan" : paidLocked ? "Already having a plan" : "Select plan";
      const btnClass = isCurrent || paidLocked ? "plan-btn secondary" : "plan-btn";
      const disabledAttr = isCurrent || paidLocked ? "disabled" : "";
      return `
        <article class="plan-tile" data-plan="${p.id}">
          <div class="plan-name">${p.name}</div>
          <div class="plan-price">${p.price}</div>
          <div class="plan-desc">${p.desc}</div>
          <button type="button" class="${btnClass}" ${disabledAttr}>${btnLabel}</button>
        </article>
      `;
    }).join("");

    grid.querySelectorAll(".plan-tile button").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const tile = e.target.closest(".plan-tile");
        if (!tile) return;
        const desired = tile.getAttribute("data-plan");
        await selectPlan(desired);
      });
    });
  }

  async function fetchStatus() {
    const res = await fetch(`/api/plan/status?session_id=${encodeURIComponent(savedSession)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not load plan status.");
    return data;
  }

  async function selectPlan(desired) {
    setMessage("");
    let status;
    try {
      status = await fetchStatus();
    } catch (e) {
      setMessage(e.message || "Please sign in again.");
      return;
    }

    if (isPaid(status.plan) && status.active) {
      setMessage("Already having a plan.");
      return;
    }

    if (desired === "free") {
      setMessage("Free plan selected. You can browse, but playback stays locked until you take a paid plan.");
      user.plan = "free";
      user.plan_expires_at = null;
      localStorage.setItem("netflixCloneUser", JSON.stringify(user));
      renderCurrent({ ...status, plan: "free", active: false, plan_expires_at: null });
      renderTiles({ ...status, plan: "free", active: false, plan_expires_at: null });
      return;
    }

    try {
      const res = await fetch("/api/plan/upgrade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: savedSession, plan: desired }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.error || "Could not update plan.");
        return;
      }
      Object.assign(user, data.user);
      localStorage.setItem("netflixCloneUser", JSON.stringify(user));
      const nextStatus = await fetchStatus();
      renderCurrent(nextStatus);
      renderTiles(nextStatus);
      setMessage("Plan activated. You can watch now.");
    } catch {
      setMessage("Network error. Please try again.");
    }
  }

  (async function init() {
    try {
      const status = await fetchStatus();
      renderCurrent(status);
      renderTiles(status);
      if (isExpired(user.plan_expires_at)) {
        setMessage("Your plan expired. Choose a plan to continue watching.");
      }
    } catch (e) {
      setMessage(e.message || "Could not load plans.");
    }
  })();
}

