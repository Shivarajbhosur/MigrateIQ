/**
 * Validation Agent — React Neural-Core Cinematic HUD
 * ---------------------------------------------------
 * Premium AI-themed visual layer rendered with React 18 + Framer Motion.
 * Pointer-events-none overlay; never intercepts Chainlit input.
 *
 * Scene composition:
 *   1. Particle field      — drifting bokeh
 *   2. Neural graph        — SVG nodes + pulsing synapse paths
 *   3. Neural core orb     — concentric rotating rings + scanning sweep
 *   4. Scan beam           — horizontal sweep across the viewport
 *   5. Holographic floor   — perspective grid at the bottom edge
 *   6. Data stream         — vertical glyph rain on left edge
 *   7. Mission HUD         — top-right glass panel with live telemetry
 *   8. Status footer       — bottom-left mono strip
 *   9. Corner brackets     — frame markers
 *
 * Loads on idle, fails silently if CDN blocked.
 */

const REACT_VERSION = "18.3.1";
const MOTION_VERSION = "11.3.19";
const HTM_VERSION = "3.1.1";

const ROOT_ID = "va-cinematic-root";
const BOOT_FLAG = "__vaReactHudMounted";
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

const cdn = (spec) => `https://esm.sh/${spec}`;
const importReact = () => import(cdn(`react@${REACT_VERSION}`));
const importReactDom = () =>
    import(cdn(`react-dom@${REACT_VERSION}/client?deps=react@${REACT_VERSION}`));
const importMotion = () =>
    import(cdn(`framer-motion@${MOTION_VERSION}?deps=react@${REACT_VERSION}`));
const importHtm = () => import(cdn(`htm@${HTM_VERSION}`));

