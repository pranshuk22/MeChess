/** Move sounds made with the Web Audio API (no sound files, so nothing to license or download). A short soft tick for a move, a lower knock for a capture, two tones for a check,
 *  a double tick for castling and a rising or falling pair at the end of a game. The browser only lets sound start after a click or key press: the audio context is created then. */
let ctx: AudioContext | null = null;
let enabled = (() => { try { return localStorage.getItem("mechess.sound") !== "0"; } catch { return true; } })();

export const soundEnabled = () => enabled;
export function setSoundEnabled(v: boolean) { enabled = v; try { localStorage.setItem("mechess.sound", v ? "1" : "0"); } catch { /* not remembered */ } }

function audio(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  ctx ??= new Ctor();
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

function tone(freq: number, start: number, dur: number, gain: number, type: OscillatorType = "sine", sweepTo?: number) {
  const a = audio();
  if (!a) return;
  const t0 = a.currentTime + start;
  const o = a.createOscillator(), g = a.createGain();
  o.type = type;
  o.frequency.setValueAtTime(freq, t0);
  if (sweepTo) o.frequency.exponentialRampToValueAtTime(sweepTo, t0 + dur);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(gain, t0 + 0.006);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g).connect(a.destination);
  o.start(t0);
  o.stop(t0 + dur + 0.02);
}

export type Sound = "move" | "capture" | "check" | "castle" | "win" | "lose" | "draw";

export function play(kind: Sound) {
  if (!enabled) return;
  try {
    if (kind === "move") tone(520, 0, 0.07, 0.16, "triangle", 380);
    else if (kind === "capture") { tone(220, 0, 0.12, 0.22, "square", 120); tone(440, 0, 0.05, 0.08, "triangle"); }
    else if (kind === "check") { tone(740, 0, 0.09, 0.16, "triangle"); tone(990, 0.09, 0.12, 0.16, "triangle"); }
    else if (kind === "castle") { tone(520, 0, 0.06, 0.15, "triangle", 400); tone(520, 0.09, 0.06, 0.15, "triangle", 400); }
    else if (kind === "win") { tone(520, 0, 0.12, 0.18); tone(780, 0.12, 0.22, 0.18); }
    else if (kind === "lose") { tone(420, 0, 0.14, 0.18); tone(280, 0.14, 0.26, 0.18); }
    else tone(500, 0, 0.2, 0.16);
  } catch { /* sound is a nicety: never an error */ }
}

/** The sound for a move written in SAN (Nxf3+, O-O, e8=Q#). */
export function soundForSan(san: string): Sound {
  if (san.includes("#") || san.includes("+")) return "check";
  if (san.startsWith("O-O")) return "castle";
  return san.includes("x") ? "capture" : "move";
}
