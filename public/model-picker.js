/* =============================================================================
 * Validation Agent — Top-left "Models" Picker Button
 * -----------------------------------------------------------------------------
 * Adds a sleek, animated "🤖 Models" pill button to the top-left of the chat
 * (next to the New Chat icon) that opens the existing Chainlit settings panel
 * — the same one driven by `_build_model_select()` in app.py. No backend
 * changes, no new widgets — it just programmatically clicks the hidden
 * built-in gear icon next to the chat input.
 *
 * Why a separate file?
 *   Keeps the voice/celebrate scripts untouched. Loaded lazily by voice.js
 *   (same companion-loader pattern as celebrate.js) so a single custom_js
 *   entry in config.toml remains sufficient.
 *
 * Resilience:
 *   - MutationObserver watches the React tree so the button survives
 *     re-renders and route changes.
 *   - Multiple DOM-selector fallbacks for the gear icon (Chainlit's class
 *     names occasionally shift between versions).
 *   - All work wrapped in try/catch — failure here can never break chat.
 * ===========================================================================*/
(() => {
  "use strict";

  if (window.__vaModelPickerMounted) return;
  window.__vaModelPickerMounted = true;

  const BTN_ID = "va-models-picker-btn";
  const STYLE_ID = "va-models-picker-styles";

  /* ------------------------------------------------------------------ *
   * 1. Inject CSS (kept inline so the module is self-contained)
   * ------------------------------------------------------------------ */
  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const css = `
      /* Hide Chainlit's built-in settings (gear) icon next to chat input —
         we surface the same panel via our top-left pill button instead.
         Keep it clickable (we forward clicks to it) — just make it
         visually invisible and zero-sized. */
      #message-composer button[aria-label*="ettings" i],
      #chat-input-container button[aria-label*="ettings" i],
      #message-composer button[aria-label*="config" i],
      #message-composer button[aria-label*="chat settings" i],
      #message-composer button[id*="ettings" i],
      #message-composer button[id*="chat-settings" i],
      #message-composer #chat-settings-open-modal,
      .va-hide-settings-gear {
        opacity: 0 !important;
        width: 0 !important;
        height: 0 !important;
        min-width: 0 !important;
        min-height: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        border: 0 !important;
        overflow: hidden !important;
        /* keep pointer-events enabled so our programmatic .click() works
           even though the 0x0 size prevents any accidental user clicks */
      }

      /* Top-left container — fixed so it survives layout shifts */
      #${BTN_ID} {
        position: fixed;
        top: 14px;
        left: 70px;             /* sits next to the New Chat icon */
        z-index: 2147483646;    /* below modals (max - 1) */
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 7px 14px 7px 11px;
        border: 1px solid rgba(160, 120, 255, 0.45);
        border-radius: 999px;
        background: linear-gradient(135deg,
          rgba(50, 30, 90, 0.85) 0%,
          rgba(80, 40, 140, 0.85) 50%,
          rgba(140, 60, 200, 0.85) 100%);
        backdrop-filter: blur(10px) saturate(140%);
        -webkit-backdrop-filter: blur(10px) saturate(140%);
        color: #fff;
        font: 600 12.5px/1 'Inter', system-ui, -apple-system, sans-serif;
        letter-spacing: 0.02em;
        cursor: pointer;
        user-select: none;
        box-shadow:
          0 0 0 1px rgba(255, 255, 255, 0.05) inset,
          0 4px 14px rgba(120, 60, 220, 0.35),
          0 0 22px rgba(180, 100, 255, 0.25);
        transition: transform 180ms ease, box-shadow 220ms ease,
                    background 220ms ease, filter 220ms ease;
        animation: vaModelsIdle 4.5s ease-in-out infinite;
      }
      #${BTN_ID} .va-mp-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 22px; height: 22px;
        border-radius: 50%;
        background: radial-gradient(circle at 30% 30%,
                    #ffd1ff 0%, #b48cff 45%, #6a3bd6 100%);
        box-shadow: 0 0 10px rgba(200, 140, 255, 0.65);
        font-size: 12px;
        animation: vaModelsSpin 9s linear infinite;
      }
      #${BTN_ID} .va-mp-label {
        background: linear-gradient(90deg, #fff, #e0c8ff, #fff);
        background-size: 200% 100%;
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
        animation: vaModelsShimmer 5s ease-in-out infinite;
      }
      #${BTN_ID} .va-mp-chev {
        margin-left: 2px;
        opacity: 0.85;
        transition: transform 180ms ease;
      }
      #${BTN_ID}:hover {
        transform: translateY(-1px) scale(1.03);
        filter: brightness(1.08);
        box-shadow:
          0 0 0 1px rgba(255, 255, 255, 0.08) inset,
          0 6px 22px rgba(160, 80, 255, 0.55),
          0 0 32px rgba(200, 140, 255, 0.45);
      }
      #${BTN_ID}:hover .va-mp-chev { transform: rotate(180deg); }
      #${BTN_ID}:active { transform: translateY(0) scale(0.98); }
      #${BTN_ID}.va-mp-flash {
        animation: vaModelsFlash 600ms ease;
      }

      @keyframes vaModelsIdle {
        0%, 100% { box-shadow:
            0 0 0 1px rgba(255, 255, 255, 0.05) inset,
            0 4px 14px rgba(120, 60, 220, 0.35),
            0 0 22px rgba(180, 100, 255, 0.25); }
        50%      { box-shadow:
            0 0 0 1px rgba(255, 255, 255, 0.08) inset,
            0 4px 18px rgba(150, 80, 240, 0.55),
            0 0 30px rgba(200, 140, 255, 0.45); }
      }
      @keyframes vaModelsSpin {
        from { transform: rotate(0deg); }
        to   { transform: rotate(360deg); }
      }
      @keyframes vaModelsShimmer {
        0%, 100% { background-position: 0% 50%; }
        50%      { background-position: 100% 50%; }
      }
      @keyframes vaModelsFlash {
        0%   { box-shadow: 0 0 0 0 rgba(255, 220, 255, 0.7),
                          0 0 22px rgba(180, 100, 255, 0.25); }
        70%  { box-shadow: 0 0 0 14px rgba(255, 220, 255, 0),
                          0 0 22px rgba(180, 100, 255, 0.25); }
        100% { box-shadow: 0 0 0 0 rgba(255, 220, 255, 0),
                          0 0 22px rgba(180, 100, 255, 0.25); }
      }

      @media (prefers-reduced-motion: reduce) {
        #${BTN_ID},
        #${BTN_ID} .va-mp-icon,
        #${BTN_ID} .va-mp-label { animation: none !important; }
      }

      @media (max-width: 640px) {
        #${BTN_ID} {
          left: 60px;
          padding: 6px 11px 6px 9px;
          font-size: 11.5px;
        }
        #${BTN_ID} .va-mp-icon { width: 19px; height: 19px; }
      }

      /* ============================================================== *
       *  Dialog polish — purple/violet palette matching the pill button.
       *  COLORS apply to all Chainlit dialogs (Settings, Readme, etc.)
       *  so the whole UI feels unified.
       *  LAYOUT (top/transform/max-height) is scoped further below to
       *  the Settings panel only, so the Readme can use its natural
       *  centered position with full content height.
       * ============================================================== */
      [role="dialog"][data-state="open"] {
        border-radius: 18px !important;
        border: 1px solid rgba(160, 120, 255, 0.45) !important;
        background: linear-gradient(155deg,
          rgba(28, 16, 52, 0.96) 0%,
          rgba(46, 22, 86, 0.96) 55%,
          rgba(70, 30, 120, 0.96) 100%) !important;
        backdrop-filter: blur(18px) saturate(150%);
        -webkit-backdrop-filter: blur(18px) saturate(150%);
        box-shadow:
          0 0 0 1px rgba(255,255,255,0.05) inset,
          0 18px 60px rgba(0, 0, 0, 0.55),
          0 0 40px rgba(160, 90, 240, 0.35) !important;
        color: #f4ecff !important;
        animation: vaPanelIn 280ms cubic-bezier(.2,.9,.25,1.1);
      }
      @keyframes vaPanelIn {
        from { opacity: 0; transform: translate(-50%, -50%) scale(.97); }
        to   { opacity: 1; transform: translate(-50%, -50%) scale(1);   }
      }

      /* Settings-panel-only layout: lift above center so the model
         dropdown has room to expand below it. Detected via the
         presence of a combobox (the model select trigger). */
      [role="dialog"][data-state="open"]:has([role="combobox"]) {
        top: 12vh !important;
        transform: translate(-50%, 0) !important;
        max-height: 80vh;
        overflow: visible !important;
        animation: vaSettingsIn 280ms cubic-bezier(.2,.9,.25,1.1);
      }
      @keyframes vaSettingsIn {
        from { opacity: 0; transform: translate(-50%, -8px) scale(.97); }
        to   { opacity: 1; transform: translate(-50%, 0)    scale(1);   }
      }

      /* Panel title */
      [role="dialog"][data-state="open"] h2,
      [role="dialog"][data-state="open"] [class*="DialogTitle"] {
        background: linear-gradient(90deg, #fff 0%, #d8b8ff 50%, #fff 100%);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        color: transparent !important;
        font-weight: 700 !important;
        letter-spacing: 0.01em;
      }

      /* Description / labels */
      [role="dialog"][data-state="open"] p,
      [role="dialog"][data-state="open"] label {
        color: rgba(232, 220, 255, 0.85) !important;
      }

      /* The select trigger (the closed dropdown bar) */
      [role="dialog"][data-state="open"] [role="combobox"],
      [role="dialog"][data-state="open"] button[role="combobox"] {
        background: rgba(255, 255, 255, 0.06) !important;
        border: 1px solid rgba(180, 140, 255, 0.4) !important;
        color: #fff !important;
        border-radius: 10px !important;
        transition: border-color 180ms ease, box-shadow 180ms ease;
      }
      [role="dialog"][data-state="open"] [role="combobox"]:hover,
      [role="dialog"][data-state="open"] [role="combobox"]:focus {
        border-color: rgba(210, 170, 255, 0.85) !important;
        box-shadow: 0 0 0 3px rgba(160, 100, 240, 0.18) !important;
      }

      /* Reset / Cancel buttons */
      [role="dialog"][data-state="open"] button:not([role="combobox"]):not([data-state]) {
        border-radius: 10px !important;
        transition: background 160ms ease, transform 120ms ease;
      }
      [role="dialog"][data-state="open"] button:not([role="combobox"]):not([data-state]):hover {
        background: rgba(255, 255, 255, 0.07) !important;
      }

      /* The dropdown listbox itself (rendered as a portal sibling) */
      [role="listbox"] {
        background: linear-gradient(160deg,
          rgba(30, 18, 58, 0.98) 0%,
          rgba(58, 28, 110, 0.98) 100%) !important;
        border: 1px solid rgba(170, 130, 255, 0.5) !important;
        border-radius: 12px !important;
        box-shadow:
          0 12px 40px rgba(0,0,0,0.55),
          0 0 24px rgba(160, 90, 240, 0.3) !important;
        color: #f4ecff !important;
        max-height: 60vh !important;
        overflow-y: auto !important;
      }
      [role="listbox"] [role="option"] {
        color: #f0e6ff !important;
        transition: background 120ms ease;
      }
      [role="listbox"] [role="option"]:hover,
      [role="listbox"] [role="option"][data-highlighted],
      [role="listbox"] [role="option"][aria-selected="true"] {
        background: linear-gradient(90deg,
          rgba(160, 100, 240, 0.35),
          rgba(120, 70, 200, 0.20)) !important;
        color: #fff !important;
      }

      /* Custom scrollbar inside the listbox */
      [role="listbox"]::-webkit-scrollbar { width: 8px; }
      [role="listbox"]::-webkit-scrollbar-track { background: transparent; }
      [role="listbox"]::-webkit-scrollbar-thumb {
        background: linear-gradient(180deg, rgba(180,120,255,0.6), rgba(120,70,200,0.6));
        border-radius: 8px;
      }
    `;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = css;
    document.head.appendChild(style);
  }

  /* ------------------------------------------------------------------ *
   * 2. Locate the built-in gear button (the one that opens ChatSettings)
   *    Chainlit doesn't expose a stable selector, so we try several.
   * ------------------------------------------------------------------ */
  function findGearButton() {
    const selectors = [
      '#message-composer button[aria-label*="ettings" i]',
      '#chat-input-container button[aria-label*="ettings" i]',
      'button[aria-label="Chat Settings"]',
      'button[aria-label="Open Chat Settings"]',
      'button[id*="chat-settings" i]',
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) return el;
    }
    // Last-resort heuristic: any button in the composer with a cog/gear SVG path.
    const composerBtns = document.querySelectorAll("#message-composer button, #chat-input-container button");
    for (const btn of composerBtns) {
      const svg = btn.querySelector("svg");
      if (!svg) continue;
      const html = svg.outerHTML.toLowerCase();
      if (html.includes("settings") || html.includes("cog") || html.includes("gear")) return btn;
    }
    return null;
  }

  /* ------------------------------------------------------------------ *
   * 3. Build & mount the pill button
   * ------------------------------------------------------------------ */
  function buildButton() {
    const btn = document.createElement("button");
    btn.id = BTN_ID;
    btn.type = "button";
    btn.title = "Switch LLM model for this session";
    btn.setAttribute("aria-label", "Open model picker");
    btn.innerHTML = `
      <span class="va-mp-icon" aria-hidden="true">🤖</span>
      <span class="va-mp-label">Models</span>
      <svg class="va-mp-chev" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
        <path d="M2 3.5 L5 6.5 L8 3.5" fill="none" stroke="currentColor"
              stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    `;
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const gear = findGearButton();
      if (!gear) {
        console.warn("[model-picker] Settings gear not found in DOM.");
        return;
      }
      try {
        gear.click();
        btn.classList.remove("va-mp-flash");
        // Re-trigger CSS animation on every click.
        void btn.offsetWidth;
        btn.classList.add("va-mp-flash");
      } catch (err) {
        console.warn("[model-picker] click forward failed:", err);
      }
    });
    return btn;
  }

  function mountIfNeeded() {
    try {
      if (!document.body) return;
      // Always try to hide the gear (covers cases where CSS selectors miss it)
      hideGearButton();
      if (document.getElementById(BTN_ID)) return;
      // Only mount once the chat UI exists — avoids appearing on login pages.
      if (!document.querySelector("#message-composer, #chat-input-container, #chat-input")) return;
      document.body.appendChild(buildButton());
    } catch (err) {
      console.warn("[model-picker] mount failed:", err);
    }
  }

  /* Hide the built-in gear button regardless of aria-label, by detecting
     a cog/gear SVG inside the composer. Runs on every DOM mutation. */
  function hideGearButton() {
    try {
      const composer = document.querySelector("#message-composer, #chat-input-container");
      if (!composer) return;
      const btns = composer.querySelectorAll("button");
      btns.forEach((b) => {
        if (b.id === BTN_ID) return;
        if (b.dataset.vaGearHidden === "1") return;
        const svg = b.querySelector("svg");
        if (!svg) return;
        const html = svg.outerHTML.toLowerCase();
        // Heuristic: cog/gear/settings icons all reference these terms,
        // OR contain a circle + multiple short stroke paths (typical cog).
        const looksLikeGear =
          html.includes("settings") ||
          html.includes("cog") ||
          html.includes("gear") ||
          /lucide-settings/.test(html) ||
          (html.includes("<circle") && (html.match(/<path/g) || []).length >= 1 &&
            (b.getAttribute("aria-label") || "").toLowerCase().match(/setting|config|option/));
        const label = (b.getAttribute("aria-label") || "").toLowerCase();
        if (looksLikeGear || label.includes("setting") || label.includes("config")) {
          b.classList.add("va-hide-settings-gear");
          b.dataset.vaGearHidden = "1";
        }
      });
    } catch (_) { /* never block */ }
  }

  /* ------------------------------------------------------------------ *
   * 4. Boot — inject styles, mount, and re-mount on DOM churn
   * ------------------------------------------------------------------ */

  /* ── Dynamic active-model label (frontend-only, zero backend cost) ──
     The Chainlit ChatSettings dropdown trigger always shows the current
     selection (e.g. "        🟢  GPT-4.1"). We read its text whenever
     the settings dialog renders, parse the model name + icon, and write
     it onto the pill button. No server calls, no listeners on the chat
     socket — just DOM observation that's already happening for mounting. */

  let _vaLastLabel = null;

  function parseSettingsTrigger(rawText) {
    if (!rawText) return null;
    // Trigger text looks like:  "        🟢  GPT-4.1"  (with leading spaces)
    // or for headers/fallback:  "⚪  @openai/gpt-4.1  (from .env)"
    const text = rawText.trim();
    if (!text) return null;
    // Skip if this is a section header sentinel.
    if (text.startsWith("━")) return null;
    // First "word" containing only emoji-ish chars is the provider icon.
    const m = text.match(/^(\S+)\s+(.+?)(?:\s+\([^)]+\))?$/);
    if (m) {
      return { icon: m[1], label: m[2].trim() };
    }
    return { icon: "🤖", label: text };
  }

  function readActiveModelFromSettings() {
    try {
      // The trigger is a [role="combobox"] inside the open settings dialog.
      const dialog = document.querySelector('[role="dialog"][data-state="open"]');
      if (!dialog) return null;
      const trigger = dialog.querySelector('[role="combobox"], button[role="combobox"]');
      if (!trigger) return null;
      // The visible label is in the first <span> or trigger text content.
      const span = trigger.querySelector("span");
      const raw = (span && span.textContent) || trigger.textContent || "";
      return parseSettingsTrigger(raw);
    } catch (_) { return null; }
  }

  function updatePillLabel(meta) {
    try {
      if (!meta || !meta.label) return;
      const sig = meta.icon + "|" + meta.label;
      if (sig === _vaLastLabel) return;       // skip redundant writes
      _vaLastLabel = sig;
      const btn = document.getElementById(BTN_ID);
      if (!btn) return;
      const iconEl = btn.querySelector(".va-mp-icon");
      const labelEl = btn.querySelector(".va-mp-label");
      if (iconEl && meta.icon) iconEl.textContent = meta.icon;
      if (labelEl) labelEl.textContent = meta.label;
      btn.title = `Active LLM: ${meta.label} — click to switch`;
    } catch (_) { /* never block */ }
  }

  /* When the user picks an option in the listbox, the trigger text
     updates a moment later. We also catch the option click directly
     for an instant pill update. */
  function watchListboxClicks() {
    try {
      document.addEventListener("click", (e) => {
        const opt = e.target && e.target.closest && e.target.closest('[role="option"]');
        if (!opt) return;
        const raw = (opt.textContent || "").trim();
        const meta = parseSettingsTrigger(raw);
        if (meta) updatePillLabel(meta);
      }, true);
    } catch (_) { /* never block */ }
  }

  /* ------------------------------------------------------------------ *
   * Reset-button override
   *
   * Chainlit 2.11.0's built-in Reset only undoes edits made WHILE the
   * dialog is open (snaps back to the value the field had when the
   * dialog opened). It does NOT revert to the widget's `initial_value`
   * from Python. So if the user previously confirmed Claude, then opens
   * Settings again, built-in Reset does nothing useful.
   *
   * We want Reset to mean: "go back to DEFAULT_MODEL from .env".
   * Python embeds that id in the Select widget's description as:
   *
   *     "Choose the model for this session. Reset → <model-id>"
   *
   * We parse it out, intercept the Reset click, open the listbox and
   * pick the matching option programmatically.
   * ------------------------------------------------------------------ */
  function getDefaultModelIdFromDescription() {
    try {
      const dialog = document.querySelector(
        '[role="dialog"][data-state="open"]:has([role="combobox"])'
      );
      if (!dialog) return null;
      const text = (dialog.innerText || "").replace(/\s+/g, " ");
      const m = text.match(/Reset\s*[→\->:]+\s*(\S+)/i);
      return m ? m[1].trim() : null;
    } catch (_) { return null; }
  }

  function findOptionMatching(defaultId) {
    const opts = document.querySelectorAll('[role="listbox"] [role="option"]');
    const wanted = defaultId.toLowerCase();
    const tail = (defaultId.split("/").pop() || "").toLowerCase();
    console.log("[model-picker] Reset: looking for", defaultId, "tail=", tail,
                "in", opts.length, "options");
    for (const opt of opts) {
      const dv = (opt.getAttribute("data-value") || "").toLowerCase();
      const txt = (opt.textContent || "").trim().toLowerCase();
      if (dv === wanted || txt.includes(wanted)) return opt;
      if (tail && (dv.endsWith(tail) || txt.includes(tail))) return opt;
    }
    return null;
  }

  function resetToDefaultModel() {
    const defaultId = getDefaultModelIdFromDescription();
    console.log("[model-picker] Reset clicked, defaultId=", defaultId);
    if (!defaultId) {
      console.warn("[model-picker] Reset: no default id found in description");
      return;
    }
    const dialog = document.querySelector(
      '[role="dialog"][data-state="open"]:has([role="combobox"])'
    );
    const combo = dialog && dialog.querySelector('[role="combobox"]');
    if (!combo) { console.warn("[model-picker] Reset: combobox not found"); return; }

    // Open the listbox so options exist, then pick the default.
    combo.click();

    // Retry a few times — Radix portals can take a moment to mount.
    let attempts = 0;
    const tryPick = () => {
      attempts++;
      const opt = findOptionMatching(defaultId);
      if (opt) {
        console.log("[model-picker] Reset: clicking option", opt.textContent.trim());
        opt.click();
        return;
      }
      if (attempts < 10) {
        setTimeout(tryPick, 60);
      } else {
        try { combo.click(); } catch (_) {}
        console.warn("[model-picker] Reset: option for", defaultId, "not in DOM after retries");
      }
    };
    setTimeout(tryPick, 80);
  }

  function watchResetButton() {
    try {
      document.addEventListener("click", (e) => {
        const btn = e.target && e.target.closest && e.target.closest("button");
        if (!btn) return;
        const dialog = btn.closest('[role="dialog"][data-state="open"]');
        if (!dialog) return;
        if (!dialog.querySelector('[role="combobox"]')) return; // settings panel only
        if ((btn.textContent || "").trim().toLowerCase() !== "reset") return;
        e.preventDefault();
        e.stopImmediatePropagation();
        e.stopPropagation();
        resetToDefaultModel();
      }, true);
    } catch (_) { /* never block */ }
  }

  function syncFromDom() {
    const meta = readActiveModelFromSettings();
    if (meta) updatePillLabel(meta);
  }

  function boot() {
    try {
      injectStyles();
      mountIfNeeded();
      watchListboxClicks();
      watchResetButton();
      // Initial sync attempt (settings dialog may not be open yet).
      syncFromDom();
      const obs = new MutationObserver(() => {
        mountIfNeeded();
        syncFromDom();
      });
      obs.observe(document.body, { childList: true, subtree: true });
    } catch (err) {
      console.warn("[model-picker] boot failed:", err);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
