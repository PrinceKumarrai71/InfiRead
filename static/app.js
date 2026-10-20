document.addEventListener("DOMContentLoaded", () => {
  const nav = document.querySelector("[data-nav]");
  document.querySelector("[data-menu-toggle]")?.addEventListener("click", () => nav?.classList.toggle("open"));
  document.querySelectorAll("[data-dismiss]").forEach(btn => btn.addEventListener("click", () => btn.closest(".flash")?.remove()));
  document.querySelectorAll("[data-confirm]").forEach(form => form.addEventListener("submit", e => {
    if (!window.confirm(form.dataset.confirm)) e.preventDefault();
  }));
  document.querySelectorAll("[data-password-toggle]").forEach(btn => btn.addEventListener("click", () => {
    const input = btn.parentElement.querySelector("input");
    const visible = input.type === "text";
    input.type = visible ? "password" : "text";
    btn.textContent = visible ? "Show" : "Hide";
  }));
  const year = document.querySelector("[data-year]");
  if (year) year.textContent = new Date().getFullYear();
  const cards = document.querySelectorAll(".book-card, .metric-card, .panel");
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.add("in-view"); observer.unobserve(entry.target); }
    }), { threshold: 0.08 });
    cards.forEach(card => observer.observe(card));
  } else cards.forEach(card => card.classList.add("in-view"));
});
