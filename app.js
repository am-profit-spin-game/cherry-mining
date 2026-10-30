(() => {

    // TELEGRAM WEB APP
    const tg = window.Telegram?.WebApp;

    tg?.ready();
    tg?.expand();

    // ELEMENT SELECTOR
    const $ = id => document.getElementById(id);

    const set = (id, msg) => {
        if ($(id)) {
            $(id).textContent = msg;
        }
    };


    // =========================
    // NAVIGATION SYSTEM
    // =========================

    const navButtons = document.querySelectorAll(".nav-btn");
    const pages = document.querySelectorAll(".page");

    function showPage(pageId) {

        pages.forEach(page => {
            page.classList.remove("active");
        });

        navButtons.forEach(button => {
            button.classList.remove("active");
        });

        const selectedPage = $(pageId);

        if (selectedPage) {
            selectedPage.classList.add("active");
        }

        const selectedButton = document.querySelector(
            `.nav-btn[data-page="${pageId}"]`
        );

        if (selectedButton) {
            selectedButton.classList.add("active");
        }

        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });
    }

    navButtons.forEach(button => {

        button.addEventListener("click", () => {

            const pageId = button.dataset.page;

            showPage(pageId);

        });

    });


    // =========================
    // TELEGRAM USER
    // =========================

    const user = tg?.initDataUnsafe?.user;

    if (user) {
        $("userName").textContent =
            user.first_name || "Telegram User";
    }


    // =========================
    // BACKEND API
    // =========================

    async function api(path, method = "GET") {

        const response = await fetch(path, {

            method: method,

            headers: {
                "Content-Type": "application/json",
                "X-Telegram-Init-Data": tg?.initData || ""
            }

        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw Error(
                data.detail || "Backend request failed"
            );
        }

        return data;
    }


    // =========================
    // REFRESH USER DATA
    // =========================

    async function refresh() {

        try {

            const data = await api("/api/me");

            $("balance").textContent =
                data.balance ?? 0;

            $("refCount").textContent =
                data.referral_count ?? 0;

            $("referralLink").value =
                data.referral_link || "Open from Telegram";

            set(
                "miningStatus",
                data.mining_active
                    ? "Mining active"
                    : "Mining not started"
            );

        } catch (error) {

            set(
                "miningStatus",
                "Backend এখনো deploy/সংযুক্ত হয়নি।"
            );

        }

    }


    // =========================
    // START MINING
    // =========================

    $("startMining").onclick = async () => {

        try {

            const data = await api(
                "/api/mining/start",
                "POST"
            );

            set("miningStatus", data.message);

            await refresh();

        } catch (error) {

            set("miningStatus", error.message);

        }

    };


    // =========================
    // CLAIM MINING
    // =========================

    $("claimMining").onclick = async () => {

        try {

            const data = await api(
                "/api/mining/claim",
                "POST"
            );

            set("miningStatus", data.message);

            await refresh();

        } catch (error) {

            set("miningStatus", error.message);

        }

    };


    // =========================
    // DAILY BONUS
    // =========================

    $("dailyBonus").onclick = async () => {

        try {

            const data = await api(
                "/api/daily/claim",
                "POST"
            );

            set("dailyStatus", data.message);

            await refresh();

        } catch (error) {

            set("dailyStatus", error.message);

        }

    };


    // =========================
    // MONETAG WATCH AD
    // =========================

    $("watchAd").onclick = async () => {

        set(
            "adStatus",
            "Monetag SDK পরীক্ষা করা হচ্ছে..."
        );

        try {

            if (
                typeof window.show_12152538 !== "function"
            ) {
                throw Error("Monetag SDK লোড হয়নি।");
            }

            await window.show_12152538();

            set(
                "adStatus",
                "Ad session শেষ। রিওয়ার্ডের আগে server-side verification লাগবে।"
            );

        } catch (error) {

            set(
                "adStatus",
                error.message || "Ad unavailable"
            );

        }

    };


    // =========================
    // COPY REFERRAL LINK
    // =========================

    $("copyReferral").onclick = async () => {

        const link = $("referralLink").value;

        try {

            await navigator.clipboard.writeText(link);

            $("copyReferral").textContent = "COPIED";

            setTimeout(() => {
                $("copyReferral").textContent = "COPY LINK";
            }, 2000);

        } catch (error) {

            $("referralLink").select();

            set(
                "dailyStatus",
                "লিংকটি সিলেক্ট হয়েছে; Copy করুন।"
            );

        }

    };


    // =========================
    // INITIALIZE
    // =========================

    showPage("homePage");

    refresh();

})();
