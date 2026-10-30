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
       REFRESH USER DATA
       ===================================== */

    async function refreshUser() {

        try {

            const data = await api("/api/me");

            userData = data;

            setText(
                "balance",
                formatNumber(data.balance)
            );

            setText(
                "usdBalance",
                "$" + usdValue(data.balance)
            );

            setText(
                "miningReward",
                formatNumber(data.mining_reward)
            );

            setText(
                "referralCount",
                formatNumber(data.referral_count)
            );

            setText(
                "profileReferrals",
                formatNumber(data.referral_count)
            );

            setText(
                "walletAddress",
                data.wallet_address || "Not connected"
            );

            setText(
                "miningStatus",
                data.mining_ready
                    ? "Ready to claim"
                    : data.mining_end_at
                        ? "Mining in progress"
                        : "Not started"
            );

            setText(
                "dailyReward",
                formatNumber(data.daily_reward)
            );

            setValue(
                "referralLink",
                data.referral_link || ""
            );

            updateMiningUI(data);

            updateDailyUI(data);

            updateWithdrawPreview();

        } catch (error) {

            console.error("Refresh user error:", error);

        }

    }


    /* =====================================
       MINING UI
       ===================================== */

    function updateMiningUI(data) {

        const startButton = $("startMining");
        const claimButton = $("claimMining");

        if (data.mining_ready) {

            if (startButton) startButton.disabled = true;
            if (claimButton) claimButton.disabled = false;

        } else if (data.mining_end_at) {

            if (startButton) startButton.disabled = true;
            if (claimButton) claimButton.disabled = true;

        } else {

            if (startButton) startButton.disabled = false;
            if (claimButton) claimButton.disabled = true;

        }

        if (data.mining_end_at && !data.mining_ready) {
            startCountdown(data.mining_end_at);
        } else {
            stopCountdown();
        }

    }


    function startCountdown(endAt) {

        stopCountdown();

        const endTime = new Date(endAt).getTime();

        function update() {

            const remaining = Math.max(
                0,
                endTime - Date.now()
            );

            const hours = Math.floor(
                remaining / 3600000
            );

            const minutes = Math.floor(
                (remaining % 3600000) / 60000
            );

            const seconds = Math.floor(
                (remaining % 60000) / 1000
            );

            setText(
                "miningTimer",
                `${hours}h ${minutes}m ${seconds}s`
            );

            if (remaining <= 0) {

                stopCountdown();

                refreshUser();

            }

        }

        update();

        countdownTimer = setInterval(update, 1000);

    }


    function stopCountdown() {

        if (countdownTimer) {

            clearInterval(countdownTimer);

            countdownTimer = null;

        }

    }


    /* =====================================
       START MINING
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
                "Mining started successfully!",
                "success"
            );

            await refreshUser();

        } catch (error) {

            message(
                "miningMessage",
                error.message,
                "error"
            );

            button.disabled = false;

        }

    });


    /* =====================================
       CLAIM MINING
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
                formatNumber(data.reward) + " Cherry claimed!",
                "success"
            );

            await refreshUser();

        } catch (error) {

            message(
                "miningMessage",
                error.message,
                "error"
            );

            button.disabled = false;

        }

    });


    /* =====================================
       DAILY UI
       ===================================== */

    function updateDailyUI(data) {

        const button = $("dailyBonus");

        if (!button) return;

        if (!data.daily_next_at) {

            button.disabled = false;

            return;

        }

        const next = new Date(data.daily_next_at).getTime();

        button.disabled = next > Date.now();

    }


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
                    task.completed ? "COMPLETED" : "WATCH AD & EARN";

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
       REWARDED TASK HELPER
       ===================================== */

    async function runRewardedTask(
        taskId,
        button,
        statusElement = "dailyMessage"
    ) {

        if (button) button.disabled = true;

        message(
            statusElement,
            "Preparing rewarded advertisement..."
        );

        try {

            // Create a unique server-side session for this task.
            const session = await api(
                "/api/ads/session?task_id=" +
                encodeURIComponent(taskId),
                "POST"
            );

            if (!session.session_id || !session.ymid) {

                throw new Error(
                    "Could not create an advertisement session."
                );

            }

            // Check Monetag SDK.
            if (
                typeof window.show_12152538 !== "function"
            ) {

                throw new Error(
                    "Monetag SDK is unavailable. Please refresh the app."
                );

            }

            message(
                statusElement,
                "Advertisement is starting..."
            );

            // Pass unique ymid to Monetag.
            await window.show_12152538({
                ymid: session.ymid
            });

            message(
                statusElement,
                "Advertisement ended. Verifying with server..."
            );

            let verified = false;

            // Wait up to two minutes for Monetag postback.
            for (let attempt = 0; attempt < 24; attempt++) {

                await new Promise(resolve =>
                    setTimeout(resolve, 5000)
                );

                const result = await api(
                    "/api/ads/session/" +
                    encodeURIComponent(session.session_id)
                );

                if (result.status === "valued") {

                    verified = true;

                    break;

                }

                if (result.status === "rejected") {

                    throw new Error(
                        "Monetag did not value this advertisement. No reward was added."
                    );

                }

                if (result.status === "claimed") {

                    throw new Error(
                        "This advertisement session has already been claimed."
                    );

                }

            }

            if (!verified) {

                message(
                    statusElement,
                    "Verification is still pending. Please try again later."
                );

                return;

            }

            // Server checks valued session and credits reward once.
            const claim = await api(
                "/api/tasks/" +
                encodeURIComponent(taskId) +
                "/complete",
                "POST",
                {
                    session_id: session.session_id
                }
            );

            message(
                statusElement,
                "Success! " +
                formatNumber(claim.reward) +
                " Cherry added to your balance.",
                "success"
            );

            await refreshUser();

            await loadTasks();

        } catch (error) {

            console.error(
                "Rewarded task error:",
                error
            );

            message(
                statusElement,
                error.message || "Advertisement task failed.",
                "error"
            );

        } finally {

            if (button) button.disabled = false;

        }

    }


    /* =====================================
       COMPLETE TASK
       ===================================== */

    async function completeTask(taskId, button) {

        await runRewardedTask(
            taskId,
            button,
            "dailyMessage"
        );

    }


    /* =====================================
       MONETAG REWARDED ADS BUTTON
       ===================================== */

    $("watchAd")?.addEventListener("click", async () => {

        const button = $("watchAd");

        // Standalone Watch Ad button uses task 1.
        await runRewardedTask(
            1,
            button,
            "adMessage"
        );

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
                "Referral link copied!",
                "success"
            );

        } catch (error) {

            message(
                "referralMessage",
                "Could not copy referral link.",
                "error"
            );

        }

    });


    /* =====================================
       REFERRAL CLAIM
       ===================================== */

    async function claimReferral() {

        const params = new URLSearchParams(
            window.location.search
        );

        const startParam = params.get("start");

        if (!startParam) return;

        try {

            await api(
                "/api/referral/claim?start=" +
                encodeURIComponent(startParam),
                "POST"
            );

        } catch (error) {

            console.log(
                "Referral:",
                error.message
            );

        }

    }


    /* =====================================
       WITHDRAW PREVIEW
       ===================================== */

    function updateWithdrawPreview() {

        const amountInput = $("withdrawAmount");

        if (!amountInput) return;

        const amount = Number(amountInput.value || 0);

        setText(
            "withdrawUsd",
            "$" + usdValue(amount)
        );

        setText(
            "withdrawBalance",
            formatNumber(userData?.balance || 0)
        );

    }


    $("withdrawAmount")?.addEventListener(
        "input",
        updateWithdrawPreview
    );


    /* =====================================
       SAVE WALLET
       ===================================== */

    $("saveWallet")?.addEventListener("click", async () => {

        const button = $("saveWallet");

        const address = $("walletInput")?.value?.trim();

        if (!address) {

            message(
                "walletMessage",
                "Please enter your wallet address.",
                "error"
            );

            return;

        }

        button.disabled = true;

        try {

            await api(
                "/api/wallet",
                "POST",
                {
                    address
                }
            );

            message(
                "walletMessage",
                "Wallet saved successfully.",
                "success"
            );

            await refreshUser();

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
       WALLET VERIFICATION
       ===================================== */

    $("verifyWallet")?.addEventListener("click", async () => {

        const button = $("verifyWallet");

        const address = $("walletInput")?.value?.trim();

        if (!address) {

            message(
                "walletMessage",
                "Enter your wallet address first.",
                "error"
            );

            return;

        }

        button.disabled = true;

        try {

            const challenge = await api(
                "/api/wallet/verification/challenge",
                "POST",
                {
                    address
                }
            );

            setText(
                "walletChallenge",
                challenge.message
            );

            message(
                "walletMessage",
                "Sign the verification message in your wallet.",
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
       LOAD WITHDRAWALS
       ===================================== */

    async function loadWithdrawals() {

        const container = $("withdrawalList");

        if (!container) return;

        try {

            const data = await api("/api/withdrawals");

            container.innerHTML = "";

            (data.withdrawals || []).forEach(item => {

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
       CREATE WITHDRAWAL
       ===================================== */

    $("withdrawButton")?.addEventListener("click", async () => {

        const button = $("withdrawButton");

        const amount = Number(
            $("withdrawAmount")?.value || 0
        );

        const walletAddress = (
            $("walletInput")?.value ||
            userData?.wallet_address ||
            ""
        ).trim();

        if (!amount || amount < MIN_WITHDRAW) {

            message(
                "withdrawMessage",
                "Minimum withdrawal is 10,000 Cherry.",
                "error"
            );

            return;

        }

        if (!walletAddress) {

            message(
                "withdrawMessage",
                "Please save your wallet address first.",
                "error"
            );

            return;

        }

        button.disabled = true;

        try {

            const data = await api(
                "/api/withdraw",
                "POST",
                {
                    amount,
                    wallet_address: walletAddress,
                    network: "BEP20"
                }
            );

            message(
                "withdrawMessage",
                "Withdrawal request submitted successfully.",
                "success"
            );

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

        await claimReferral();

    }

    initialize();

})();
