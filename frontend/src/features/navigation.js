const $ = (id) => document.getElementById(id);

export function initNavigation({ onNewChat }) {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    if (button.dataset.action === "new") onNewChat();
    else if (button.dataset.action === "sidebar") {
      $("app").classList.toggle(
        matchMedia("(max-width: 767px)").matches
          ? "mobile-sidebar-open"
          : "sidebar-collapsed",
      );
    }
  });
  $("sidebar-backdrop").addEventListener("click", () => {
    $("app").classList.remove("mobile-sidebar-open");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape")
      $("app").classList.remove("mobile-sidebar-open");
  });
}
