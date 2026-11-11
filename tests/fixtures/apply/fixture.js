/* The fictional fixture form's behaviour: steps, required-field validation (aria-invalid + a role=alert message), the
   final Submit (window.__submitted, a confirmation number) and query variants: captcha, login, code, applied, offsite
   (Next goes to linkedin.com), elsewhere (Next goes to another fictional host), sw (registers a service worker). */
(() => {
  const q = new URLSearchParams(location.search), $ = (s) => document.querySelector(s);
  let step = q.get("step") || "1";
  const show = (n) => { step = String(n); document.querySelectorAll("[data-step]").forEach((s) => { s.hidden = s.dataset.step !== step; }); };
  if (q.get("applied")) { $("#app").hidden = true; $("#err").textContent = "You have already applied for this position."; return; }
  if (q.get("sw") && navigator.serviceWorker) navigator.serviceWorker.register("sw.js").then(() => { document.body.dataset.sw = "registered"; }, () => { document.body.dataset.sw = "refused"; });
  if (q.get("login")) {
    $("#login").hidden = false; $("#app").hidden = true;
    $("#signin").addEventListener("click", () => { $("#login").hidden = true; $("#app").hidden = false; });
  }
  if (q.get("captcha")) {
    const f = document.createElement("iframe");
    f.src = "/recaptcha/api2/bframe-fake.html"; f.id = "captcha"; f.style.cssText = "width:320px;height:200px;display:block";
    document.body.prepend(f);
  }
  show(step);
  const invalid = (sec) => {
    let bad = false;
    sec.querySelectorAll("[required]").forEach((el) => {
      const empty = el.type === "checkbox" ? !el.checked : el.type === "file" ? !el.files.length : !el.value.trim();
      el.setAttribute("aria-invalid", String(empty)); bad = bad || empty;
    });
    $("#err").textContent = bad ? "Please complete the required fields" : "";
    return bad;
  };
  document.querySelectorAll("[data-next]").forEach((b) => b.addEventListener("click", () => {
    if (invalid(b.closest("[data-step]"))) return;
    if (q.get("offsite")) { location.href = "https://www.linkedin.com/jobs/view/1"; return; }
    if (q.get("elsewhere")) { location.href = `http://careers.example-robotics.test:${location.port}/form.html?step=2`; return; }
    show(2);
  }));
  const done = () => {
    window.__submitted = true;
    $("#app").hidden = true;
    $("#err").textContent = "";
    const h = document.createElement("h2");
    h.textContent = "Thank you for applying! Confirmation number FIX-" + (1000 + document.title.length);
    document.body.append(h);
  };
  $("#submit").addEventListener("click", () => {
    if (invalid(document.querySelector('[data-step="2"]'))) return;
    window.__files = [...$("#resume").files].map((f) => f.name);
    if (q.get("code")) { show("code"); return; }
    done();
  });
  $("#verify").addEventListener("click", () => { if ($("#otp").value.trim()) done(); });
})();
