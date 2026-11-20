let departure: Animation | null = null;
let restoreTimer: ReturnType<typeof setTimeout> | undefined;

function restorePage(): void {
  departure?.cancel();
  departure = null;
  clearTimeout(restoreTimer);
}

export function navigateDocument(href: string): void {
  if (departure) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    window.location.assign(href);
    return;
  }
  const animation = document.body.animate([{ opacity: 1 }, { opacity: 0 }], {
    duration: 160, easing: "ease-in", fill: "forwards",
  });
  departure = animation;
  void animation.finished.then(() => {
    window.location.assign(href);
    // Restore a cancelled unload or a destination that has not responded.
    restoreTimer = setTimeout(restorePage, 1200);
  }, () => {});
}

export function installDocumentNavigation(): () => void {
  const show = (event: PageTransitionEvent): void => {
    restorePage();
    if (event.persisted && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document.body.animate([{ opacity: 0 }, { opacity: 1 }], {
        duration: 300, easing: "cubic-bezier(.16, 1, .3, 1)",
      });
    }
  };
  const click = (event: MouseEvent): void => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
    if (!anchor || anchor.hasAttribute("download") || (anchor.target && anchor.target !== "_self")) return;
    const target = new URL(anchor.href, window.location.href);
    if (target.origin !== window.location.origin || (target.pathname === window.location.pathname && target.search === window.location.search)) return;
    event.preventDefault();
    navigateDocument(anchor.href);
  };
  document.addEventListener("click", click);
  window.addEventListener("pageshow", show);
  return () => {
    document.removeEventListener("click", click);
    window.removeEventListener("pageshow", show);
    restorePage();
  };
}