async function bootHud() {
    if (window[BOOT_FLAG]) return;
    window[BOOT_FLAG] = true;

    const reducedInitial = window.matchMedia(REDUCED_MOTION_QUERY).matches;

    let React, ReactDom, motionMod, htmMod;
    try {
        [React, ReactDom, motionMod, htmMod] = await Promise.all([
            importReact(),
            importReactDom(),
            importMotion(),
            importHtm(),
        ]);
    } catch (err) {
        window[BOOT_FLAG] = false;
        // eslint-disable-next-line no-console
        console.warn("[va-hud] esm.sh unavailable, CSS-only fallback", err);
        return;
    }

    const {
        useEffect,
        useMemo,
        useRef,
        useState,
        createElement,
        StrictMode,
        Fragment,
    } = React;
    const { createRoot } = ReactDom;
    const { motion, AnimatePresence } = motionMod;
    const htm = htmMod.default || htmMod;
    const html = htm.bind(createElement);

    const NBSP = "\u00A0";

    /* Hooks */

    const BASELINE_RE = /\bP\d{4,6}-[A-Z]{1,6}\d{2,8}[A-Z]?\b/;

    function useBaselineDetection() {
        const [baseline, setBaseline] = useState(null);
        useEffect(() => {
            const detect = () => {
                const nodes = document.querySelectorAll(
                    ".user-message, .ai-message, [class*=user-message], [class*=ai-message]"
                );
                for (let i = nodes.length - 1; i >= 0; i--) {
                    const m = (nodes[i].textContent || "").match(BASELINE_RE);
                    if (m) {
                        setBaseline((prev) => (prev === m[0] ? prev : m[0]));
                        return;
                    }
                }
            };
            detect();
            const obs = new MutationObserver(detect);
            obs.observe(document.body, { childList: true, subtree: true });
            return () => obs.disconnect();
        }, []);
        return baseline;
    }

    function useActivityPulse() {
        const [pulse, setPulse] = useState(0);
        useEffect(() => {
            const obs = new MutationObserver((mutations) => {
                let delta = 0;
                for (const mut of mutations) {
                    for (const node of mut.addedNodes) {
                        if (node.nodeType !== 1) continue;
                        const cls = node.className || "";
                        if (
                            typeof cls === "string" &&
                            (cls.includes("ai-message") ||
                                cls.includes("user-message"))
                        ) {
                            delta += 1;
                        }
                    }
                }
                if (delta) setPulse((p) => p + delta);
            });
            obs.observe(document.body, { childList: true, subtree: true });
            return () => obs.disconnect();
        }, []);
        return pulse;
    }

    function useClock() {
        const [now, setNow] = useState(() => new Date());
        useEffect(() => {
            const t = setInterval(() => setNow(new Date()), 1000);
            return () => clearInterval(t);
        }, []);
        return now;
    }

    function useReducedMotion() {
        const [reduced, setReduced] = useState(reducedInitial);
        useEffect(() => {
            const mq = window.matchMedia(REDUCED_MOTION_QUERY);
            const onChange = (e) => setReduced(e.matches);
            if (mq.addEventListener) {
                mq.addEventListener("change", onChange);
                return () => mq.removeEventListener("change", onChange);
            }
            mq.addListener(onChange);
            return () => mq.removeListener(onChange);
        }, []);
        return reduced;
    }

    /* Particle field */

    function ParticleField({ paused }) {
        const canvasRef = useRef(null);
        useEffect(() => {
            const canvas = canvasRef.current;
            if (!canvas) return undefined;
            const ctx = canvas.getContext("2d", { alpha: true });
            if (!ctx) return undefined;
            const dpr = Math.min(window.devicePixelRatio || 1, 2);
            const particles = Array.from({ length: 90 }, () => ({
                x: Math.random(),
                y: Math.random(),
                vx: (Math.random() - 0.5) * 0.00022,
                vy: (Math.random() - 0.5) * 0.00022,
                r: Math.random() * 1.8 + 0.6,
                hue:
                    Math.random() < 0.55
                        ? 178
                        : Math.random() < 0.85
                        ? 212
                        : 268,
                phase: Math.random() * Math.PI * 2,
            }));
            let raf = 0;
            let w = 0;
            let h = 0;
            let alive = true;
            const resize = () => {
                w = canvas.clientWidth;
                h = canvas.clientHeight;
                canvas.width = Math.max(1, Math.round(w * dpr));
                canvas.height = Math.max(1, Math.round(h * dpr));
                ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            };
            const tick = (ts) => {
                if (!alive) return;
                if (paused) {
                    raf = requestAnimationFrame(tick);
                    return;
                }
                ctx.clearRect(0, 0, w, h);
                for (const p of particles) {
                    p.x += p.vx;
                    p.y += p.vy;
                    if (p.x < 0 || p.x > 1) p.vx *= -1;
                    if (p.y < 0 || p.y > 1) p.vy *= -1;
                    const x = p.x * w;
                    const y = p.y * h;
                    const breath =
                        0.55 + Math.sin(ts * 0.0019 + p.phase) * 0.45;
                    const radius = p.r * 7 * breath;
                    const g = ctx.createRadialGradient(x, y, 0, x, y, radius);
                    g.addColorStop(0, `hsla(${p.hue}, 92%, 72%, 0.6)`);
                    g.addColorStop(1, `hsla(${p.hue}, 92%, 72%, 0)`);
                    ctx.fillStyle = g;
                    ctx.beginPath();
                    ctx.arc(x, y, radius, 0, Math.PI * 2);
                    ctx.fill();
                }
                raf = requestAnimationFrame(tick);
            };
            resize();
            raf = requestAnimationFrame(tick);
            const onResize = () => resize();
            window.addEventListener("resize", onResize, { passive: true });
            return () => {
                alive = false;
                cancelAnimationFrame(raf);
                window.removeEventListener("resize", onResize);
            };
        }, [paused]);
        return html`<canvas
            ref=${canvasRef}
            className="va-hud-canvas"
            aria-hidden="true"
        />`;
    }

    /* Neural graph */

    const NEURAL_NODES = [
        { x: 12, y: 22 },
        { x: 28, y: 14 },
        { x: 42, y: 30 },
        { x: 22, y: 44 },
        { x: 50, y: 50 },
        { x: 8, y: 60 },
        { x: 34, y: 70 },
        { x: 58, y: 18 },
        { x: 70, y: 38 },
        { x: 64, y: 64 },
        { x: 88, y: 28 },
        { x: 92, y: 56 },
        { x: 78, y: 80 },
        { x: 16, y: 84 },
        { x: 46, y: 88 },
    ];
    const NEURAL_EDGES = [
        [0, 1], [0, 3], [1, 2], [1, 7], [2, 4], [2, 8],
        [3, 4], [3, 5], [4, 6], [4, 9], [5, 6], [6, 14],
        [7, 8], [7, 10], [8, 9], [8, 11], [9, 12], [10, 11],
        [11, 12], [12, 14], [5, 13], [13, 14], [3, 6], [9, 11],
    ];

    function NeuralGraph({ paused }) {
        return html`
            <svg
                className="va-hud-neural"
                viewBox="0 0 100 100"
                preserveAspectRatio="xMidYMid slice"
                aria-hidden="true"
            >
                <defs>
                    <radialGradient id="va-node-grad" cx="50%" cy="50%" r="50%">
                        <stop offset="0%" stopColor="#9af3ea" stopOpacity="1" />
                        <stop offset="60%" stopColor="#70e6dc" stopOpacity="0.7" />
                        <stop offset="100%" stopColor="#70e6dc" stopOpacity="0" />
                    </radialGradient>
                    <linearGradient
                        id="va-edge-grad"
                        x1="0%"
                        y1="0%"
                        x2="100%"
                        y2="0%"
                    >
                        <stop offset="0%" stopColor="#70e6dc" stopOpacity="0" />
                        <stop
                            offset="50%"
                            stopColor="#83bbff"
                            stopOpacity="0.85"
                        />
                        <stop
                            offset="100%"
                            stopColor="#bd8cff"
                            stopOpacity="0"
                        />
                    </linearGradient>
                </defs>
                <g>
                    ${NEURAL_EDGES.map(([a, b], i) => {
                        const pa = NEURAL_NODES[a];
                        const pb = NEURAL_NODES[b];
                        return html`
                            <${motion.line}
                                key=${`e${i}`}
                                x1=${pa.x}
                                y1=${pa.y}
                                x2=${pb.x}
                                y2=${pb.y}
                                stroke="url(#va-edge-grad)"
                                strokeWidth="0.18"
                                strokeLinecap="round"
                                initial=${{ opacity: 0.08, pathLength: 0 }}
                                animate=${
                                    paused
                                        ? { opacity: 0.18, pathLength: 1 }
                                        : {
                                              opacity: [0.05, 0.6, 0.05],
                                              pathLength: [0, 1, 0],
                                          }
                                }
                                transition=${
                                    paused
                                        ? { duration: 0.3 }
                                        : {
                                              duration: 5 + (i % 5) * 0.9,
                                              repeat: Infinity,
                                              ease: "easeInOut",
                                              delay: (i * 0.27) % 4,
                                          }
                                }
                            />
                        `;
                    })}
                </g>
                <g>
                    ${NEURAL_NODES.map(
                        (n, i) => html`
                            <${motion.circle}
                                key=${`n${i}`}
                                cx=${n.x}
                                cy=${n.y}
                                r="0.9"
                                fill="url(#va-node-grad)"
                                initial=${{ opacity: 0.4, scale: 0.8 }}
                                animate=${
                                    paused
                                        ? { opacity: 0.7, scale: 1 }
                                        : {
                                              opacity: [0.3, 1, 0.3],
                                              scale: [0.7, 1.4, 0.7],
                                          }
                                }
                                transition=${
                                    paused
                                        ? { duration: 0.3 }
                                        : {
                                              duration: 3.2 + (i % 4) * 0.5,
                                              repeat: Infinity,
                                              ease: "easeInOut",
                                              delay: (i * 0.21) % 3,
                                          }
                                }
                            />
                        `
                    )}
                </g>
            </svg>
        `;
    }

    /* Neural core orb */

    function NeuralCoreOrb({ paused, pulse }) {
        const rings = [
            { r: 46, dur: 22, dir: 1, opacity: 0.7, dash: "3 4" },
            { r: 36, dur: 16, dir: -1, opacity: 0.55, dash: "5 6" },
            { r: 26, dur: 11, dir: 1, opacity: 0.45, dash: "2 3" },
        ];
        return html`
            <div className="va-hud-orb" aria-hidden="true">
                <svg viewBox="0 0 100 100" className="va-hud-orb-svg">
                    <defs>
                        <radialGradient
                            id="va-orb-core"
                            cx="50%"
                            cy="50%"
                            r="50%"
                        >
                            <stop
                                offset="0%"
                                stopColor="#ffffff"
                                stopOpacity="1"
                            />
                            <stop
                                offset="40%"
                                stopColor="#9af3ea"
                                stopOpacity="0.85"
                            />
                            <stop
                                offset="80%"
                                stopColor="#5fb4ff"
                                stopOpacity="0.25"
                            />
                            <stop
                                offset="100%"
                                stopColor="#5fb4ff"
                                stopOpacity="0"
                            />
                        </radialGradient>
                        <linearGradient
                            id="va-orb-ring"
                            x1="0%"
                            y1="0%"
                            x2="100%"
                            y2="100%"
                        >
                            <stop offset="0%" stopColor="#70e6dc" />
                            <stop offset="50%" stopColor="#83bbff" />
                            <stop offset="100%" stopColor="#bd8cff" />
                        </linearGradient>
                    </defs>

                    ${rings.map(
                        (ring, i) => html`
                            <${motion.circle}
                                key=${i}
                                cx="50"
                                cy="50"
                                r=${ring.r}
                                fill="none"
                                stroke="url(#va-orb-ring)"
                                strokeWidth="0.6"
                                strokeDasharray=${ring.dash}
                                opacity=${ring.opacity}
                                style=${{ transformOrigin: "50% 50%" }}
                                animate=${
                                    paused
                                        ? { rotate: 0 }
                                        : { rotate: ring.dir * 360 }
                                }
                                transition=${
                                    paused
                                        ? { duration: 0.3 }
                                        : {
                                              duration: ring.dur,
                                              repeat: Infinity,
                                              ease: "linear",
                                          }
                                }
                            />
                        `
                    )}

                    <${motion.circle}
                        cx="50"
                        cy="50"
                        r="14"
                        fill="url(#va-orb-core)"
                        animate=${
                            paused
                                ? { opacity: 0.85, scale: 1 }
                                : {
                                      opacity: [0.6, 1, 0.6],
                                      scale: [0.92, 1.08, 0.92],
                                  }
                        }
                        transition=${
                            paused
                                ? { duration: 0.3 }
                                : {
                                      duration: 3.4,
                                      repeat: Infinity,
                                      ease: "easeInOut",
                                  }
                        }
                        style=${{ transformOrigin: "50% 50%" }}
                    />
                </svg>
            </div>
        `;
    }

    /* Scan beam */

    function ScanBeam({ paused }) {
        if (paused) return null;
        return html`
            <${motion.div}
                className="va-hud-scan"
                aria-hidden="true"
                initial=${{ y: "-10vh", opacity: 0 }}
                animate=${{ y: "110vh", opacity: [0, 0.75, 0] }}
                transition=${{
                    duration: 7,
                    repeat: Infinity,
                    ease: "linear",
                    repeatDelay: 3,
                }}
            />
        `;
    }

    /* Holographic floor grid */

    function HoloGrid({ paused }) {
        return html`
            <div className="va-hud-holo" aria-hidden="true">
                <${motion.div}
                    className="va-hud-holo-grid"
                    animate=${
                        paused
                            ? { backgroundPositionY: "0px" }
                            : { backgroundPositionY: ["0px", "80px"] }
                    }
                    transition=${
                        paused
                            ? { duration: 0.3 }
                            : {
                                  duration: 6,
                                  repeat: Infinity,
                                  ease: "linear",
                              }
                    }
                />
            </div>
        `;
    }

    /* Data stream (left edge glyph rain) */

    const GLYPHS = "01∇λΣΨ◇△○✕≡⟨⟩";
    function DataColumn({ index, paused }) {
        const seed = useMemo(() => {
            const chars = [];
            for (let i = 0; i < 18; i++) {
                chars.push(GLYPHS[(i * 7 + index * 3) % GLYPHS.length]);
            }
            return chars.join(" ");
        }, [index]);
        return html`
            <${motion.div}
                className="va-hud-stream-col"
                initial=${{ y: "-30%", opacity: 0 }}
                animate=${
                    paused
                        ? { y: "0%", opacity: 0.2 }
                        : { y: ["-30%", "120%"], opacity: [0, 0.55, 0] }
                }
                transition=${
                    paused
                        ? { duration: 0.3 }
                        : {
                              duration: 9 + (index % 3) * 2,
                              repeat: Infinity,
                              ease: "linear",
                              delay: (index % 4) * 1.5,
                          }
                }
            >
                ${seed}
            </${motion.div}>
        `;
    }
    function DataStream({ paused }) {
        return html`
            <div className="va-hud-stream" aria-hidden="true">
                ${[0, 1, 2, 3, 4, 5].map(
                    (i) =>
                        html`<${DataColumn}
                            key=${i}
                            index=${i}
                            paused=${paused}
                        />`
                )}
            </div>
        `;
    }

    /* Corner brackets */

    function CornerBrackets({ paused }) {
        const corners = ["tl", "tr", "bl", "br"];
        return html`
            <div className="va-hud-corners" aria-hidden="true">
                ${corners.map(
                    (c) => html`
                        <${motion.span}
                            key=${c}
                            className=${`va-hud-corner va-hud-corner-${c}`}
                            initial=${{ opacity: 0, scale: 0.94 }}
                            animate=${
                                paused
                                    ? { opacity: 0.7, scale: 1 }
                                    : {
                                          opacity: [0.45, 0.95, 0.45],
                                          scale: [0.985, 1.015, 0.985],
                                      }
                            }
                            transition=${
                                paused
                                    ? { duration: 0.3 }
                                    : {
                                          duration: 4.2,
                                          repeat: Infinity,
                                          ease: "easeInOut",
                                      }
                            }
                        />
                    `
                )}
            </div>
        `;
    }

    /* Mission HUD */

    function MissionHud({ baseline, pulse, clock, paused }) {
        const hh = String(clock.getHours()).padStart(2, "0");
        const mm = String(clock.getMinutes()).padStart(2, "0");
        const ss = String(clock.getSeconds()).padStart(2, "0");
        const yyyy = clock.getFullYear();
        const mo = String(clock.getMonth() + 1).padStart(2, "0");
        const dd = String(clock.getDate()).padStart(2, "0");
        return html`
            <${motion.aside}
                className="va-hud-panel va-hud-mission"
                aria-hidden="true"
                initial=${{ opacity: 0, y: -14 }}
                animate=${{ opacity: 1, y: 0 }}
                transition=${{
                    duration: 0.7,
                    ease: [0.16, 1, 0.3, 1],
                    delay: 0.35,
                }}
            >
                <div className="va-hud-row va-hud-row-head">
                    <${motion.span}
                        className="va-hud-dot"
                        animate=${
                            paused
                                ? { opacity: 0.8 }
                                : {
                                      opacity: [0.4, 1, 0.4],
                                      scale: [1, 1.32, 1],
                                  }
                        }
                        transition=${
                            paused
                                ? { duration: 0.3 }
                                : {
                                      duration: 2.4,
                                      repeat: Infinity,
                                      ease: "easeInOut",
                                  }
                        }
                    />
                    <span className="va-hud-label">AI${NBSP}ASSISTANT</span>
                    <span className="va-hud-sep">·</span>
                    <span className="va-hud-time">${hh}:${mm}:${ss}</span>
                </div>
                <div className="va-hud-row va-hud-row-detail">
                    <span className="va-hud-key">DATE</span>
                    <span className="va-hud-value va-hud-mono">${yyyy}-${mo}-${dd}</span>
                </div>
                <div className="va-hud-row va-hud-row-detail">
                    <span className="va-hud-key">BASELINE</span>
                    <${AnimatePresence} mode="popLayout" initial=${false}>
                        <${motion.span}
                            key=${baseline || "idle"}
                            className=${`va-hud-value ${
                                baseline
                                    ? "va-hud-value-active"
                                    : "va-hud-value-idle"
                            }`}
                            initial=${{ opacity: 0, y: 6, filter: "blur(4px)" }}
                            animate=${{
                                opacity: 1,
                                y: 0,
                                filter: "blur(0px)",
                            }}
                            exit=${{ opacity: 0, y: -6, filter: "blur(4px)" }}
                            transition=${{
                                duration: 0.45,
                                ease: [0.16, 1, 0.3, 1],
                            }}
                        >
                            ${baseline || "AWAITING"}
                        </${motion.span}>
                    </${AnimatePresence}>
                </div>
                <div className="va-hud-row va-hud-row-detail">
                    <span className="va-hud-key">ACTIVITY</span>
                    <span className="va-hud-bar-track">
                        <${motion.span}
                            className="va-hud-bar"
                            animate=${
                                paused
                                    ? { scaleX: 0.7 }
                                    : { scaleX: [0.35, 1, 0.6, 0.9, 0.4] }
                            }
                            transition=${
                                paused
                                    ? { duration: 0.3 }
                                    : {
                                          duration: 2.8,
                                          repeat: Infinity,
                                          ease: "easeInOut",
                                      }
                            }
                        />
                    </span>
                </div>
            </${motion.aside}>
        `;
    }

    /* Signal rail */

    function SignalRail({ pulse, paused }) {
        const bars = 22;
        return html`
            <div className="va-hud-rail" aria-hidden="true">
                ${Array.from({ length: bars }).map(
                    (_, i) => html`
                        <${motion.span}
                            key=${i}
                            className="va-hud-rail-bar"
                            animate=${
                                paused
                                    ? { scaleY: 0.3 }
                                    : {
                                          scaleY: [
                                              0.2,
                                              0.85 +
                                                  Math.sin(i + pulse * 0.6) *
                                                      0.15,
                                              0.35,
                                          ],
                                      }
                            }
                            transition=${
                                paused
                                    ? { duration: 0.3 }
                                    : {
                                          duration: 1.6 + (i % 5) * 0.18,
                                          repeat: Infinity,
                                          ease: "easeInOut",
                                          delay: i * 0.04,
                                      }
                            }
                        />
                    `
                )}
            </div>
        `;
    }

    /* Status footer */

    function StatusFooter({ baseline, clock, paused }) {
        const epoch = clock.toISOString().slice(0, 10).replace(/-/g, ".");
        return html`
            <${motion.div}
                className="va-hud-panel va-hud-footer"
                aria-hidden="true"
                initial=${{ opacity: 0, y: 14 }}
                animate=${{ opacity: 1, y: 0 }}
                transition=${{
                    duration: 0.6,
                    ease: [0.16, 1, 0.3, 1],
                    delay: 0.5,
                }}
            >
                <span className="va-hud-tag">DATE</span>
                <span className="va-hud-value va-hud-mono">${epoch}</span>
                <span className="va-hud-sep">·</span>
                <span className="va-hud-tag">CONNECTION</span>
                <span className="va-hud-value">SECURE${NBSP}LINK</span>
                <span className="va-hud-sep">·</span>
                <span className="va-hud-tag">BASELINE</span>
                <span className="va-hud-value">${baseline || "—"}</span>
                <${motion.span}
                    className="va-hud-footer-glow"
                    animate=${
                        paused
                            ? { opacity: 0.4 }
                            : { opacity: [0.25, 0.75, 0.25] }
                    }
                    transition=${
                        paused
                            ? { duration: 0.3 }
                            : {
                                  duration: 3.6,
                                  repeat: Infinity,
                                  ease: "easeInOut",
                              }
                    }
                />
            </${motion.div}>
        `;
    }

    /* App */

    function App() {
        const baseline = useBaselineDetection();
        const pulse = useActivityPulse();
        const clock = useClock();
        const reduced = useReducedMotion();
        return html`
            <${Fragment}>
                <div className="va-hud-stage" aria-hidden="true">
                    <${ParticleField} paused=${reduced} />
                    <${NeuralGraph} paused=${reduced} />
                    <${HoloGrid} paused=${reduced} />
                    <${DataStream} paused=${reduced} />
                    <${ScanBeam} paused=${reduced} />
                    <${CornerBrackets} paused=${reduced} />
                </div>
                <${NeuralCoreOrb} paused=${reduced} pulse=${pulse} />
                <${MissionHud}
                    baseline=${baseline}
                    pulse=${pulse}
                    clock=${clock}
                    paused=${reduced}
                />
                <${SignalRail} pulse=${pulse} paused=${reduced} />
            </${Fragment}>
        `;
    }

    /* Mount */

    let mountNode = document.getElementById(ROOT_ID);
    if (!mountNode) {
        mountNode = document.createElement("div");
        mountNode.id = ROOT_ID;
        mountNode.setAttribute("aria-hidden", "true");
        document.body.appendChild(mountNode);
    }
    document.body.classList.add("va-hud-active");
    const root = createRoot(mountNode);
    root.render(createElement(StrictMode, null, createElement(App)));
}

function scheduleBoot() {
    const run = () => {
        bootHud().catch(() => {
            window[BOOT_FLAG] = false;
        });
    };
    if ("requestIdleCallback" in window) {
        window.requestIdleCallback(run, { timeout: 2500 });
    } else {
        setTimeout(run, 600);
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scheduleBoot, { once: true });
} else {
    scheduleBoot();
}
