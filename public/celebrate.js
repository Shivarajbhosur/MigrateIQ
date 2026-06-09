/* ============================================================================
 * Validation Agent — Cinematic completion celebration
 * ----------------------------------------------------------------------------
 * Fires a layered confetti + petal + flash animation when a chat message
 * containing a known success phrase appears.
 *
 * Design notes
 *   - Loaded by voice.js (Chainlit allows only one custom_js).
 *   - No HTML/JS is injected from Python messages (config has
 *     unsafe_allow_html = false), so detection is purely DOM-side.
 *   - Idempotent: each message element is marked once via a data-attribute,
 *     so resizing / re-rendering never re-fires the animation.
 *   - Lazy-loads canvas-confetti from CDN only on first trigger; failure is
 *     swallowed silently so app functionality is never affected.
 *   - Zero impact on streaming, voice input, message rendering, or layout.
 * ========================================================================== */
(() => {
  "use strict";

  if (window.__vaCelebrateInstalled) return;
  window.__vaCelebrateInstalled = true;

  // ----- Trigger phrases ---------------------------------------------------
  // Add new completion phrases here. Matching is case-insensitive substring.
  const TRIGGERS = [
    "reporting task complete",
    "all 6 steps completed successfully",
  ];

  const MARK_ATTR = "data-va-celebrated";
  const CONFETTI_URL =
    "https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.3/dist/confetti.browser.min.js";

  // ----- Lazy loader for canvas-confetti -----------------------------------
  let confettiPromise = null;
  function loadConfetti() {
    if (window.confetti) return Promise.resolve(window.confetti);
    if (confettiPromise) return confettiPromise;
    confettiPromise = new Promise((resolve) => {
      const s = document.createElement("script");
      s.src = CONFETTI_URL;
      s.async = true;
      s.onload = () => resolve(window.confetti || null);
      s.onerror = () => resolve(null); // fail quietly
      document.head.appendChild(s);
    });
    return confettiPromise;
  }

  // ----- Visual helpers ----------------------------------------------------
  function injectStylesOnce() {
    if (document.getElementById("va-celebrate-styles")) return;
    const css = `
      .va-flash-overlay{
        position:fixed;inset:0;z-index:9998;pointer-events:none;
        background:radial-gradient(circle at 50% 55%,
          rgba(255,255,255,.85) 0%,
          rgba(255,224,130,.55) 25%,
          rgba(139,92,246,.25) 55%,
          rgba(0,0,0,0) 75%);
        opacity:0;animation: va-flash 1.1s ease-out forwards;
      }
      @keyframes va-flash{
        0%  {opacity:0; transform:scale(.9)}
        20% {opacity:1; transform:scale(1)}
        100%{opacity:0; transform:scale(1.05)}
      }
      .va-trophy-banner{
        position:fixed;left:50%;top:18%;transform:translate(-50%, -20px) scale(.85);
        z-index:9999;pointer-events:none;opacity:0;
        padding:14px 28px;border-radius:999px;
        background:linear-gradient(135deg,#8B5CF6 0%,#06B6D4 50%,#10B981 100%);
        color:#fff;font: 600 18px/1.2 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
        letter-spacing:.4px;
        box-shadow:0 12px 40px rgba(139,92,246,.45),
                   0 0 0 0 rgba(16,185,129,.6);
        animation: va-banner-in .55s cubic-bezier(.2,1.4,.4,1) forwards,
                   va-banner-glow 1.6s ease-out .55s 2,
                   va-banner-out .6s ease-in 3.2s forwards;
        display:flex;align-items:center;gap:10px;
      }
      .va-trophy-banner .va-trophy-emoji{
        font-size:24px;display:inline-block;
        animation: va-trophy-spin 1.2s ease-out;
      }
      @keyframes va-banner-in{
        from{opacity:0;transform:translate(-50%,-40px) scale(.7)}
        to  {opacity:1;transform:translate(-50%,0)     scale(1)}
      }
      @keyframes va-banner-out{
        from{opacity:1;transform:translate(-50%,0)   scale(1)}
        to  {opacity:0;transform:translate(-50%,-30px) scale(.9)}
      }
      @keyframes va-banner-glow{
        0%  {box-shadow:0 12px 40px rgba(139,92,246,.45),0 0 0 0 rgba(16,185,129,.7)}
        100%{box-shadow:0 12px 40px rgba(139,92,246,.45),0 0 0 28px rgba(16,185,129,0)}
      }
      @keyframes va-trophy-spin{
        from{transform:rotate(-25deg) scale(.6)}
        to  {transform:rotate(0)      scale(1)}
      }
      @media (prefers-reduced-motion: reduce){
        .va-flash-overlay,.va-trophy-banner{animation:none;opacity:0}
      }
    `;
    const tag = document.createElement("style");
    tag.id = "va-celebrate-styles";
    tag.textContent = css;
    document.head.appendChild(tag);
  }

  function flashOverlay() {
    const el = document.createElement("div");
    el.className = "va-flash-overlay";
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 1300);
  }

  function trophyBanner() {
    const el = document.createElement("div");
    el.className = "va-trophy-banner";
    el.innerHTML =
      '<span class="va-trophy-emoji">🏆</span>' +
      '<span>Reporting Complete</span>' +
      '<span class="va-trophy-emoji">🎉</span>';
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  // ----- Flower shape (canvas-confetti supports custom path shapes) --------
  function buildFlowerShape(confetti) {
    if (typeof confetti.shapeFromPath !== "function") return null;
    // Simple 6-petal flower, ~24x24 viewbox
    const d =
      "M12 2 C14 6 18 6 18 10 C22 12 22 16 18 16 C18 20 14 22 12 18 " +
      "C10 22 6 20 6 16 C2 16 2 12 6 10 C6 6 10 6 12 2 Z";
    try {
      return confetti.shapeFromPath({ path: d });
    } catch {
      return null;
    }
  }

  // ----- Cinematic sequence ------------------------------------------------
  const PALETTE = [
    "#8B5CF6", // violet
    "#06B6D4", // cyan
    "#10B981", // emerald
    "#FACC15", // gold
    "#F472B6", // pink
    "#FB923C", // orange
  ];

  async function runCelebration() {
    injectStylesOnce();
    flashOverlay();
    trophyBanner();

    const confetti = await loadConfetti();
    if (!confetti) return;

    const flower = buildFlowerShape(confetti);

    // Defaults shared by every burst
    const base = { zIndex: 9999, colors: PALETTE, disableForReducedMotion: true };

    // 1) Big centre burst
    confetti({
      ...base,
      particleCount: 160,
      spread: 90,
      startVelocity: 55,
      origin: { x: 0.5, y: 0.6 },
      scalar: 1.1,
    });

    // 2) Side cannons firing inward for ~1.4s
    const cannonsEnd = Date.now() + 1400;
    (function cannons() {
      confetti({
        ...base,
        particleCount: 7,
        angle: 60,
        spread: 55,
        startVelocity: 60,
        origin: { x: 0, y: 0.7 },
      });
      confetti({
        ...base,
        particleCount: 7,
        angle: 120,
        spread: 55,
        startVelocity: 60,
        origin: { x: 1, y: 0.7 },
      });
      if (Date.now() < cannonsEnd) requestAnimationFrame(cannons);
    })();

    // 3) Flower bloom (custom shape) just after the centre burst
    setTimeout(() => {
      confetti({
        ...base,
        particleCount: flower ? 60 : 80,
        spread: 110,
        startVelocity: 35,
        scalar: 1.6,
        gravity: 0.7,
        origin: { x: 0.5, y: 0.55 },
        shapes: flower ? [flower] : ["circle"],
      });
    }, 350);

    // 4) Star pops at random horizontal positions
    [0.2, 0.4, 0.6, 0.8].forEach((x, i) => {
      setTimeout(() => {
        confetti({
          ...base,
          particleCount: 30,
          spread: 70,
          startVelocity: 45,
          scalar: 0.9,
          shapes: ["star"],
          origin: { x, y: 0.4 + Math.random() * 0.2 },
        });
      }, 600 + i * 120);
    });

    // 5) Gentle falling petals (low gravity drift) for ~2s
    const petalsEnd = Date.now() + 2000;
    (function petals() {
      confetti({
        ...base,
        particleCount: 4,
        startVelocity: 8,
        gravity: 0.35,
        spread: 180,
        scalar: 1.3,
        ticks: 220,
        origin: { x: Math.random(), y: 0 },
        shapes: flower ? [flower] : ["circle"],
      });
      if (Date.now() < petalsEnd) setTimeout(petals, 90);
    })();
  }

  // ----- Detection (MutationObserver) --------------------------------------
  function maybeCelebrate(node) {
    if (!node || node.nodeType !== 1) return;
    if (node.hasAttribute && node.hasAttribute(MARK_ATTR)) return;
    const text = (node.innerText || "").toLowerCase();
    if (!text) return;
    if (!TRIGGERS.some((t) => text.includes(t))) return;
    // Mark the closest message container so re-renders won't re-fire.
    const target =
      node.closest && (node.closest("[data-step]") || node.closest("li") || node);
    try { target.setAttribute(MARK_ATTR, "1"); } catch {}
    runCelebration();
  }

  function start() {
    // Sweep existing DOM once on load (in case page restored a finished session)
    document.querySelectorAll("p, div, li").forEach((el) => {
      const text = (el.innerText || "").toLowerCase();
      if (text && TRIGGERS.some((t) => text.includes(t))) {
        el.setAttribute(MARK_ATTR, "1"); // mark, don't fire on reload
      }
    });

    const observer = new MutationObserver((mutations) => {
      for (const m of mutations) {
        for (const node of m.addedNodes) maybeCelebrate(node);
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
