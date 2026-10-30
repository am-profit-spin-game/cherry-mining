
"use strict";

/* =========================================
   CHERRY MINING - FRONTEND CONTROLLER
   ========================================= */

(() => {

    const tg = window.Telegram?.WebApp;

    tg?.ready();
    tg?.expand();

    const BOT_USERNAME = "CherryMiningBot";
    const API_BASE = "";

    const RATE = 10000;
    const MIN_WITHDRAW = 10000;

    const $ = id => document.getElementById(id);

    let userData = null;
    let taskData = [];
    let countdownTimer = null;


    /* =====================================
       API HELPER
       ===================================== */

    async function api(path, method = "GET", body = null) {

        const headers = {
            "Content-Type": "application/json"
        };

        if (tg?.initData) {
            headers["X-Telegram-Init-Data"] = tg.initData;
        }

        const options = {
            method,
            headers
        };

        if (body !== null) {
            options.body = JSON.stringify(body);
        }

        const response = await fetch(API_BASE + path, options);

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(
                data.detail || data.message || "Request failed"
            );
        }

        return data;
    }


    /* =====================================
       MESSAGE HELPER
       ===================================== */

    function message(id, text, type = "") {

        const element = $(id);

        if (!element) return;

        element.textContent = text;
        element.className = "message";

        if (type) {
            element.classList.add(type);
        }
    }


    function setText(id, value) {

        const element = $(id);

        if (element) {
            element.textContent = value ?? "";
        }
    }


    function setValue(id, value) {

        const element = $(id);

        if (element) {
            element.value = value ?? "";
        }
    }


    function formatNumber(value) {

        return Number(value || 0).toLocaleString("en-US", {
            maximumFractionDigits: 4
        });

    }


    function usdValue(cherry) {

        return (Number(cherry || 0) / RATE).toFixed(4);

    }


    /* =====================================
       NAVIGATION
       ===================================== */

    const navButtons = document.querySelectorAll(".nav-btn");

    const pages = document.querySelectorAll(".page");

    function showPage(pageId) {

        pages.forEach(page => {
            page.classList.toggle(
                "active",
                page.id === pageId
            );
        });

        navButtons.forEach(button => {
            button.classList.toggle(
                "active",
                button.dataset.page === pageId
            );
        });

        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });

        if (pageId === "tasksPage") {
            loadTasks();
        }

        if (pageId === "withdrawPage") {
            loadWithdrawals();
            updateWithdrawPreview();
        }

        if (pageId === "profilePage") {
            loadProfile();
        }

    }


    navButtons.forEach(button => {

        button.addEventListener("click", () => {

            showPage(button.dataset.page);

        });

    });


    /* =====================================
       TELEGRAM USER
       ===================================== */

    const telegramUser = tg?.initDataUnsafe?.user;

    function loadTelegramUser() {

        if (!telegramUser) {
            setText("headerUser", "Telegram User");
            return;
        }

        const fullName = [
            telegramUser.first_name,
            telegramUser.last_name
        ].filter(Boolean).join(" ");

        setText("headerUser", fullName || "Telegram User");

        setText("profileName", fullName || "Telegram User");

        setText("telegramId", telegramUser.id || "--");

        if (telegramUser.photo_url) {

            const avatar = $("profileAvatar");

            if (avatar) {

                avatar.innerHTML = "";

                const image = document.createElement("img");

                image.src = telegramUser.photo_url;
                image.alt = "Profile Photo";

                avatar.appendChild(image);

            }

        }

    }


    /* =====================================
       BALANCE
       ===================================== */

    function updateBalance(balance) {

        const amount = Number(balance || 0);

        setText("balance", formatNumber(amount) + " 🍒");

        setText("usdBalance", usdValue(amount));

        setText("withdrawBalance", formatNumber(amount) + " Cherry");

        setText("withdrawUSD", usdValue(amount));

        setText("profileBalance", formatNumber(amount));

        updateWithdrawPreview();

    }


    function updateWithdrawPreview() {

        const amount = Number(
            $("withdrawAmount")?.value || 0
        );

        setText(
            "withdrawPreview",
            "$" + usdValue(amount)
        );

    }


    $("withdrawAmount")?.addEventListener(
        "input",
        updateWithdrawPreview
    );


    /* =====================================
       LOAD USER DATA
       ===================================== */

    async function refreshUser() {

        try {

            const data = await api("/api/me");

            userData = data;

            updateBalance(data.balance);

            setText(
                "refCount",
                formatNumber(data.referral_count)
            );

            setText(
                "profileReferrals",
                formatNumber(data.referral_count)
            );

            setText(
                "miningStatus",
                data.mining_active ? "Active" : "Inactive"
            );

            setText(
                "miningReward",
                formatNumber(data.mining_reward || 0) + " Cherry"
            );

            setText(
                "verificationStatus",
                data.verified ? "Verified" : "Unverified"
            );

            setText(
                "profileVerifyStatus",
                data.verified ? "Verified" : "Not Verified"
            );

            if (data.wallet_address) {

                setValue("profileWallet", data.wallet_address);

                setValue("withdrawWallet", data.wallet_address);

            }

            if (data.referral_link) {

                setValue("referralLink", data.referral_link);

            } else {

                const link =
                    "https://t.me/" +
                    BOT_USERNAME +
                    "?start=" +
                    (telegramUser?.id || "");

                setValue("referralLink", link);

            }

            if (data.mining_end_at) {
                startCountdown(
                    "miningCountdown",
                    data.mining_end_at
                );
            }

            if (data.daily_next_at) {
                startCountdown(
                    "dailyCountdown",
                    data.daily_next_at
                );
            }

        } catch (error) {

            console.error("User API:", error);

            message(
                "miningMessage",
                error.message,
                "error"
            );

        }

    }


    /* =====================================
       COUNTDOWN
       ===================================== */

    function startCountdown(elementId, targetTime) {

        const element = $(elementId);

        if (!element) return;

        function update() {

            const target = new Date(targetTime).getTime();

            const now = Date.now();

            let difference = Math.max(0, target - now);

            if (difference <= 0) {

                element.textContent = "Available Now";

                clearInterval(countdownTimer);

                refreshUser();

                return;

            }

            const hours = Math.floor(
                difference / 3600000
            );

            const minutes = Math.floor(
                (difference % 3600000) / 60000
            );

            const seconds = Math.floor(
                (difference % 60000) / 1000
            );

            element.textContent =
                String(hours).padStart(2, "0") + ":" +
                String(minutes).padStart(2, "0") + ":" +
                String(seconds).padStart(2, "0");

        }

        update();

        clearInterval(countdownTimer);

        countdownTimer = setInterval(update, 1000);

    }


    /* =====================================
       MINING START
       ===================================== */

    $("startMining")?.addEventListener("click", async () => {

        const button = $("startMining");

        button.disabled = true;

        try {

            const data = await api(
                "/api/mining/start",
                "POST"
            );

            message(
                "miningMessage",
                data.message || "Mining started successfully.",
                "success"
            );

            await refreshUser();

        } catch (error) {

            message(
                "miningMessage",
                error.message,
                "error"
            );

        } finally {

            button.disabled = false;

        }

    });


    /* =====================================
       MINING CLAIM
       ===================================== */

    $("claimMining")?.addEventListener("click", async () => {

        const button = $("claimMining");

        button.disabled = true;

        try {

            const data = await api(
                "/api/mining/claim",
                "POST"
            );

            message(
                "miningMessage",
                data.message || "Mining reward claimed.",
                "success"
            );

            await refreshUser();

        } catch (error) {

            message(
                "miningMessage",
                error.message,
                "error"
            );

        } finally {

            button.disabled = false;

        }

    });


    /* =====================================
       DAILY CHECK-IN
       ===================================== */

    $("dailyBonus")?.addEventListener("click", async () => {

        const button = $("dailyBonus");

        button.disabled = true;

        try {

            const data = await api(
                "/api/daily/claim",
                "POST"
            );

            message(
                "dailyMessage",
                data.message || "Daily reward claimed successfully.",
                "success"
            );

            await refreshUser();

        } catch (error) {

            message(
                "dailyMessage",
                error.message,
                "error"
            );

        } finally {

            button.disabled = false;

        }

    });


    /* =====================================
       LOAD TASKS
       ===================================== */

    async function loadTasks() {

        const container = $("taskList");

        if (!container) return;

        try {

            const data = await api("/api/tasks");

            taskData = data.tasks || [];

            container.innerHTML = "";

            taskData.forEach(task => {

                const item = document.createElement("div");

                item.className = "task-item";

                const details = document.createElement("div");

                details.className = "task-details";

                const title = document.createElement("h3");

                title.textContent = task.title;

                const description = document.createElement("p");

                description.textContent =
                    task.description || "Complete this daily task.";

                const reward = document.createElement("span");

                reward.className = "task-reward";

                reward.textContent =
                    formatNumber(task.reward) + " Cherry";

                const button = document.createElement("button");

                button.className = "task-btn";

                button.textContent =
                    task.completed ? "COMPLETED" : "START";

                button.disabled = !!task.completed;

                button.addEventListener("click", () => {
                    completeTask(task.id, button);
                });

                details.appendChild(title);

                details.appendChild(description);

                item.appendChild(details);

                item.appendChild(reward);

                item.appendChild(button);

                container.appendChild(item);

            });

            if (!taskData.length) {

                container.textContent = "No tasks available.";

            }

        } catch (error) {

            container.textContent = error.message;

        }

    }


    /* =====================================
       COMPLETE TASK
       ===================================== */

    async function completeTask(taskId, button) {

        button.disabled = true;

        try {

            const data = await api(
                "/api/tasks/" + encodeURIComponent(taskId) + "/complete",
                "POST"
            );

            message(
                "dailyMessage",
                data.message || "Task completed.",
                "success"
            );

            await refreshUser();

            await loadTasks();

        } catch (error) {

            message(
                "dailyMessage",
                error.message,
                "error"
            );

            button.disabled = false;

        }

    }


    /* =====================================
       MONETAG REWARDED ADS
       ===================================== */

    $("watchAd")?.addEventListener("click", async () => {

        const button = $("watchAd");

        button.disabled = true;

        message(
            "adMessage",
            "Preparing rewarded advertisement..."
        );

        try {

            // Create a server-side reward session first.
            const session = await api(
                "/api/ads/session",
                "POST"
            );

            if (
                typeof window.show_12152538 !== "function"
            ) {

                throw new Error(
                    "Monetag SDK is unavailable."
                );

            }

            await window.show_12152538();

            message(
                "adMessage",
                "Ad session ended. Waiting for server reward verification."
            );

            // Poll server. Browser never credits the reward.
            let verified = false;

            for (let attempt = 0; attempt < 12; attempt++) {

                await new Promise(resolve =>
                    setTimeout(resolve, 5000)
                );

                const result = await api(
                    "/api/ads/session/" +
                    encodeURIComponent(session.session_id)
                );

                if (result.status === "valued") {

                    verified = true;

                    message(
                        "adMessage",
                        "Advertisement reward verified successfully!",
                        "success"
                    );

                    await refreshUser();

                    break;

                }

                if (result.status === "rejected") {

                    throw new Error(
                        "Advertisement reward was not verified."
                    );

                }

            }

            if (!verified) {

                message(
                    "adMessage",
                    "Verification is still pending. Please check again later."
                );

            }

        } catch (error) {

            message(
                "adMessage",
                error.message,
                "error"
            );

        } finally {

            button.disabled = false;

        }

    });


    /* =====================================
       REFERRAL
       ===================================== */

    $("copyReferral")?.addEventListener("click", async () => {

        const link = $("referralLink")?.value;

        if (!link) return;

        try {

            await navigator.clipboard.writeText(link);

            message(
                "referralMessage",
                "Referral link copied successfully.",
                "success"
            );

        } catch (error) {

            $("referralLink").select();

            message(
                "referralMessage",
                "Select and copy your referral link.",
                "error"
            );

        }

    });


    $("shareReferral")?.addEventListener("click", () => {

        const link = $("referralLink")?.value;

        if (!link) return;

        const text = encodeURIComponent(
            "Join Cherry Mining using my referral link: " + link
        );

        const shareUrl =
            "https://t.me/share/url?url=" +
            encodeURIComponent(link) +
            "&text=" + text;

        tg?.openTelegramLink(shareUrl);

    });


    /* =====================================
       SAVE WALLET
       ===================================== */

    $("saveWallet")?.addEventListener("click", async () => {

        const wallet = $("profileWallet")?.value.trim();

        if (!/^0x[a-fA-F0-9]{40}$/.test(wallet || "")) {

            message(
                "walletMessage",
                "Please enter a valid BEP20 wallet address.",
                "error"
            );

            return;

        }

        const button = $("saveWallet");

        button.disabled = true;

        try {

            const data = await api(
                "/api/wallet",
                "POST",
                {
                    address: wallet
                }
            );

            setValue("withdrawWallet", wallet);

            message(
                "walletMessage",
                data.message || "Wallet saved successfully.",
                "success"
            );

        } catch (error) {

            message(
                "walletMessage",
                error.message,
                "error"
            );

        } finally {

            button.disabled = false;

        }

    });


    /* =====================================
       WALLET OWNERSHIP VERIFICATION
       ===================================== */

    $("verifyWallet")?.addEventListener("click", async () => {

        const button = $("verifyWallet");

        if (!window.ethereum) {

            message(
                "verifyMessage",
                "A compatible Web3 wallet is required for signature verification.",
                "error"
            );

            return;

        }

        button.disabled = true;

        try {

            const accounts = await window.ethereum.request({
                method: "eth_requestAccounts"
            });

            const wallet = accounts[0];

            if (!wallet) {

                throw new Error("Wallet connection failed.");

            }

            const challenge = await api(
                "/api/wallet/verification/challenge",
                "POST",
                {
                    address: wallet
                }
            );

            const signature = await window.ethereum.request({
                method: "personal_sign",
                params: [
                    challenge.message,
                    wallet
                ]
            });

            const result = await api(
                "/api/wallet/verification/confirm",
                "POST",
                {
                    address: wallet,
                    message: challenge.message,
                    signature: signature
                }
            );

            message(
                "verifyMessage",
                result.message || "Wallet ownership verified.",
                "success"
            );

            await refreshUser();

        } catch (error) {

            message(
                "verifyMessage",
                error.message,
                "error"
            );

        } finally {

            button.disabled = false;

        }

    });


    /* =====================================
       WITHDRAWAL PREVIEW
       ===================================== */

    $("withdrawAmount")?.addEventListener(
        "input",
        updateWithdrawPreview
    );


    /* =====================================
       SUBMIT WITHDRAWAL
       ===================================== */

    $("submitWithdrawal")?.addEventListener("click", async () => {

        const button = $("submitWithdrawal");

        const amount = Number(
            $("withdrawAmount")?.value
        );

        const wallet = $("withdrawWallet")?.value.trim();

        if (!Number.isSafeInteger(amount) || amount < MIN_WITHDRAW) {

            message(
                "withdrawMessage",
                "Minimum withdrawal is 10,000 Cherry.",
                "error"
            );

            return;

        }

        if (!/^0x[a-fA-F0-9]{40}$/.test(wallet || "")) {

            message(
                "withdrawMessage",
                "Enter a valid BEP20 wallet address.",
                "error"
            );

            return;

        }

        if (!confirm(
            "Submit withdrawal of " +
            formatNumber(amount) +
            " Cherry ($" +
            usdValue(amount) +
            ")?"
        )) {
            return;
        }

        button.disabled = true;

        try {

            const data = await api(
                "/api/withdraw",
                "POST",
                {
                    amount: amount,
                    wallet_address: wallet,
                    network: "BEP20"
                }
            );

            message(
                "withdrawMessage",
                data.message || "Withdrawal request submitted for admin approval.",
                "success"
            );

            setValue("withdrawAmount", "");

            await refreshUser();

            await loadWithdrawals();

        } catch (error) {

            message(
                "withdrawMessage",
                error.message,
                "error"
            );

        } finally {

            button.disabled = false;

        }

    });


    /* =====================================
       WITHDRAWAL HISTORY
       ===================================== */

    async function loadWithdrawals() {

        const container = $("withdrawHistory");

        if (!container) return;

        try {

            const data = await api("/api/withdrawals");

            const items = data.withdrawals || [];

            container.innerHTML = "";

            if (!items.length) {

                container.textContent =
                    "No withdrawal history available.";

                return;

            }

            items.forEach(item => {

                const row = document.createElement("div");

                row.className = "task-item";

                const details = document.createElement("div");

                details.className = "task-details";

                const title = document.createElement("h3");

                title.textContent =
                    formatNumber(item.amount) + " Cherry";

                const description = document.createElement("p");

                description.textContent =
                    "BEP20 • " +
                    String(item.status || "Pending").toUpperCase();

                details.appendChild(title);

                details.appendChild(description);

                row.appendChild(details);

                container.appendChild(row);

            });

        } catch (error) {

            container.textContent = error.message;

        }

    }


    /* =====================================
       PROFILE
       ===================================== */

    async function loadProfile() {

        try {

            const data = await api("/api/me");

            setText(
                "profileName",
                data.full_name || "Telegram User"
            );

            setText(
                "telegramId",
                data.telegram_id || telegramUser?.id || "--"
            );

            setText(
                "profileReferrals",
                formatNumber(data.referral_count)
            );

            setText(
                "profileVerifyStatus",
                data.verified ? "Verified" : "Not Verified"
            );

            if (data.wallet_address) {

                setValue(
                    "profileWallet",
                    data.wallet_address
                );

            }

        } catch (error) {

            message(
                "walletMessage",
                error.message,
                "error"
            );

        }

    }


    /* =====================================
       INITIALIZATION
       ===================================== */

    async function initialize() {

        loadTelegramUser();

        showPage("homePage");

        await refreshUser();

    }

    initialize();

})();
