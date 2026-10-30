
const tg = window.Telegram?.WebApp;

if (tg) {
  tg.ready();
  tg.expand();
}

const $ = (id) => document.getElementById(id);

const claimBtn = $("claimMining");
const watchBtn = $("watchAd");
const startBtn = $("startMining");

function getHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": tg?.initData || ""
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...getHeaders(),
      ...(options.headers || {})
    }
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.detail || "Request failed");
  }

  return data;
}

async function loadProfile() {
  const status = $("miningStatus");

  if (!tg?.initData) {
    status.textContent = "Telegram Mini App থেকে খুলুন।";
    return;
  }

  try {
    const user = await api("/api/me");
    $("balance").textContent =
      Number(user.balance || 0).toLocaleString();
  } catch (error) {
    status.textContent = error.message;
  }
}

async function startMining() {
  const status = $("miningStatus");
  startBtn.disabled = true;

  try {
    await api("/api/mining/start", {
      method: "POST",
      body: "{}"
    });

    status.textContent = "Mining চালু হয়েছে।";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    startBtn.disabled = false;
  }
}

async function showRewardedAd(placement, button, status) {
  if (!tg?.initData) {
    status.textContent = "Telegram Mini App থেকে খুলুন।";
    return;
  }

  button.disabled = true;

  try {
    const session = await api("/api/ads/start", {
      method: "POST",
      body: JSON.stringify({ placement })
    });

    if (typeof window.show_12152538 !== "function") {
      throw new Error("Monetag SDK লোড হয়নি।");
    }

    status.textContent = "বিজ্ঞাপন লোড হচ্ছে...";

    await window.show_12152538();

    status.textContent =
      "বিজ্ঞাপন প্রক্রিয়া শেষ। সার্ভার যাচাই যুক্ত না হওয়া পর্যন্ত Cherry যোগ হবে না।";

  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

startBtn?.addEventListener("click", startMining);

claimBtn?.addEventListener("click", () => {
  showRewardedAd(
    "mining_claim",
    claimBtn,
    $("miningStatus")
  );
});

watchBtn?.addEventListener("click", () => {
  showRewardedAd(
    "watch_ad",
    watchBtn,
    $("adStatus")
  );
});

async function loadTasks() {
  if (!tg?.initData) return;

  try {
    const tasks = await api("/api/tasks");
    const container = $("tasks");

    container.innerHTML = "";

    tasks.forEach((task) => {
      const row = document.createElement("div");
      row.className = "task-item";

      const title = document.createElement("span");
      title.textContent = task.title;

      const reward = document.createElement("small");
      reward.textContent = task.reward + " Cherry";

      row.append(title, reward);
      container.append(row);
    });

  } catch (error) {
    $("tasks").textContent = error.message;
  }
}

loadProfile();
loadTasks();
