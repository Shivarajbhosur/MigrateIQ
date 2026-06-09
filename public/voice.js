(() => {
  "use strict";

  // --- Load companion modules (kept in separate files so voice logic is untouched) ---
  // celebrate.js: cinematic completion animation. Failure is silently ignored.
  try {
    if (!document.querySelector('script[data-va-module="celebrate"]')) {
      const s = document.createElement("script");
      s.src = "/public/celebrate.js?v=20260529-celebrate-1";
      s.async = true;
      s.dataset.vaModule = "celebrate";
      document.head.appendChild(s);
    }
  } catch (_) { /* never block voice features */ }

  // model-picker.js: top-left "🤖 Models" pill that opens the LLM picker
  // (drives the same ChatSettings panel built in app.py). Failure ignored.
  try {
    if (!document.querySelector('script[data-va-module="model-picker"]')) {
      const s = document.createElement("script");
      s.src = "/public/model-picker.js?v=20260604-models-13";
      s.async = true;
      s.dataset.vaModule = "model-picker";
      document.head.appendChild(s);
    }
  } catch (_) { /* never block voice features */ }

  const BUTTON_ID = "va-voice-button";
  const LISTENING_CLASS = "va-voice-listening";
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  let recognition = null;
  let listening = false;

  function getComposer() {
    return document.querySelector("#message-composer");
  }

  function getInput() {
    return (
      document.querySelector("#chat-input") ||
      document.querySelector("textarea[placeholder]") ||
      document.querySelector("textarea")
    );
  }

  function normalizeVoiceText(rawText) {
    let text = (rawText || "")
      .trim()
      .replace(/\s*(?:hyphen|dash)\s*/gi, "-")
      .replace(/[。.!?,;:]+/g, " ")
      .replace(/\s+/g, " ")
      .replace(/\s*-\s*/g, "-");

    text = text.replace(
      /\b([Pp])\s*(\d{4,6})[-\s]+([A-Za-z]{2,6})[-\s]*(\d{2,4})[-\s]*([A-Za-z]?)\b/g,
      (_match, prefix, digits, programPrefix, programDigits, suffix) => {
        return `${prefix.toUpperCase()}${digits}-${programPrefix.toUpperCase()}${programDigits}${suffix.toUpperCase()}`;
      }
    );

    return text;
  }

  function setInputValue(input, value) {
    const prototype = Object.getPrototypeOf(input);
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");

    if (descriptor && typeof descriptor.set === "function") {
      descriptor.set.call(input, value);
    } else {
      input.value = value;
    }

    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.focus();

    try {
      input.setSelectionRange(value.length, value.length);
    } catch (_error) {
      // Some input implementations do not expose selection APIs.
    }
  }

  function setListeningState(button, value) {
    listening = value;
    button.classList.toggle(LISTENING_CLASS, value);
    button.setAttribute("aria-pressed", String(value));
    button.title = value ? "Listening... click to stop" : "Voice input";
  }

  function stopListening(button) {
    if (recognition && listening) {
      try {
        recognition.stop();
      } catch (_error) {
        // Browser already stopped recognition.
      }
    }
    setListeningState(button, false);
  }

  function startListening(button) {
    const input = getInput();
    if (!input || !SpeechRecognition) {
      return;
    }

    recognition = new SpeechRecognition();
    recognition.lang = navigator.language || "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => setListeningState(button, true);

    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript || "")
        .join(" ");
      const normalized = normalizeVoiceText(transcript);
      if (normalized) {
        setInputValue(input, normalized);
      }
    };

    recognition.onerror = (event) => {
      button.title = `Voice input failed: ${event.error || "unknown error"}`;
      setListeningState(button, false);
    };

    recognition.onend = () => setListeningState(button, false);

    try {
      recognition.start();
    } catch (_error) {
      setListeningState(button, false);
    }
  }

  function attachVoiceButton() {
    const composer = getComposer();
    if (!composer || document.getElementById(BUTTON_ID)) {
      return;
    }

    const button = document.createElement("button");
    button.id = BUTTON_ID;
    button.type = "button";
    button.className = "va-voice-button";
    button.setAttribute("aria-label", "Voice input");
    button.setAttribute("aria-pressed", "false");
    button.innerHTML = `
      <svg class="va-voice-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M12 14.5c1.66 0 3-1.34 3-3V6c0-1.66-1.34-3-3-3S9 4.34 9 6v5.5c0 1.66 1.34 3 3 3Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M5 10.5v1A7 7 0 0 0 19 11.5v-1" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M12 18.5V22" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M8.5 22h7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    `;

    if (!SpeechRecognition) {
      button.disabled = true;
      button.classList.add("va-voice-unsupported");
      button.title = "Voice input is not supported in this browser";
    } else {
      button.title = "Voice input";
      button.addEventListener("click", () => {
        if (listening) {
          stopListening(button);
        } else {
          startListening(button);
        }
      });
    }

    composer.appendChild(button);
  }

  function startObserver() {
    attachVoiceButton();

    const observer = new MutationObserver(() => attachVoiceButton());
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startObserver, { once: true });
  } else {
    startObserver();
  }
})();


/* --------------------------------------------------------------------------
   Validation Agent — React cinematic HUD bootstrap.
   Loads public/dashboard.mjs as a deferred ES module after the Chainlit
   shell paints. Runs on idle, fails silently if the CDN is unreachable.
   Decorative only; never blocks voice input or chat interactions.
   -------------------------------------------------------------------------- */
(() => {
  if (window.__VA_REACT_HUD_BOOT__) return;
  window.__VA_REACT_HUD_BOOT__ = true;

  var boot = function () {
    import("/public/dashboard.mjs?v=20260526-neural-16").catch(function (err) {
      // Silent fallback — CSS atmosphere still applies.
      // eslint-disable-next-line no-console
      console.warn("[va-hud] dashboard module unavailable", err);
    });
  };

  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(boot, { timeout: 2500 });
  } else {
    setTimeout(boot, 800);
  }
})();
