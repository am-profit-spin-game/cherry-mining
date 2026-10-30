(() => {
 const tg=window.Telegram?.WebApp; tg?.ready(); tg?.expand();
 const $=id=>document.getElementById(id), set=(id,msg)=>{if($(id))$(id).textContent=msg};
 const user=tg?.initDataUnsafe?.user; if(user)$("userName").textContent=user.first_name||"Telegram User";
 async function api(path,method="GET"){
  const r=await fetch(path,{method,headers:{"Content-Type":"application/json","X-Telegram-Init-Data":tg?.initData||""}});
  const d=await r.json().catch(()=>({})); if(!r.ok)throw Error(d.detail||"Backend request failed"); return d;
 }
 async function refresh(){try{const d=await api("/api/me");$("balance").textContent=d.balance??0;$("refCount").textContent=d.referral_count??0;$("referralLink").value=d.referral_link||"Open from Telegram";set("miningStatus",d.mining_active?"Mining active":"Mining not started")}catch(e){set("miningStatus","Backend এখনো deploy/সংযুক্ত হয়নি।")}}
 $("startMining").onclick=async()=>{try{const d=await api("/api/mining/start","POST");set("miningStatus",d.message);await refresh()}catch(e){set("miningStatus",e.message)}};
 $("claimMining").onclick=async()=>{try{const d=await api("/api/mining/claim","POST");set("miningStatus",d.message);await refresh()}catch(e){set("miningStatus",e.message)}};
 $("dailyBonus").onclick=async()=>{try{const d=await api("/api/daily/claim","POST");set("dailyStatus",d.message);await refresh()}catch(e){set("dailyStatus",e.message)}};
 $("watchAd").onclick=async()=>{set("adStatus","Monetag SDK পরীক্ষা করা হচ্ছে...");try{if(typeof window.show_12152538!=="function")throw Error("Monetag SDK লোড হয়নি।");await window.show_12152538();set("adStatus","Ad session শেষ। রিওয়ার্ডের আগে server-side verification লাগবে।")}catch(e){set("adStatus",e.message||"Ad unavailable")}};
 $("copyReferral").onclick=async()=>{try{await navigator.clipboard.writeText($("referralLink").value);$("copyReferral").textContent="COPIED"}catch(e){$("referralLink").select();set("dailyStatus","লিংকটি সিলেক্ট হয়েছে; Copy করুন।")}};
 refresh();
})();