/* The fictional account portal's behaviour. Accounts live in this origin's localStorage (each test has its own browser
   profile). Query variants: next=PAGE (after sign-in go there), verify=code|link (after Create), exists=1 (Create says
   the email is taken), captcha=1 (a challenge on the sign-up page), twostep=1 (a code after sign-in), bad=1 (every
   sign-in fails), activate=1 (the emailed verification link). window.__created holds what Create received. */
(() => {
  const q = new URLSearchParams(location.search), $ = (s) => document.querySelector(s);
  const load = () => JSON.parse(localStorage.getItem("acct") || "null"), save = (a) => localStorage.setItem("acct", JSON.stringify(a));
  const show = (id, msg = "") => {
    ["signin", "signup", "code", "checkmail", "home"].forEach((s) => { $("#" + s).hidden = s !== id; });
    $("#msg").textContent = msg;
  };
  const home = () => { if (q.get("next")) location.href = q.get("next"); else show("home"); };
  let after = home;  // what a correct code leads to
  if (q.get("activate")) {
    const a = load(); if (a) { a.verified = true; save(a); }
    show("signin", "Your account is verified. Sign in.");
  }
  $("#toCreate").addEventListener("click", () => {
    show("signup");
    if (q.get("captcha") && !$("#captcha")) {
      const f = document.createElement("iframe");
      f.src = "/recaptcha/api2/bframe-fake.html"; f.id = "captcha"; f.style.cssText = "width:320px;height:200px;display:block";
      $("#signup").prepend(f);
    }
  });
  $("#toSignin").addEventListener("click", () => show("signin"));
  $("#forgot").addEventListener("click", () => show("signin", "We sent a reset link to your email."));
  $("#fSignup").addEventListener("submit", () => {
    const email = $("#su_email").value.trim(), pw = $("#su_pw").value;
    if (!$("#terms").checked) return show("signup", "Please accept the terms to continue.");
    if (!email || pw.length < 8 || pw !== $("#su_pw2").value) return show("signup", "Please fill in every field.");
    window.__created = { email, pw };
    if (q.get("exists")) return show("signup", "An account with this email already exists. Sign in instead.");
    save({ email, pw, verified: !q.get("verify") });
    if (q.get("verify") === "code") { after = () => { const a = load(); a.verified = true; save(a); home(); }; return show("code"); }
    if (q.get("verify") === "link") return show("checkmail");
    home();
  });
  $("#fSignin").addEventListener("submit", () => {
    const a = load(), email = $("#si_email").value.trim(), pw = $("#si_pw").value;
    window.__signins = (window.__signins || 0) + 1;
    if (q.get("bad") || !a || a.email !== email || a.pw !== pw) return show("signin", "Incorrect email or password.");
    if (!a.verified) return show("signin", "Please verify your email address first.");
    if (q.get("twostep")) { after = home; return show("code"); }
    home();
  });
  $("#verify").addEventListener("click", () => { if ($("#otp").value.trim() === "482913") after(); else $("#msg").textContent = "That code is not right."; });
})();
