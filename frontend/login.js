import { login, getMe } from "./api.js";

const form = document.getElementById("login-form");
const emailInput = document.getElementById("login-email");
const passwordInput = document.getElementById("login-password");
const errorEl = document.getElementById("login-error");
const submitButton = document.getElementById("login-submit");

function safeNextPath() {
  const params = new URLSearchParams(location.search);
  const next = params.get("next");
  // Only accept a same-site relative path -- "//evil.com" or
  // "https://evil.com" would otherwise be a classic open-redirect via
  // this exact "return me to where I came from" mechanism.
  if (next && next.startsWith("/") && !next.startsWith("//")) return next;
  return "index.html";
}

// Already logged in (e.g. a stale bookmark to /login.html, or a page
// reload) -- skip straight past the form instead of making the user log
// in again for no reason.
getMe()
  .then(() => {
    location.href = safeNextPath();
  })
  .catch(() => {
    // Not logged in -- this is the expected/routine case, just show the form.
  });

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  errorEl.classList.add("hidden");
  submitButton.disabled = true;
  submitButton.textContent = "Logging in…";

  try {
    await login(emailInput.value.trim(), passwordInput.value);
    location.href = safeNextPath();
  } catch (err) {
    console.error("login failed", err);
    errorEl.textContent = "Incorrect email or password. Try again.";
    errorEl.classList.remove("hidden");
    passwordInput.value = "";
    passwordInput.focus();
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Log in";
  }
});
