
(() => {
    "use strict";

    // ==========================================
    // CHERRY MINING - FRONTEND APP
    // ==========================================

    const tg = window.Telegram?.WebApp;

    tg?.ready();
    tg?.expand();

    const $ = (id) => document.getElementById(id);

    const API_HEADERS = {
        "Content-Type": "application/json"
    };

    if (tg?.initData) {
        API_HEADERS["X-Telegram-Init-Data"] = tg.initData;
    }

    const state = {
        user: null,
        joined: false,
        mining: null,
        miningSyncTime: Date.now(),
        miningBaseEarned: 0,
        miningTimer: null,
        busy: false,
        tasks: [],
        referrals: [],
        withdrawals: [],
        adBusy: false
    };

    // ==========================================
    // HELPERS
    // ==========================================

    function setText(id, value) {
        const el = $(id);
        if (el) el.textContent = value ?? "";
    }

    function showStatus(id, message, error = false) {
        const el = $(id);
        if (!el) return;

        el.textContent = message;
        el.style.color = error ? "#ff8b9d" : "#ffb4d2";
    }

    function formatCherry(value) {
        const number = Number(value || 0);

        return number.toLocaleString("en-US", {
            minimumFractionDigits: 0,
            maximumFractionDigits: 8
        });
    }

    function formatUSD(value) {
        return "$" + Number(value || 0).toFixed(4);
    }

    function formatDate(value) {
        if (!value) return "N/A";

        const date = new Date(value);

        if (Number.isNaN(date.getTime())) return "N/A";

        return date.toLocaleString();
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    function escapeHTML(value) {
        return String(value ?? "").replace(/[&<>"']/g, char => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#039;"
        })[char]);
    }

    // ==========================================
    // API CONNECTION
    // ==========================================

    async function api(path, method = "GET", body = null) {
        const options = {
            method,
            headers: { ...API_HEADERS }
        };

        if (body !== null) {
            options.body = JSON.stringify(body);
        }

        let response;

        try {
            response = await fetch(path, options);
        } catch (error) {
            throw new Error("Network connection failed. Please try again.");
        }

        let data = {};

        try {
            data = await response.json();
        } catch {
            data = {};
        }

        if (!response.ok) {
            let message = data.detail || data.message || "Something went wrong.";

            if (typeof message !== "string") {
                message = JSON.stringify(message);
            }

            throw new Error(message);
        }

        return data;
    }

    // ==========================================
    // TELEGRAM USER
    // ==========================================

    function loadTelegramUser() {
        const user = tg?.initDataUnsafe?.user;

        if (user) {
            state.user = user;
            setText("userName", user.first_name || "Telegram User");
        } else {
            setText("userName", "Telegram User");
        }
    }

    // ==========================================
    // NAVIGATION
    // ==========================================

    const navButtons = document.querySelectorAll(".nav-btn");
    const pages = document.querySelectorAll(".page");

    function showPage(pageId) {
        pages.forEach(page => {
            page.classList.toggle("active", page.id === pageId);
        });

        navButtons.forEach(button => {
            button.classList.toggle(
                "active",
                button.dataset.page === pageId
            );
        });

        if (pageId === "tasksPage") loadTasks();
        if (pageId === "referralPage") loadReferrals();
        if (pageId === "historyPage") loadWithdrawals();
    }

    navButtons.forEach(button => {
        button.addEventListener("click", () => {
            showPage(button.dataset.page);
        });
    });

    // ==========================================
    // CHANNEL VERIFICATION
    // ==========================================

    function updateChannelUI(joined) {
        state.joined = Boolean(joined);

        const section = $("channelSection");
        const miningSection = $("miningSection");

        if (section) {
            section.style.display = joined ? "none" : "block";
        }

        if (miningSection) {
            miningSection.style.opacity = joined ? "1" : "0.55";
        }

        setText(
            "channelStatus",
            joined
                ? "Channel membership verified."
                : "Join our official Telegram channel first."
        );
    }

    async function checkChannel() {
        try {
            const data = await api("/api/channel/status");

            const joined =
                data.joined === true ||
                data.is_member === true ||
                data.verified === true;

            updateChannelUI(joined);

            return joined;
        } catch (error) {
            updateChannelUI(false);
            return false;
        }
    }

    const joinChannel = $("joinChannel");

    if (joinChannel) {
        joinChannel.addEventListener("click", () => {
            const url = "https://t.me/CherryMiningChannel";

            if (tg?.openTelegramLink) {
                tg.openTelegramLink(url);
            } else {
                window.open(url, "_blank");
            }
        });
    }

    const verifyChannel = $("verifyChannel");

    if (verifyChannel) {
        verifyChannel.addEventListener("click", async () => {
            verifyChannel.disabled = true;

            try {
                const data = await api("/api/channel/verify", "POST");

                if (
                    data.joined === true ||
                    data.is_member === true ||
                    data.verified === true ||
                    data.success === true
                ) {
                    updateChannelUI(true);
                    showStatus("channelStatus", "Channel verified successfully!");

                    await refreshAll();
                } else {
                    updateChannelUI(false);
                    showStatus(
                        "channelStatus",
                        "Channel membership not found. Join first.",
                        true
                    );
                }
            } catch (error) {
                showStatus("channelStatus", error.message, true);
            } finally {
                verifyChannel.disabled = false;
            }
        });
    }

    // ==========================================
    // BALANCE
    // ==========================================

    function updateBalance(data) {
        setText("balance", formatCherry(data.balance));
        setText("usdBalance", formatUSD(data.usd_balance));
    }

    // ==========================================
    // MINING
    // ==========================================

    function renderMining(data) {
        state.mining = data;
        state.miningSyncTime = Date.now();

        state.miningBaseEarned = Number(
            data.mining_earned ?? data.earned ?? 0
        );

        const started = data.mining_started;
        const ends = data.mining_ends || data.mining_end_at;

        const active = Boolean(
            data.mining_active || data.active
        );

        const completed = Boolean(
            data.mining_completed || data.completed
        );

        const reward = Number(data.mining_reward || 500);

        const earned = state.miningBaseEarned;

        setText("miningEarned", formatCherry(earned));
        setText(
            "miningUsd",
            formatUSD(data.mining_earned_usd)
        );

        const progress = Math.min(
            100,
            Math.max(0, Number(data.mining_progress || 0))
        );

        const progressBar = $("miningProgress");

        if (progressBar) {
            progressBar.style.width = progress + "%";
        }

        setText(
            "miningProgressText",
            progress.toFixed(2) + "%"
        );

        const startButton = $("startMining");
        const claimButton = $("claimMining");

        if (startButton) {
            startButton.disabled = active || !state.joined;
        }

        if (claimButton) {
            claimButton.disabled = earned <= 0 || !state.joined;
        }

        if (active) {
            setText("miningStatus", "Mining is active.");
        } else if (completed && earned > 0) {
            setText("miningStatus", "Mining completed. Claim your reward.");
        } else {
            setText("miningStatus", "Mining is not active.");
        }

        updateMiningTimer(ends, active, started, reward);
    }

    function updateMiningTimer(ends, active, started, reward) {
        if (state.miningTimer) {
            clearInterval(state.miningTimer);
            state.miningTimer = null;
        }

        function tick() {
            if (!ends) {
                setText("miningTimer", "00:00:00");
                return;
            }

            const endTime = new Date(ends).getTime();
            const remaining = Math.max(0, endTime - Date.now());

            if (active && remaining > 0) {
                const totalSeconds = Math.floor(remaining / 1000);

                const hours = Math.floor(totalSeconds / 3600);
                const minutes = Math.floor((totalSeconds % 3600) / 60);
                const seconds = totalSeconds % 60;

                setText(
                    "miningTimer",
                    [hours, minutes, seconds]
                        .map(v => String(v).padStart(2, "0"))
                        .join(":")
                );

                const elapsed = Math.max(
                    0,
                    (Date.now() - state.miningSyncTime) / 1000
                );

                const liveEarned = Math.min(
                    Number(reward || 500),
                    state.miningBaseEarned +
                    (elapsed * Number(reward || 500) / 86400)
                );

                setText("miningEarned", formatCherry(liveEarned));

                const usdRate = Number(
                    state.mining?.cherry_per_usd || 10000
                );

                setText(
                    "miningUsd",
                    formatUSD(liveEarned / usdRate)
                );

                const totalDuration = started
                    ? endTime - new Date(started).getTime()
                    : 86400000;

                const progress = totalDuration > 0
                    ? Math.min(
                        100,
                        Math.max(
                            0,
                            ((Date.now() - new Date(started || Date.now()).getTime()) /
                                totalDuration) * 100
                        )
                    )
                    : 0;

                const bar = $("miningProgress");

                if (bar) bar.style.width = progress + "%";

                setText(
                    "miningProgressText",
                    progress.toFixed(2) + "%"
                );
            } else {
                setText(
                    "miningTimer",
                    remaining <= 0 ? "Completed" : "00:00:00"
                );
            }
        }

        tick();
        state.miningTimer = setInterval(tick, 1000);
    }

    async function loadMining() {
        try {
            const data = await api("/api/mining/status");
            renderMining(data);
        } catch (error) {
            if (state.mining) {
                renderMining(state.mining);
            }

            showStatus("miningStatus", error.message, true);
        }
    }

    const startMining = $("startMining");

    if (startMining) {
        startMining.addEventListener("click", async () => {
            if (!state.joined) {
                showStatus(
                    "miningStatus",
                    "Join the official channel first.",
                    true
                );
                return;
            }

            startMining.disabled = true;

            try {
                const data = await api("/api/mining/start", "POST");

                showStatus(
                    "miningStatus",
                    data.message || "Mining started successfully!"
                );

                await refreshAll();
            } catch (error) {
                showStatus("miningStatus", error.message, true);
            } finally {
                startMining.disabled = false;
            }
        });
    }

    const claimMining = $("claimMining");

    if (claimMining) {
        claimMining.addEventListener("click", async () => {
            claimMining.disabled = true;

            try {
                const data = await api("/api/mining/claim", "POST");

                showStatus(
                    "miningStatus",
                    data.message || "Mining reward claimed successfully!"
                );

                await refreshAll();
            } catch (error) {
                showStatus("miningStatus", error.message, true);
            } finally {
                claimMining.disabled = false;
            }
        });
    }

    // ==========================================
    // DAILY BONUS
    // ==========================================

    async function updateDailyStatus() {
        try {
            const data = await api("/api/me");

            const next = data.daily_next_at
                ? new Date(data.daily_next_at).getTime()
                : 0;

            const available = !next || next <= Date.now();

            const button = $("dailyBonus");

            if (button) {
                button.disabled = !available;
            }

            setText(
                "dailyStatus",
                available
                    ? "Your daily bonus is available!"
                    : "Next bonus: " + formatDate(data.daily_next_at)
            );
        } catch (error) {
            showStatus("dailyStatus", error.message, true);
        }
    }

    const dailyBonus = $("dailyBonus");

    if (dailyBonus) {
        dailyBonus.addEventListener("click", async () => {
            dailyBonus.disabled = true;

            try {
                const data = await api("/api/daily/claim", "POST");

                showStatus(
                    "dailyStatus",
                    data.message || "Daily bonus claimed!"
                );

                await refreshAll();
            } catch (error) {
                showStatus("dailyStatus", error.message, true);
                dailyBonus.disabled = false;
            }
        });
    }

    // ==========================================
    // MONETAG TASKS
    // ==========================================

    async function loadTasks() {
        const container = $("taskList");
        if (!container) return;

        container.innerHTML =
            '<div class="empty-state">Loading tasks...</div>';

        try {
            const data = await api("/api/tasks");

            state.tasks = Array.isArray(data)
                ? data
                : (data.tasks || []);

            if (!state.tasks.length) {
                container.innerHTML =
                    '<div class="empty-state">No tasks available.</div>';
                return;
            }

            container.innerHTML = "";

            state.tasks.forEach(task => {
                const item = document.createElement("div");

                item.className = "task-item";

                const title = escapeHTML(
                    task.title || `Task ${task.id}`
                );

                const description = escapeHTML(
                    task.description || "Complete this task to earn Cherry."
                );

                const reward = escapeHTML(task.reward ?? 50);

                const completed = Boolean(
                    task.completed || task.claimed
                );

                item.innerHTML = `
                    <h3>${title}</h3>
                    <p>${description}</p>
                    <p>Reward: ${reward} Cherry</p>
                    <button class="primary task-action"
                        ${completed ? "disabled" : ""}
                        type="button">
                        ${completed ? "Completed" : "Start Task"}
                    </button>
                    <p class="status task-status"></p>
                `;

                const button = item.querySelector(".task-action");
                const status = item.querySelector(".task-status");

                button.addEventListener("click", async () => {
                    await startAdTask(task, button, status);
                });

                container.appendChild(item);
            });

        } catch (error) {
            container.innerHTML = "";
            showStatus("taskList", error.message, true);
        }
    }

    async function startAdTask(task, button, status) {
        if (state.adBusy) return;

        if (!state.joined) {
            status.textContent = "Join the official channel first.";
            return;
        }

        state.adBusy = true;
        button.disabled = true;
        button.textContent = "Preparing Ad...";

        try {
            const session = await api(
                `/api/ads/session?task_id=${encodeURIComponent(task.id)}`,
                "POST"
            );

            if (!session.session_id) {
                throw new Error("Ad session could not be created.");
            }

            if (typeof window.show_12152538 !== "function") {
                throw new Error(
                    "Monetag SDK is not ready. Please reload and try again."
                );
            }

            status.textContent = "Please watch the advertisement.";

            button.textContent = "Advertisement Running...";

            try {
                await window.show_12152538({
                    ymid: session.ymid
                });
            } catch (adError) {
                console.warn("Monetag SDK:", adError);
            }

            status.textContent =
                "Waiting for ad verification. Please wait...";

            button.textContent = "Verifying...";

            let verified = false;

            for (let i = 0; i < 45; i++) {
                await sleep(2000);

                const result = await api(
                    `/api/ads/session/${encodeURIComponent(session.session_id)}`
                );

                if (result.status === "valued") {
                    verified = true;
                    break;
                }

                if (
                    result.status === "rejected" ||
                    result.status === "non_valued"
                ) {
                    throw new Error(
                        "Advertisement was not approved. Try again later."
                    );
                }
            }

            if (!verified) {
                throw new Error(
                    "Ad verification is still pending. Please try again later."
                );
            }

            const completed = await api(
                `/api/tasks/${encodeURIComponent(task.id)}/complete`,
                "POST",
                {
                    session_id: session.session_id
                }
            );

            status.textContent =
                completed.message || "Task completed successfully!";

            button.textContent = "Completed";

            await refreshAll();
            await loadTasks();

        } catch (error) {
            status.textContent = error.message;
            button.disabled = false;
            button.textContent = "Try Again";
        } finally {
            state.adBusy = false;
        }
    }

    // ==========================================
    // WATCH AD BUTTON
    // ==========================================

    const watchAd = $("watchAd");

    if (watchAd) {
        watchAd.addEventListener("click", async () => {
            showStatus(
                "adStatus",
                "Please complete an available task from the Tasks page."
            );

            showPage("tasksPage");
        });
    }

    // ==========================================
    // REFERRAL
    // ==========================================

    async function loadReferrals() {
        try {
            const data = await api("/api/referrals");

            state.referrals = data.referrals || [];

            setText("refCount", data.total_referrals ?? data.referral_count ?? 0);

            setText(
                "approvedReferrals",
                data.approved_referrals ?? data.approved ?? 0
            );

            setText(
                "pendingReferrals",
                data.pending_referrals ?? data.pending ?? 0
            );

            setText(
                "referralBonus",
                formatCherry(data.total_bonus ?? data.referral_bonus ?? 0)
            );

            renderReferralList(state.referrals);

        } catch (error) {
            showStatus("referralList", error.message, true);
        }
    }

    function renderReferralList(referrals) {
        const container = $("referralList");
        if (!container) return;

        if (!referrals.length) {
            container.innerHTML =
                '<div class="empty-state">No referrals yet.</div>';
            return;
        }

        container.innerHTML = "";

        referrals.forEach(ref => {
            const item = document.createElement("div");

            item.className = "referral-item";

            const name = escapeHTML(
                ref.first_name || ref.username || "Telegram User"
            );

            const status = String(ref.status || "pending").toLowerCase();

            const statusLabel = escapeHTML(status);

            item.innerHTML = `
                <h3>${name}</h3>
                <p>Joined: ${escapeHTML(formatDate(ref.referred_at))}</p>
                <p>Bonus: ${escapeHTML(formatCherry(ref.bonus))} Cherry</p>
                <span class="referral-status ${statusLabel}">
                    ${statusLabel.toUpperCase()}
                </span>
            `;

            container.appendChild(item);
        });
    }

    async function processReferralStart() {
        const params = new URLSearchParams(window.location.search);

        const startParam =
            tg?.initDataUnsafe?.start_param ||
            params.get("startapp") ||
            params.get("start") ||
            params.get("tgWebAppStartParam");

        if (!startParam) return;

        try {
            await api(
                `/api/referral/claim?start=${encodeURIComponent(startParam)}`,
                "POST"
            );
        } catch (error) {
            console.warn("Referral attribution:", error.message);
        }
    }

    const copyReferral = $("copyReferral");

    if (copyReferral) {
        copyReferral.addEventListener("click", async () => {
            const input = $("referralLink");

            if (!input || !input.value) {
                showStatus("referralList", "Referral link not available.", true);
                return;
            }

            try {
                await navigator.clipboard.writeText(input.value);

                showStatus("referralList", "Referral link copied!");
            } catch (error) {
                input.select();

                const copied = document.execCommand("copy");

                showStatus(
                    "referralList",
                    copied ? "Referral link copied!" : "Copy failed.",
                    !copied
                );
            }
        });
    }

    // ==========================================
    // WALLET
    // ==========================================

    async function saveWallet() {
        const input = $("walletAddress");

        if (!input) return;

        const address = input.value.trim();

        if (!address) {
            showStatus("walletStatus", "Enter your wallet address.", true);
            return;
        }

        try {
            const data = await api("/api/wallet", "POST", {
                address
            });

            showStatus(
                "walletStatus",
                data.message || "Wallet address saved successfully!"
            );

            createVerifyWalletButton();

        } catch (error) {
            showStatus("walletStatus", error.message, true);
        }
    }

    const saveWalletButton = $("saveWallet");

    if (saveWalletButton) {
        saveWalletButton.addEventListener("click", saveWallet);
    }

    function createVerifyWalletButton() {
        if ($("verifyWallet")) return;

        const saveButton = $("saveWallet");
        if (!saveButton) return;

        const button = document.createElement("button");

        button.id = "verifyWallet";
        button.className = "secondary";
        button.type = "button";
        button.textContent = "Verify Wallet";

        saveButton.insertAdjacentElement("afterend", button);

        button.addEventListener("click", verifyWallet);
    }

    async function verifyWallet() {
        const input = $("walletAddress");

        const address = input?.value.trim();

        if (!address) {
            showStatus("walletStatus", "Enter your wallet address first.", true);
            return;
        }

        if (!window.ethereum) {
            showStatus(
                "walletStatus",
                "Please open this app in a wallet browser such as MetaMask.",
                true
            );
            return;
        }

        const button = $("verifyWallet");

        if (button) button.disabled = true;

        try {
            const challenge = await api(
                "/api/wallet/verification/challenge",
                "POST",
                { address }
            );

            if (!challenge.message) {
                throw new Error("Wallet verification message not received.");
            }

            const accounts = await window.ethereum.request({
                method: "eth_requestAccounts"
            });

            const connectedAddress = accounts?.[0];

            if (
                !connectedAddress ||
                connectedAddress.toLowerCase() !== address.toLowerCase()
            ) {
                throw new Error(
                    "Connected wallet does not match the saved address."
                );
            }

            const signature = await window.ethereum.request({
                method: "personal_sign",
                params: [challenge.message, connectedAddress]
            });

            const result = await api(
                "/api/wallet/verification/confirm",
                "POST",
                {
                    address,
                    message: challenge.message,
                    signature
                }
            );

            showStatus(
                "walletStatus",
                result.message || "Wallet verified successfully!"
            );

        } catch (error) {
            showStatus("walletStatus", error.message, true);
        } finally {
            if (button) button.disabled = false;
        }
    }

    // ==========================================
    // WITHDRAWAL
    // ==========================================

    const withdrawButton = $("withdrawButton");

    if (withdrawButton) {
        withdrawButton.addEventListener("click", async () => {
            const amount = Number($("withdrawAmount")?.value);

            const walletAddress = $("walletAddress")?.value.trim();

            if (!amount || amount <= 0) {
                showStatus("withdrawStatus", "Enter a valid amount.", true);
                return;
            }

            if (amount < 10000) {
                showStatus(
                    "withdrawStatus",
                    "Minimum withdrawal is 10,000 Cherry.",
                    true
                );
                return;
            }

            if (!walletAddress) {
                showStatus(
                    "withdrawStatus",
                    "Save your wallet address first.",
                    true
                );
                return;
            }

            withdrawButton.disabled = true;

            try {
                const data = await api("/api/withdraw", "POST", {
                    amount,
                    wallet_address: walletAddress,
                    network: "BEP20"
                });

                showStatus(
                    "withdrawStatus",
                    data.message || "Withdrawal request submitted!"
                );

                if ($("withdrawAmount")) {
                    $("withdrawAmount").value = "";
                }

                await refreshAll();
                await loadWithdrawals();

            } catch (error) {
                showStatus("withdrawStatus", error.message, true);
            } finally {
                withdrawButton.disabled = false;
            }
        });
    }

    // ==========================================
    // WITHDRAWAL HISTORY
    // ==========================================

    async function loadWithdrawals() {
        const container = $("withdrawalHistory");

        if (!container) return;

        container.innerHTML =
            '<div class="empty-state">Loading withdrawal history...</div>';

        try {
            const data = await api("/api/withdrawals");

            state.withdrawals = Array.isArray(data)
                ? data
                : (data.withdrawals || []);

            if (!state.withdrawals.length) {
                container.innerHTML =
                    '<div class="empty-state">No withdrawal history yet.</div>';
                return;
            }

            container.innerHTML = "";

            state.withdrawals.forEach(item => {
                const card = document.createElement("div");

                card.className = "history-item";

                card.innerHTML = `
                    <p><strong>Amount:</strong>
                        ${escapeHTML(formatCherry(item.amount))} Cherry
                    </p>
                    <p><strong>Status:</strong>
                        ${escapeHTML(item.status || "Pending")}
                    </p>
                    <p><strong>Network:</strong>
                        ${escapeHTML(item.network || "BEP20")}
                    </p>
                    <p><strong>Date:</strong>
                        ${escapeHTML(formatDate(item.created_at))}
                    </p>
                `;

                container.appendChild(card);
            });

        } catch (error) {
            container.innerHTML = "";
            showStatus("withdrawalHistory", error.message, true);
        }
    }

    // ==========================================
    // MAIN REFRESH
    // ==========================================

    async function refreshAll() {
        try {
            const data = await api("/api/me");

            updateBalance(data);

            setText("refCount", data.referral_count ?? 0);

            if (data.referral_link) {
                const input = $("referralLink");

                if (input) {
                    input.value = data.referral_link;
                }
            }

            if (data.wallet_address && $("walletAddress")) {
                $("walletAddress").value = data.wallet_address;
                createVerifyWalletButton();
            }

            renderMining(data);

            await checkChannel();

            if (state.joined) {
                await loadMining();
            }

            await updateDailyStatus();

        } catch (error) {
            console.error("Refresh failed:", error);

            showStatus(
                "miningStatus",
                error.message,
                true
            );
        }
    }

    // ==========================================
    // INITIALIZE APP
    // ==========================================

    async function initialize() {
        loadTelegramUser();

        showPage("homePage");

        await processReferralStart();

        await refreshAll();

        await loadTasks();
        await loadReferrals();
        await loadWithdrawals();

        console.log("Cherry Mining App initialized.");
    }

    initialize();

    // Refresh server data periodically
    setInterval(async () => {
        await refreshAll();
    }, 30000);

})();
