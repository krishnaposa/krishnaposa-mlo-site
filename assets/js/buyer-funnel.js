/* ===== CONFIG: update these ===== */
const BOOKING_URL = "https://calendar.app.google/22s8fcMQLge9g63d6"; // your live booking link
const DEFAULT_RATE = 6.75;     // percent
const DEFAULT_PMI_RATE = 0.6;  // percent annual if LTV>80 and conventional
const TAX_RATE_BY_ZIP = { "30004": 0.012, "30301": 0.012, "30305": 0.0125, "30309": 0.013 };
const INSURANCE_PER_YEAR = 1200;

/* ===== Utility ===== */
const $, $$ = (q, all=false, r=document)=> all ? r.querySelectorAll(q) : r.querySelector(q);
const fmt = v => isFinite(v) ? v.toLocaleString(undefined,{style:"currency",currency:"USD",maximumFractionDigits:0}) : "$—";
const pct = v => (v*100).toFixed(1) + "%";
const num = v => {
  if(v==null) return NaN;
  v = String(v).trim();
  if(v.endsWith("%")) return parseFloat(v)/100;
  return parseFloat(v.replace(/[,\\s$]/g,""));
};

/* ===== Booking links ===== */
["bookTop","bookMid","bookBottom","bookSticky"].forEach(id=>{
  const el = document.getElementById(id);
  if(el) el.href = BOOKING_URL;
});

/* ===== Progress bar ===== */
function updateProgress(){
  const required = ["zip","price","fico","income"];
  const filled = required.filter(id => (document.getElementById(id)?.value || "").trim()).length;
  const percent = Math.min(100, (filled/required.length)*60 + 10);
  const bar = document.getElementById("bar");
  if(bar) bar.style.width = percent + "%";
}
document.getElementById("qualifyForm").addEventListener("input", updateProgress);
updateProgress();

/* ===== Agent co-brand ===== */
function drawAgent(){
  const data = JSON.parse(localStorage.getItem("agent") || "{}");
  document.getElementById("agentName").textContent = data.name || "No agent added";
  document.getElementById("agentFirm").textContent = data.firm || "You can add one above";
  document.getElementById("agentAvatar").src = data.logo || "";
  // hidden fields for intake
  document.getElementById("h_agentName").value = data.name || "";
  document.getElementById("h_agentEmail").value = data.email || "";
}
document.getElementById("saveAgent").addEventListener("click", ()=>{
  const name = document.getElementById("agent_name").value.trim();
  const firm = document.getElementById("agent_firm").value.trim();
  const email = document.getElementById("agent_email").value.trim();
  const logo = document.getElementById("agent_logo").value.trim();
  localStorage.setItem("agent", JSON.stringify({name, firm, email, logo}));
  drawAgent();
});
drawAgent();

/* ===== Calculator ===== */
document.getElementById("estimateBtn").addEventListener("click", ()=>{
  const price = num(document.getElementById("price").value);
  const downInput = document.getElementById("down").value;
  const down = downInput?.includes("%") ? price * num(downInput) : num(downInput||0);
  const loan = Math.max(0, price - (down||0));
  const rate = num(document.getElementById("rate").value || DEFAULT_RATE)/100;
  const zip = (document.getElementById("zip").value || "").trim();
  const prog = document.getElementById("program").value;
  const income = num(document.getElementById("income").value);
  const debts = num(document.getElementById("debts").value || 0);

  if(!price || !loan || !income){
    document.getElementById("formMsg").textContent = "Please complete price, down payment, and income.";
    return;
  }
  document.getElementById("formMsg").textContent = "";

  const n = 30 * 12;
  const m = rate/12;
  const pAndI = (m===0)? loan/n : loan * (m * Math.pow(1+m, n)) / (Math.pow(1+m, n) - 1);

  const taxRate = TAX_RATE_BY_ZIP[zip] ?? 0.012;
  const taxes = (price * taxRate) / 12;
  const ins   = INSURANCE_PER_YEAR / 12;

  let pmi = 0;
  const ltv = loan/price;
  if(prog === "conventional" && ltv > 0.80){
    pmi = (price * (DEFAULT_PMI_RATE/100)) / 12; // rough
    document.getElementById("pmiLine").style.display = "";
    document.getElementById("pmiLine").textContent = "Mortgage insurance estimated due to down payment under 20 percent. This can drop off as loan to value improves.";
  } else {
    document.getElementById("pmiLine").style.display = "none";
  }

  const total = pAndI + taxes + ins + pmi;
  const dti = (debts + total) / income;

  document.getElementById("pAndI").textContent = fmt(pAndI);
  document.getElementById("taxes").textContent = fmt(taxes + ins + pmi);
  document.getElementById("totalPay").textContent = fmt(total);
  document.getElementById("estimatesWrap").style.display = "grid";

  const dtiEl = document.getElementById("dtiLine");
  dtiEl.style.display = "";
  dtiEl.innerHTML = "Estimated DTI: <strong>"+ (dti*100).toFixed(1) + "%</strong>. Many programs prefer under 43 percent.";

  // hidden fields + persist
  document.getElementById("h_estMonthly").value = Math.round(total);
  document.getElementById("h_estDTI").value = (dti*100).toFixed(1) + "%";
  localStorage.setItem("lastEstimate", JSON.stringify({
    price, down, rate: rate*100, program: prog, monthly: Math.round(total), dti: (dti*100).toFixed(1)
  }));

  if(window.dataLayer){ dataLayer.push({event:"estimate_calculated"}); }
});

document.getElementById("resetBtn").addEventListener("click", ()=>{
  document.getElementById("estimatesWrap").style.display = "none";
  document.getElementById("dtiLine").style.display = "none";
  document.getElementById("pmiLine").style.display = "none";
  document.getElementById("formMsg").textContent = "";
  localStorage.removeItem("lastEstimate");
  updateProgress();
});

// Prefill from saved estimate + UTM chain
(function(){
  try{
    const saved = JSON.parse(localStorage.getItem("lastEstimate") || "{}");
    if(saved.price){
      document.getElementById("price").value = saved.price;
      if(saved.down){ document.getElementById("down").value = saved.down; }
      document.getElementById("rate").value = saved.rate ? saved.rate.toFixed?.(2) + "%" : "";
      document.getElementById("program").value = saved.program || "conventional";
    }
  }catch(e){}
  const utm = location.search.replace("?","").split("&").filter(Boolean).join("&");
  document.getElementById("h_utm").value = utm;
})();

// Intake submit tracking
document.getElementById("intakeForm").addEventListener("submit", ()=>{
  if(window.dataLayer){ dataLayer.push({event:"preapproval_submit"}); }
});

// Keyboard submit for estimate
document.getElementById("qualifyForm").addEventListener("keydown", (e)=>{
  if(e.key==="Enter"){ e.preventDefault(); document.getElementById("estimateBtn").click(); }
});