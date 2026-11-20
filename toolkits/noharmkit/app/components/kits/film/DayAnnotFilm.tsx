"use client";

import { Fragment } from "react";
import type { CSSProperties } from "react";

import { BENCHMARK, STAGES, clamp, easeInOut, easeOut, span } from "./types";
import type { TrailerFilm } from "./types";
import styles from "./DayAnnotFilm.module.css";

/**
 * Daylight: one case runs through every stage end to end (act 1), then the same
 * pipeline sweeps across twelve cases from different specialties (act 2).
 */
/** Film-time length; `warp` adds the three pauses on top (see DayAnnotFilm below). */
const DURATION = 27.1;
/** Final leaderboard leaves and the end card arrives. */
const OUTRO = 23.5;

/** Stage start times (film time) for act 1 (one case) and act 2 (twelve cases); the rail steps on these. */
const ACT1 = [3.3, 4.2, 5.2, 7, 8.2, 9.2];
const ACT1_DONE = 10.4;
const ACT2 = [11.5, 13.4, 14.05, 16.6, 17.4, 18.3];
const ACT2_DONE = 19.6;
const T2 = ACT2[0];

const lerp = (a: number, b: number, p: number): number => a + (b - a) * p;
/** Horizontal lengths scale with canvas width through --spread (px per design unit). */
const sx = (value: number): string => `calc(${value.toFixed(2)} * var(--spread))`;
const place = (x: number, y: number, z: number, extra = ""): string =>
  `translate(-50%, -50%) translate3d(${sx(x)}, ${y.toFixed(2)}px, ${z.toFixed(2)}px) ${extra}`;
const placeTop = (x: number, top: number, z: number, extra = ""): string =>
  `translate(-50%, 0) translate3d(${sx(x)}, ${top.toFixed(2)}px, ${z.toFixed(2)}px) ${extra}`;

type Rgb = [number, number, number];
const mix = (a: Rgb, b: Rgb, p: number, alpha = 1): string =>
  `rgba(${a.map((v, i) => Math.round(lerp(v, b[i], p))).join(", ")}, ${alpha.toFixed(3)})`;
const WHITE: Rgb = [255, 255, 255];
const INK: Rgb = [12, 21, 38];
/** Matches --ink-soft, the composer's typed line, so the premise can hand off without a visible swap. */
const INK_SOFT: Rgb = [47, 60, 87];
const MUTED: Rgb = [77, 90, 116];
const HAIRLINE: Rgb = [190, 201, 222];
const BLUE: Rgb = [47, 111, 224];
const BLUE_INK: Rgb = [29, 79, 184];
const RED: Rgb = [214, 40, 57];
const RED_INK: Rgb = [163, 23, 42];
/** No harm reads as the calm accent blue; harm stays red. */
const SAFE: Rgb = [37, 99, 235];
const SAFE_INK: Rgb = [30, 64, 175];
const rgb = (c: Rgb): string => c.join(", ");
const ACCENT = `rgb(${rgb(BLUE)})`;
const HARM_RED = `rgb(${rgb(RED)})`;

/**
 * Annotation marks: clean strokes inked on as `draw` runs 0 to 1, laid over the element they mark.
 * Lines span the parent's width (underline or strike-through); boxes and rings sit `pad` px outside it.
 */
const inked = (draw: number) => ({ pathLength: 1, strokeDasharray: "1 1", strokeDashoffset: (1 - draw).toFixed(4) });

function Line({ draw, fade = 1, color = ACCENT, strike = false, offset = -4, width = 1.5 }: { draw: number; fade?: number; color?: string; strike?: boolean; offset?: number; width?: number }) {
  if (draw <= 0 || fade <= 0) return null;
  return <svg className={styles.markLine} style={{ ...(strike ? { top: "52%" } : { bottom: offset }), opacity: +fade.toFixed(3) }} aria-hidden="true">
    <line x1="0" y1="1" x2="100%" y2="1" stroke={color} strokeWidth={width} {...inked(draw)} />
  </svg>;
}

function Mark({ draw, fade = 1, color = ACCENT, ring = false, padX = 4, padY = 4, radius = 3, width = 1.25 }: { draw: number; fade?: number; color?: string; ring?: boolean; padX?: number; padY?: number; radius?: number; width?: number }) {
  if (draw <= 0 || fade <= 0) return null;
  return <svg className={styles.mark} style={{ opacity: +fade.toFixed(3), left: -padX, top: -padY, width: `calc(100% + ${2 * padX}px)`, height: `calc(100% + ${2 * padY}px)` }} aria-hidden="true">
    {ring
      ? <ellipse cx="50%" cy="50%" rx="50%" ry="50%" fill="none" stroke={color} strokeWidth={width} {...inked(draw)} />
      : <rect x="0" y="0" width="100%" height="100%" rx={radius} fill="none" stroke={color} strokeWidth={width} {...inked(draw)} />}
  </svg>;
}

const CASE = BENCHMARK.firstCase;
const CASES = BENCHMARK.cases;
/** Act 1 tests three models on one case; act 2 tests all eight across the benchmark. */
const MODELS: string[] = [...BENCHMARK.models];
const SCALE: string[] = [...BENCHMARK.scaleModels];
const harmLabel = (harm: string): string => harm === "severe" ? "Severe harm" : "No harm";

/** Act 1: one case. Each response is graded against the D1 (follow-up) row it matches. */
const responseOf = (model: string) => CASE.responses.find((response) => response.model === model) ?? CASE.responses[0];
const isSevereResponse = (model: string): boolean => responseOf(model).harm === "severe";
const caseCount = (model: string): number => isSevereResponse(model) ? 1 : 0;

/** The generated rubric, flattened into Decision headers and rows in display order. */
type RubricRow = (typeof BENCHMARK.rubricDecisions)[number]["rows"][number] & { timing?: string };
type RubricItem = { kind: "head"; d: number } | { kind: "row"; d: number; row: RubricRow };
const DECISIONS = BENCHMARK.rubricDecisions;
const ITEMS: RubricItem[] = DECISIONS.flatMap((decision, d) => [
  { kind: "head" as const, d },
  ...decision.rows.map((row) => ({ kind: "row" as const, d, row: row as RubricRow })),
]);
const HEAD_H = 54;
const ROW_H = 50;
const PANEL_HEAD_H = 44;
const PANEL_H = 400;
const bestScore = (d: number): number => Math.max(...DECISIONS[d].rows.map((row) => row.score));
const SEVERITY = ["Severe", "Moderate", "Mild"];
const tierOf = (score: number): string => score >= 7 ? "Appropriate" : score >= 4 ? "Uncertain" : "Inappropriate";
/** Harm wording follows the answer-table contract: best row carries the harm of omission (9/8/7), 1-3 rows the harm if recommended. */
function harmOf(d: number, score: number): { text: string; level: "severe" | "moderate" | "mild" | "neutral" } {
  const best = bestScore(d);
  if (score === best) {
    const level = (["severe", "moderate", "mild"] as const)[9 - score] ?? "mild";
    return { text: `${SEVERITY[9 - score] ?? "Mild"} if not addressed`, level };
  }
  if (score >= 7) return { text: "Less preferred", level: "neutral" };
  if (score >= 4) return { text: "Uncertain harm", level: "neutral" };
  return { text: `${SEVERITY[score - 1]} if recommended`, level: (["severe", "moderate", "mild"] as const)[score - 1] };
}
/** Which D1 row each act 1 response matches; its score decides the harm (D1.5 scores 1, severe). */
/**
 * Act 1 autograding, from BENCHMARK.firstCase.judgments: each answer matches rows across several
 * decisions, and an answer can omit a decision entirely (an omission is a harm). D4 is conditional,
 * so leaving it out is not an omission.
 */
const JUDGE = BENCHMARK.firstCase.judgments;
type GradeTarget = { kind: "row" | "omit"; id: string };
const gradeTargets = (model: string): GradeTarget[] => [
  ...(JUDGE[model]?.matches ?? []).map((id) => ({ kind: "row" as const, id })),
  ...(JUDGE[model]?.omitted ?? []).map((id) => ({ kind: "omit" as const, id })),
];
const GRADED_ROWS = new Set(Object.values(JUDGE).flatMap((judgment) => judgment.matches));
/** The grading view shows D1 to D4 with only the rows an answer matched. */
const GRADED_DECISIONS = 4;

/** Act 2: the whole benchmark. */
const isSevere = (model: string, title: string): boolean => (BENCHMARK.severe[model] ?? []).includes(title);
const severeCount = (model: string): number => CASES.filter((item) => isSevere(model, item.title)).length;
const RANK1 = [...MODELS].sort((a, b) => caseCount(a) - caseCount(b));
/** Final leaderboard order: best overall first (fewest severe harms), ties alphabetical; shown only as unlabeled bars. */
const RANK2 = [...SCALE].sort((a, b) => severeCount(a) - severeCount(b) || a.localeCompare(b));
/** The best model's bar fills this much of its track, so no model reads as a perfect score. */
const BAR_MAX = .7;
/** Final board bar per rank (fraction of the track), unevenly spaced so the board reads as measured, not stepped. */
const FINAL_BARS = [.7, .63, .52, .47, .35, .3, .2, .11];

/**
 * Act 1 layout. Dataset: the case card sits left of center with a callout to its right. Rubrics:
 * the card docks left and the abstract rubric appears far back on the right. Responses: the D1
 * card comes into focus on the left and the responses come in on the right.
 */
const CASE_W = 340;
const CASE_X = 0;
const CASE_TOP = -150;
const CASE_BODY_H = 440;
const CASE_DOCK_BODY_H = 462;
const FOOTER_H = 70;
const CASE_DOCK_W = 340;
const CASE_DOCK_X = -310;
const CASE_DOCK_TOP = -248;
/** Generate button: center y, and half its width in px (it has a fixed min width). */
const BUTTON_Y = CASE_DOCK_TOP + CASE_BODY_H + FOOTER_H / 2;
const BUTTON_HALF = 125;
const PANEL_W = 610;
const PANEL_X = 230;
const PANEL_Z = -350;
const PANEL_TOP = -200;
/** The crisp D1 card used for act 1 grading. */
const D1_X = -218;
const D1_TOP = -150;
/** The crisp review card is simpler than the abstract rubric: a one-line question header and one-line rows. */
const D1_HEAD_H = 36;
const D1_ROW_H = 40;
const D1_H = PANEL_HEAD_H + D1_HEAD_H + DECISIONS[0].rows.length * D1_ROW_H;
/** Zoomed-out grading layout: D1 to D4 headers plus the matched rows, as centers relative to the card top. */
const GRADE_TOP = -205;
const GRADE_LAYOUT = (() => {
  const centers: Record<string, number> = {};
  let y = PANEL_HEAD_H;
  DECISIONS.slice(0, GRADED_DECISIONS).forEach((decision) => {
    centers[decision.id] = y + D1_HEAD_H / 2;
    y += D1_HEAD_H;
    decision.rows.filter((row) => GRADED_ROWS.has(row.id)).forEach((row) => {
      centers[row.id] = y + D1_ROW_H / 2;
      y += D1_ROW_H;
    });
  });
  return { centers, height: y };
})();
const RESP_X = 336;
const RESP_W = 340;
const RESP_Y = [-116, 0, 116];

/** Act 2 layout: chips on the left, a 4 x 3 grid on the right. */
const COLS = 4;
const CELL_W = 190;
const PITCH_X = 202;
const PITCH_Y = 148;
const GRID_SHIFT = 100;
/** Act 2 model chips: one column, A to H. */
const CHIP_W = 86;
const CHIP_H = 40;
const chipPos = (i: number): [number, number] => [-430, (i - 3.5) * 48];
const ROW_Y = [-86, 0, 86];
/** Final eight-row leaderboard. */
const ROW8_W = 560;
const ROW8_H = 44;
/** Shifted down a little to leave room for the title above the board. */
const ROW8_Y = Array.from({ length: 8 }, (_, r) => (r - 3.5) * 50 + 22);
/** Model chips float on a nearer layer than the grid, so the camera glide reads as parallax. */
const CHIP_Z = 20;
const cellPos = (index: number): [number, number] =>
  [(index % COLS - 1.5) * PITCH_X + GRID_SHIFT, (Math.floor(index / COLS) - 1) * PITCH_Y];

/** Camera keyframes [time, translateZ, rotateX, rotateY], interpolated with a smooth Hermite spline. */
const KEYS: Array<[number, number, number, number]> = [
  [0, -200, 5, -10],
  [2.4, 30, 2, -4],
  [3.6, 0, 1.5, 2],
  [4.55, -20, 2, 0],
  [5.6, -175, 2.5, 2],
  [7.6, -255, 2, -2],
  [9, -235, 2, 0],
  [10, 0, 1, 0],
  [11.8, -60, 2, -2],
  [13.2, -265, 4, 0],
  [17.0, -265, 2.5, -2.5],
  [19.4, -200, 2, -1.5],
  [20.3, -70, 0, 0],
];

function camera(time: number): [number, number, number] {
  const last = KEYS.length - 1;
  if (time <= KEYS[0][0]) return [KEYS[0][1], KEYS[0][2], KEYS[0][3]];
  if (time >= KEYS[last][0]) return [KEYS[last][1], KEYS[last][2], KEYS[last][3]];
  const i = KEYS.findIndex((_, index) => index < last && time < KEYS[index + 1][0]);
  const [t0] = KEYS[i];
  const [t1] = KEYS[i + 1];
  const h = t1 - t0;
  const p = (time - t0) / h;
  const tangent = (k: number, channel: number): number => {
    if (k === 0 || k === last) return 0;
    return (KEYS[k + 1][channel] - KEYS[k - 1][channel]) / (KEYS[k + 1][0] - KEYS[k - 1][0]) * .8;
  };
  const value = (channel: number): number => {
    const p2 = p * p;
    const p3 = p2 * p;
    return (2 * p3 - 3 * p2 + 1) * KEYS[i][channel] + (p3 - 2 * p2 + p) * h * tangent(i, channel)
      + (-2 * p3 + 3 * p2) * KEYS[i + 1][channel] + (p3 - p2) * h * tangent(i + 1, channel);
  };
  return [value(1), value(2), value(3)];
}

/** Per-stage highlight for the rail: [active, done] for each stage, and the fill of each link. */
function railState(time: number): { active: number[]; done: number[]; links: number[]; act2: boolean } {
  // Act 1 progress clears only once the one-case board has mostly left, then act 2 progress fades in.
  const act2 = time >= T2 + .3;
  const times = act2 ? ACT2 : ACT1;
  const end = act2 ? ACT2_DONE : ACT1_DONE;
  const keep = act2 ? easeInOut(span(time, T2 + .3, .35)) : 1 - easeInOut(span(time, T2 - .05, .35));
  const active: number[] = [];
  const done: number[] = [];
  const links: number[] = [];
  times.forEach((start, i) => {
    const next = i < times.length - 1 ? times[i + 1] : end;
    const on = easeOut(span(time, start, .3));
    const off = easeOut(span(time, next, .3));
    active.push(on * (1 - off) * keep);
    done.push(off * keep);
    if (i > 0) links.push(easeInOut(span(time, start - .3, .45)) * keep);
  });
  return { active, done, links, act2 };
}

/** The anchor: six numbered stages in order, current one lit, finished ones checked. Hidden until the idea is sent. */
function Rail({ time }: { time: number }) {
  // Appears once the idea is sent; leaves as the end card arrives.
  const appear = easeOut(span(time, 2.55, .7)) * (1 - easeInOut(span(time, OUTRO, .6)));
  if (appear <= 0) return null;
  const { active, done, links } = railState(time);
  return <div className={styles.rail} style={{ opacity: appear, transform: `translateX(-50%) translateY(${((1 - appear) * -12).toFixed(2)}px)` }}>
    {STAGES.map((stage, i) => {
      const lit = Math.max(active[i], done[i]);
      return <Fragment key={stage}>
        {i > 0 && <span className={styles.railLink}><span className={styles.railLinkFill} style={{ transform: `scaleX(${links[i - 1].toFixed(3)})` }} /></span>}
        <span className={styles.railStep}>
          <span className={styles.railDot} style={{
            background: mix(WHITE, BLUE, done[i]),
            borderColor: mix(HAIRLINE, BLUE, lit),
          }}>
            <span className={styles.railNum} style={{ opacity: 1 - done[i], color: mix(MUTED, BLUE_INK, active[i]) }}>{i + 1}</span>
            <svg className={styles.railCheck} viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" style={{ opacity: done[i] }}><path d="M2.6 6.3 5 8.6l4.4-5" fill="none" stroke="#ffffff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </span>
          <span className={styles.railLabel} style={{ color: mix(MUTED, INK, Math.max(active[i], done[i] * .6)) }}>{stage}</span>
        </span>
      </Fragment>;
    })}
  </div>;
}

/** Text revealed as `fill` moves from `from` to `to` (both 0..1). */
const fillText = (text: string, fill: number, from: number, to: number): string =>
  text.slice(0, Math.floor(text.length * clamp((fill - from) / (to - from))));

/** Types `text` in place: the untyped rest stays laid out but invisible, so the card never grows. */
function Filled({ text, fill, from, to, caret = false }: { text: string; fill: number; from: number; to: number; caret?: boolean }) {
  const shown = fillText(text, fill, from, to);
  return <>{shown}{caret && <span style={{ position: "relative" }}><span className={styles.caret} style={{ position: "absolute", left: 1, top: ".08em", margin: 0 }} /></span>}<span style={{ visibility: "hidden" }}>{text.slice(shown.length)}</span></>;
}

function typed(text: string, time: number, start: number, length: number): string {
  return text.slice(0, Math.floor(text.length * span(time, start, length)));
}

/**
 * The composer widens on large canvases, and its typed line is sized from that width so the longest
 * specialty ("inpatient hospitalizations?") just fits on one line (the line measures about 30.8 em).
 */
const COMPOSER_W = "min(1100px, 100cqw - 40px)";
const LINE2_SIZE = `calc((${COMPOSER_W} - 60px) * .031)`;

/** The framing question: an ARISEKit task in a clinical context. */
const FRAME_LEAD = "How well does AI handle ";
/**
 * Opening, in real seconds: the whole question types out in ink, its two variable parts turn blue,
 * the task flips through its options and lands, then the context flips and lands on "medical cases
 * in pediatrics". The task lands on its shortest option before any long context appears, so the line
 * never grows past "medical questions in inpatient hospitalizations?", the width the composer is sized for.
 */
const QUESTION_TYPE_AT = 1.75;
const QUESTION_TYPE = 1.5;
const BLUE_AT = 3.55;
const FRAME_TASKS: Array<[number, string]> = [[0, "multi-turn conversations"], [4.35, "clinical agent tasks"], [5.15, "medical cases"]];
const FRAME_CONTEXTS: Array<[number, string]> = [[0, "mental health"], [6.05, "Sweden"], [6.65, "women's health"], [7.25, "oncology"], [7.85, "inpatient hospitalizations"], [8.45, "pediatrics"]];
const LANDED_TASK = FRAME_TASKS[FRAME_TASKS.length - 1][1];
const LANDED_CONTEXT = FRAME_CONTEXTS[FRAME_CONTEXTS.length - 1][1];
const QUESTION = `${FRAME_LEAD}${FRAME_TASKS[0][1]} in ${FRAME_CONTEXTS[0][1]}?`;
/** Both slots are underlined once the context lands. */
const LAND_REAL = 8.6;
/** Each flip rolls over this long, easing in and out, so words glide rather than snap. */
const FLIP = .45;

/** One flipping word: the outgoing word rolls up and out as the next rolls in. */
function Slot({ words, real }: { words: Array<[number, string]>; real: number }) {
  const index = words.reduce((current, [start], i) => real >= start ? i : current, -1);
  if (index < 0) return null;
  const roll = index === 0 ? 1 : easeInOut(span(real, words[index][0], FLIP));
  const color = mix(INK_SOFT, BLUE, easeInOut(span(real, BLUE_AT, .5)));
  return <span className={styles.slot}>
    {index > 0 && roll < 1 && <span className={styles.slotWord} style={{ position: "absolute", left: 0, opacity: 1 - roll, transform: `translateY(${(-roll * 0.9).toFixed(3)}em)`, color }}>{words[index - 1][1]}</span>}
    <span className={styles.slotWord} style={{ opacity: roll, transform: `translateY(${((1 - roll) * 0.9).toFixed(3)}em)`, color }}>{words[index][1]}{index === words.length - 1 && <Line draw={easeInOut(span(real, LAND_REAL, .4))} offset={1} />}</span>
  </span>;
}

/** The question types out as plain text, then becomes live slots once it is complete. */
function FramingLine({ real }: { real: number }) {
  if (real < QUESTION_TYPE_AT + QUESTION_TYPE) return <>{typed(QUESTION, real, QUESTION_TYPE_AT, QUESTION_TYPE)}</>;
  return <>{FRAME_LEAD}<Slot words={FRAME_TASKS} real={real} /> in <Slot words={FRAME_CONTEXTS} real={real} />?</>;
}

/** `time` is warped (frozen during the slot hold); `real` drives the typing and the specialty flips. */
function Composer({ time, real }: { time: number; real: number }) {
  if (time >= 3.6) return null;
  const rise = easeOut(span(time, .15, .9));
  const condense = easeInOut(span(time, 2.9, .36));
  const line1 = typed(BENCHMARK.idea, real, .45, .65);
  const typing = (real >= .45 && real < 1.1) || (real >= QUESTION_TYPE_AT && real < QUESTION_TYPE_AT + QUESTION_TYPE);
  const caretOn = real >= .35 && time < 2.85 && (typing || Math.floor(real * 2.4) % 2 === 0);
  const onLine2 = real >= 1.2;
  const send = Math.sin(Math.PI * span(time, 2.5, .45));
  const caret = <span className={styles.caret} style={{ opacity: caretOn ? 1 : 0 }} />;
  const line2 = <FramingLine real={real} />;
  return <div className={`${styles.card} ${styles.composer}`} style={{
    width: COMPOSER_W,
    opacity: rise * (1 - condense),
    transform: place(0, lerp(70, 0, rise), lerp(-160, 0, rise) - 120 * condense, `rotateX(${lerp(22, 0, rise)}deg) scale(${1 - .15 * condense})`),
    filter: `blur(${(condense * 6).toFixed(2)}px)`,
  }}>
    <p className={styles.composerLine1} style={{ fontSize: `calc(${LINE2_SIZE} * 1.12)` }}>{line1}{!onLine2 && caret}</p>
    <p className={styles.composerLine2} style={{ opacity: time >= 2.85 ? 0 : 1, fontSize: LINE2_SIZE }}>{line2}{onLine2 && caret}</p>
    <div className={styles.composerBar}>
      <span className={styles.send} style={{ transform: `scale(${(1 - .08 * send).toFixed(3)})`, background: mix(BLUE, BLUE_INK, send) }}>
        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M8 12.5V4M4.2 7.6 8 3.8l3.8 3.8" fill="none" stroke="#ffffff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </span>
    </div>
  </div>;
}

/** The framing line lifts out of the composer and holds as the premise above the first case. */
function Premise({ time, gen }: { time: number; gen: number }) {
  if (time < 2.85 || gen >= .07) return null;
  // Glides from the moment of the swap, so it never sits still while the camera drifts.
  const lift = easeInOut(span(time, 2.85, .42));
  const fade = easeInOut(span(gen, 0, .06));
  const rest = (1 - lift).toFixed(4);
  // Stays just in front of the composer card until the card has receded, or the card hides it.
  const depth = lerp(1, -20, easeInOut(span(time, 2.95, .3)));
  // Starts exactly on the composer's typed line (left-aligned at its text edge), then glides up to center.
  // The line's centre sits .75 font-sizes minus 22px below the composer's centre (measured).
  const startX = `calc((${COMPOSER_W} / -2 + 30.8px) * ${rest})`;
  const startY = `calc((${LINE2_SIZE} * .75 - 22px) * ${rest} + ${(-185 * lift - 14 * fade).toFixed(2)}px)`;
  return <p className={styles.premise} style={{
    opacity: 1 - clamp(fade * 2.2),
    fontSize: `calc(${LINE2_SIZE} * ${(1 - lift).toFixed(4)} + 23px * ${lift.toFixed(4)})`,
    color: mix(INK_SOFT, INK, lift),
    transform: `translate(${(-50 * lift).toFixed(3)}%, -50%) translate3d(${startX}, ${startY}, ${depth.toFixed(2)}px)`,
  }}>{FRAME_LEAD}<span className={styles.marked} style={{ color: `rgba(${rgb(BLUE)}, 1)` }}>{LANDED_TASK}<Line draw={1} offset={-1} /></span> in <span className={styles.marked} style={{ color: `rgba(${rgb(BLUE)}, 1)` }}>{LANDED_CONTEXT}<Line draw={1} offset={-1} /></span>?</p>;
}

/** Grading progress of one response's line, shared by the lines and the D1 row highlight. */
/** The card zooms out from D1 to D1-D4 as autograding starts; then each answer's lines fan out, staggered. */
const gradeZoom = (time: number): number => easeInOut(span(time, ACT1[3] - .35, .6));
const lineDraw = (time: number, m: number, k: number): number => easeInOut(span(time, ACT1[3] + .3 + m * .12 + k * .06, .3));
const linesFade = (time: number): number => 1 - easeInOut(span(time, ACT1[5] - .05, .35));
const score1 = (time: number, m: number): number => easeOut(span(time, ACT1[4] + m * .12, .5));

/**
 * Generation pause phases, as fractions of `gen`: the button breathes, is pressed, shows a
 * loading state for about a second, then the abstract rubric streams in and scrolls.
 */
const GEN_PRESS = .17;
const GEN_LOADING = [.21, .17] as const;
const GEN_LAYOUT = [.3, .12] as const;
const GEN_STREAM = [.38, .38] as const;
const GEN_BACK = [.88, .11] as const;
const genLayout = (gen: number): number => easeInOut(span(gen, GEN_LAYOUT[0], GEN_LAYOUT[1]));
/** The D1 card comes into focus out of the abstract rubric as responses arrive. */
/**
 * Responses beat (film time): the review card steps back out of the way, the case is fed to the
 * three models during the FEED stretch, then the case card leaves and D1 returns for autograding.
 */
const D1_AWAY = 4.65;
const CASE_LEAVE = 6.02;
const D1_BACK = 6.08;

function Sparkle() {
  return <svg viewBox="0 0 16 16" width="18" height="18" aria-hidden="true"><path d="M8 1.5c.5 3.3 1.9 5 5.5 6.5-3.6 1.5-5 3.2-5.5 6.5-.5-3.3-1.9-5-5.5-6.5C6.1 6.5 7.5 4.8 8 1.5Z" fill="currentColor" /></svg>;
}

function Spinner({ real }: { real: number }) {
  return <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" style={{ transform: `rotate(${((real * 420) % 360).toFixed(1)}deg)` }}>
    <circle cx="10" cy="10" r="7.5" fill="none" stroke="rgba(255, 255, 255, .3)" strokeWidth="2.4" />
    <path d="M10 2.5a7.5 7.5 0 0 1 7.5 7.5" fill="none" stroke="#ffffff" strokeWidth="2.4" strokeLinecap="round" />
  </svg>;
}

function CaseCard({ time, real, fill, gen }: { time: number; real: number; fill: number; gen: number }) {
  if (time < ACT1[0] - .1 || time >= CASE_LEAVE + .7) return null;
  const appear = easeOut(span(time, ACT1[0], .8));
  const footerIn = easeOut(span(gen, .02, .05));
  const dock = genLayout(gen);
  // Rises into the premise's place as the premise fades and the Generate button appears.
  const rise = easeInOut(span(gen, 0, .055));
  const leave = easeInOut(span(time, CASE_LEAVE, .6));
  const breathe = .5 + .5 * Math.sin(real * 3.4);
  const press = Math.sin(Math.PI * span(gen, GEN_PRESS, .04));
  const loading = gen >= GEN_LOADING[0];
  const loadingIn = easeOut(span(gen, GEN_LOADING[0], .03));
  const idle = 1 - span(gen, GEN_PRESS, .03);
  /** The loading button stays up while the rubric streams in beside it, then folds away. */
  const footer = footerIn * (1 - easeInOut(span(gen, GEN_STREAM[0] + GEN_STREAM[1] * .7, .06)));
  return <div className={`${styles.card} ${styles.caseCard}`} style={{
    width: sx(lerp(CASE_W, CASE_DOCK_W, dock)),
    opacity: clamp(appear * 1.3) * (1 - leave),
    transform: placeTop(lerp(CASE_X, CASE_DOCK_X, dock) - 60 * leave, lerp(CASE_TOP, CASE_DOCK_TOP, rise), lerp(-90, 0, appear) - 220 * leave, `rotateX(${lerp(-14, 0, appear).toFixed(2)}deg) scale(${lerp(.92, 1, appear).toFixed(3)})`),
  }}>
    <div className={styles.caseBody} style={{ maxHeight: `${lerp(CASE_BODY_H, CASE_DOCK_BODY_H, dock).toFixed(2)}px` }}>
      <p className={styles.caseTitle}><Filled text={CASE.title} fill={fill} from={0} to={.1} /></p>
      <div className={styles.caseDivider} />
      <span className={styles.label}>Case</span>
      <p className={styles.caseInput}><Filled text={CASE.input} fill={fill} from={.12} to={.46} caret={fill > .12 && fill < .48} /></p>
      <span className={styles.label}>Solution</span>
      <p className={styles.caseRef}><Filled text={CASE.reference} fill={fill} from={.5} to={.72} caret={fill >= .5 && fill < .72} /></p>
      <span className={styles.label}>Errors</span>
      <ul className={styles.errorList}>
        {CASE.errors.map((error, k) => {
          const from = .76 + k * .052;
          const shown = clamp((fill - from) / .05);
          return <li key={error.text} className={styles.errorItem} style={{ opacity: easeOut(shown), transform: `translateY(${((1 - easeOut(shown)) * 6).toFixed(2)}px)` }}>
            <span className={styles.errorText}>{fillText(error.text, fill, from, from + .04)}</span>
            <span className={`${styles.harmChip} ${HARM_CLASS[error.harm]}`}>{error.harm[0].toUpperCase() + error.harm.slice(1)}</span>
          </li>;
        })}
      </ul>
    </div>
    <div className={styles.caseFooter} style={{ height: `${(FOOTER_H * footer).toFixed(2)}px`, opacity: footer }}>
      <span className={styles.generate} style={{
        transform: `scale(${(1 + .02 * breathe * idle - .05 * press).toFixed(3)})`,
        background: mix(BLUE, BLUE_INK, press * .6 + (loading ? .2 : 0)),
      }}>

        <span className={styles.generateFace} style={{ opacity: 1 - loadingIn }}><Sparkle /><span>Generate Rubric</span></span>
        {loading && <span className={styles.generateFace} style={{ opacity: loadingIn }}><Spinner real={real} /><span>Generating rubric</span></span>}
      </span>
    </div>
  </div>;
}

/** Tier colors for the abstract score squares and tier pills. */
const TIER_TONE: Record<string, string> = { Appropriate: "#2563eb", Uncertain: "#a8a29e", Inappropriate: "#dc2626" };
const HARM_TONE: Record<string, string> = { severe: "rgba(214, 40, 57, .28)", moderate: "rgba(234, 88, 12, .26)", mild: "rgba(217, 119, 6, .22)", neutral: "rgba(22, 44, 92, .1)" };
/** Deterministic pseudo-text widths (percent) from a label. */
const barWidth = (label: string, min: number, range: number): number =>
  min + [...label].reduce((sum, ch, i) => sum + ch.charCodeAt(0) * (i + 3), 0) % range;

const itemAppear = (gen: number, k: number): number => easeOut(span(gen, GEN_STREAM[0] + k * GEN_STREAM[1] / ITEMS.length, .04));
const itemHeight = (item: RubricItem): number => item.kind === "head" ? HEAD_H : ROW_H;

/**
 * The generated rubric, far back and softly blurred: abstract shapes that read as a dense
 * NOHARM answer table (score squares, text bars, harm pills) streaming in and scrolling.
 */
function RubricPanel({ gen, review }: { gen: number; review: number }) {
  if (gen < GEN_LAYOUT[0] || review >= REVIEW_IN[1]) return null;
  const appear = genLayout(gen);
  const focus = easeInOut(span(review, REVIEW_IN[0], REVIEW_IN[1]));
  const shown = ITEMS.map((_, k) => itemAppear(gen, k));
  const contentH = ITEMS.reduce((sum, item, k) => sum + itemHeight(item) * shown[k], 0);
  const streamEnd = GEN_STREAM[0] + GEN_STREAM[1] + .04;
  const skeleton = easeOut(span(gen, GEN_STREAM[0] - .03, .03)) * (1 - easeInOut(span(gen, streamEnd - .03, .03)));
  const follow = Math.max(0, contentH + ROW_H * skeleton - (PANEL_H - PANEL_HEAD_H));
  const scroll = follow * (1 - easeInOut(span(gen, GEN_BACK[0], GEN_BACK[1])));

  return <div className={`${styles.card} ${styles.rubricPanel}`} style={{
    width: sx(PANEL_W),
    height: PANEL_H,
    opacity: appear * (1 - focus),
    filter: `blur(${lerp(5, 2.2, appear).toFixed(2)}px)`,
    transform: placeTop(PANEL_X + 120 * (1 - appear), PANEL_TOP, lerp(-750, PANEL_Z, appear) - 200 * focus, `rotateY(${lerp(-18, -8, appear).toFixed(2)}deg)`),
  }}>
    <div className={styles.panelHead}>
      <span className={styles.absBar} style={{ width: 60, height: 12, background: "rgba(12, 21, 38, .55)" }} />
      <span className={styles.absBar} style={{ width: 120, height: 9 }} />
      <span className={styles.absPill} style={{ marginLeft: "auto", width: 130, background: "rgba(47, 111, 224, .22)" }} />
    </div>
    <div className={styles.panelView} style={{ height: PANEL_H - PANEL_HEAD_H }}>
      <div className={styles.panelContent} style={{ transform: `translateY(${(-scroll).toFixed(2)}px)` }}>
        {ITEMS.map((item, k) => {
          const amount = shown[k];
          if (amount <= 0) return null;
          const style: CSSProperties = { height: `${(itemHeight(item) * amount).toFixed(2)}px`, opacity: clamp(amount * 1.4 - .2) };
          if (item.kind === "head") {
            const decision = DECISIONS[item.d];
            return <div key={decision.id} className={styles.decision} style={style}>
              <div className={styles.decisionHead}>
                <span className={styles.absBar} style={{ width: 22, height: 11, background: "rgba(77, 90, 116, .45)" }} />
                <span className={styles.absBar} style={{ width: `${barWidth(decision.question, 38, 30)}%`, height: 11, background: "rgba(12, 21, 38, .5)" }} />
                <span className={styles.absBar} style={{ marginLeft: "auto", width: 54, height: 9 }} />
              </div>
              <div className={`${styles.absGrid} ${styles.absColHead}`}>
                <span /><span className={styles.absBar} style={{ width: 70, height: 7 }} /><span className={styles.absBar} style={{ width: 64, height: 7 }} />
              </div>
            </div>;
          }
          const { row, d } = item;
          const tier = tierOf(row.score);
          const harm = harmOf(d, row.score);
          const twoLines = row.text.length > 44;
          return <div key={row.id} className={`${styles.absGrid} ${styles.absRow}`} style={style}>
            <span className={styles.absBar} style={{ width: 26, height: 9 }} />
            <span className={styles.absScore} style={{ background: TIER_TONE[tier] }} />
            <span className={styles.absText}>
              <span className={styles.absBar} style={{ width: `${barWidth(row.id + row.text, twoLines ? 70 : 40, twoLines ? 28 : 40)}%`, height: 10, background: "rgba(12, 21, 38, .32)" }} />
              {twoLines && <span className={styles.absBar} style={{ width: `${barWidth(row.text, 25, 40)}%`, height: 10, background: "rgba(12, 21, 38, .32)" }} />}
            </span>
            <span className={styles.absMeta}>
              <span className={styles.absLine}>
                <span className={styles.absPill} style={{ width: 62, background: `${TIER_TONE[tier]}55` }} />
                {row.timing === "urgent" && <span className={styles.absPill} style={{ width: 36, background: "rgba(30, 64, 175, .2)" }} />}
              </span>
              <span className={styles.absPill} style={{ width: harm.level === "neutral" ? 70 : 96, background: HARM_TONE[harm.level] }} />
            </span>
          </div>;
        })}
        {skeleton > 0 && <div className={`${styles.absGrid} ${styles.skeleton}`} style={{ height: `${(ROW_H * skeleton).toFixed(2)}px`, opacity: skeleton }}>
          <span className={styles.skelBar} style={{ width: 26 }} />
          <span className={styles.skelBar} style={{ width: 18, height: 18 }} />
          <span className={styles.skelBar} style={{ width: "80%" }} />
          <span className={styles.skelBar} style={{ width: 90 }} />

        </div>}
      </div>
    </div>
  </div>;
}

/** Score badge colors from the rubric editor: red (1) to blue (9) through neutral. */
const SCORE_STYLE: Record<number, [string, string]> = {
  1: ["#b91c1c", "#ffffff"], 2: ["#dc2626", "#ffffff"], 3: ["#f87171", "#450a0a"],
  4: ["#fecaca", "#450a0a"], 5: ["#d6d3d1", "#1c1917"], 6: ["#bfdbfe", "#172554"],
  7: ["#60a5fa", "#172554"], 8: ["#2563eb", "#ffffff"], 9: ["#1e40af", "#ffffff"],
};
const HARM_CLASS: Record<string, string> = { severe: styles.harmSevere, moderate: styles.harmModerate, mild: styles.harmMild, neutral: styles.harmNeutral, safe: styles.harmSafe };

/**
 * Physician review beat, as fractions of `review`: the D1 card comes into focus, a pointer opens
 * D1.3's score bar and changes the generated 5 to the reviewed 4, then presses Mark reviewed.
 */
const REVIEW_IN = [0, .1] as const;
/** The card glides down through several decisions and straight back up to triage before the edit, with no stop in between. */
const REVIEW_SCROLL: Array<[number, number]> = [[.08, 0], [.29, 3], [.45, 0]];
const REVIEW_SCORE_CLICK = .54;
const REVIEW_PICK = .68;
const REVIEW_MARK = .86;
/** The edited row: generated with this score, stored in BENCHMARK as the reviewed score. */
const EDITED_ROW = "D1.3";
const GENERATED_SCORE = 5;
/** The physician's edit: the generated Uncertain becomes Moderate harm (score 2), as stored in BENCHMARK. */
const REVIEWED_SCORE = 2;
const REVIEW_X = 175;
const REVIEW_TOP = -200;
/** Pointer path in card coordinates: [fraction, left %, left px, top px]. */
const POINTER: Array<[number, number, number, number]> = [
  [.46, 100, 60, 300],
  [.52, 100, -48, 177],
  [.56, 100, -48, 177],
  [.64, 100, -110, 205],
  [.7, 100, -110, 205],
  [.83, 100, -70, 22],
  [.92, 100, -70, 22],
  [1, 100, 70, 120],
];

function pointerAt(review: number): [number, number, number] {
  const last = POINTER.length - 1;
  if (review <= POINTER[0][0]) return [POINTER[0][1], POINTER[0][2], POINTER[0][3]];
  if (review >= POINTER[last][0]) return [POINTER[last][1], POINTER[last][2], POINTER[last][3]];
  const i = POINTER.findIndex((_, k) => k < last && review < POINTER[k + 1][0]);
  const p = easeInOut((review - POINTER[i][0]) / (POINTER[i + 1][0] - POINTER[i][0]));
  return [lerp(POINTER[i][1], POINTER[i + 1][1], p), lerp(POINTER[i][2], POINTER[i + 1][2], p), lerp(POINTER[i][3], POINTER[i + 1][3], p)];
}

function Pointer({ review }: { review: number }) {
  const [pct, px, top] = pointerAt(review);
  const show = easeOut(span(review, .46, .05)) * (1 - easeInOut(span(review, .93, .06)));
  const clicks = [REVIEW_SCORE_CLICK, REVIEW_PICK, REVIEW_MARK].map((at) => Math.sin(Math.PI * span(review, at, .06)));
  const press = Math.max(...clicks);
  if (show <= 0) return null;
  return <span className={styles.pointer} style={{ left: `calc(${pct.toFixed(2)}% + ${px.toFixed(1)}px)`, top: `${top.toFixed(1)}px`, opacity: show }}>
    <span className={styles.pointerRing} style={{ opacity: press * .9, transform: `translate(-50%, -50%) scale(${(.4 + 1.1 * press).toFixed(3)})` }} />
    <svg viewBox="0 0 20 22" width="20" height="22" aria-hidden="true" style={{ transform: `scale(${(1 - .12 * press).toFixed(3)})`, transformOrigin: "2px 2px" }}>
      <path d="M2.5 2.5v15.2l4.1-3.9 2.7 6 2.6-1.1-2.7-5.9h5.6Z" fill="#0c1526" stroke="#ffffff" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  </span>;
}

/** The editor's 1-9 appropriateness bar, opened under the edited row's score badge. */
/** Harm levels the reviewer can assign, with the score each one stores (1-3 harmful, 5 uncertain). */
const HARM_OPTIONS: Array<{ label: string; score: number; level: "neutral" | "mild" | "moderate" | "severe" }> = [
  { label: "Uncertain", score: 5, level: "neutral" },
  { label: "Mild", score: 3, level: "mild" },
  { label: "Moderate", score: 2, level: "moderate" },
  { label: "Severe", score: 1, level: "severe" },
];

/** The editor's harm picker, opened under the edited row's harm label. */
function HarmPicker({ review }: { review: number }) {
  const open = easeOut(span(review, REVIEW_SCORE_CLICK + .02, .05)) * (1 - easeInOut(span(review, REVIEW_PICK + .03, .05)));
  if (open <= 0) return null;
  const hover = review >= .63 ? REVIEWED_SCORE : GENERATED_SCORE;
  const chosen = review >= REVIEW_PICK ? REVIEWED_SCORE : GENERATED_SCORE;
  return <span className={styles.harmPicker} style={{ opacity: open, transform: `translateY(${((1 - open) * -6).toFixed(2)}px)` }}>
    {HARM_OPTIONS.map((option) => {
      const on = option.score === chosen;
      const lit = on || option.score === hover;
      return <span key={option.label} className={`${styles.harmChip} ${lit ? HARM_CLASS[option.level] : styles.harmOff}`}>
        {option.label}
      </span>;
    })}
  </span>;
}

/** Top offset of decision d inside the crisp card's scrolling list. */
const decisionTop = (d: number): number => DECISIONS.slice(0, d).reduce((sum, item) => sum + D1_HEAD_H + item.rows.length * D1_ROW_H, 0);
function reviewScroll(review: number): number {
  const last = REVIEW_SCROLL.length - 1;
  if (review <= REVIEW_SCROLL[0][0] || review >= REVIEW_SCROLL[last][0]) return 0;
  const i = REVIEW_SCROLL.findIndex((_, k) => k < last && review < REVIEW_SCROLL[k + 1][0]);
  const [t0, d0] = REVIEW_SCROLL[i];
  const [t1, d1] = REVIEW_SCROLL[i + 1];
  return lerp(decisionTop(d0), decisionTop(d1), easeInOut((review - t0) / (t1 - t0)));
}

/** One plain label per row on the crisp card: appropriate, uncertain, or the harm if recommended. */
function d1Pill(score: number): { text: string; level: "neutral" | "safe" | "severe" | "moderate" | "mild" } {
  if (score >= 7) return { text: "Appropriate", level: "safe" };
  if (score >= 4) return { text: "Uncertain", level: "neutral" };
  return { text: ["Severe harm", "Moderate harm", "Mild harm"][score - 1], level: (["severe", "moderate", "mild"] as const)[score - 1] };
}

/**
 * The rubric review panel: D1 in focus, sharp and legible. During the review pause a physician
 * edits one score and marks it reviewed; later it moves left and the act 1 responses grade against it.
 */
function D1Card({ time, real, review }: { time: number; real: number; review: number }) {
  const reviewIn = easeInOut(span(review, REVIEW_IN[0], REVIEW_IN[1]));
  if (reviewIn <= 0 || time >= ACT1[5] + .8) return null;
  const away = easeInOut(span(time, D1_AWAY, .5));
  const back = easeInOut(span(time, D1_BACK, .8));
  const returning = time >= D1_BACK;
  const shown = returning ? back : 1 - away;
  const leave = easeInOut(span(time, ACT1[5] - .1, .7));
  const zoom = gradeZoom(time);
  const listH = lerp(D1_HEAD_H + DECISIONS[0].rows.length * D1_ROW_H, GRADE_LAYOUT.height - PANEL_HEAD_H, zoom);
  const reviewed = span(review, REVIEW_MARK + .02, .05);
  const markButton = 1 - span(review, REVIEW_MARK + .03, .06);
  const markPress = Math.sin(Math.PI * span(review, REVIEW_MARK, .06));
  return <div className={`${styles.card} ${styles.rubricPanel}`} style={{
    width: sx(PANEL_W),
    height: PANEL_HEAD_H + listH,
    overflow: "visible",
    opacity: clamp(reviewIn * 1.6) * shown * (1 - leave),
    filter: reviewIn < 1 || shown < 1 ? `blur(${(4 * (1 - reviewIn * shown)).toFixed(2)}px)` : undefined,
    transform: returning
      ? placeTop(D1_X, lerp(D1_TOP, GRADE_TOP, zoom), -300 * (1 - back) - 220 * leave)
      : placeTop(lerp(PANEL_X, REVIEW_X, reviewIn), lerp(PANEL_TOP + 60, REVIEW_TOP, reviewIn), lerp(PANEL_Z, 0, reviewIn) - 300 * away, `rotateY(${lerp(-8, 0, reviewIn).toFixed(2)}deg)`),
  }}>
    <div className={styles.panelHead}>
      <span className={styles.panelTitle}>Rubric review</span>
      <span className={styles.reviewStatus} style={{ color: mix(MUTED, BLUE_INK, reviewed) }}>
        {reviewed > .5
          ? <><svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M2.6 6.3 5 8.6l4.4-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>Physician reviewed</>
          : "Generated, not yet reviewed"}
      </span>
      <span className={styles.markReviewed} style={{
        opacity: markButton,
        transform: `scale(${(1 - .06 * markPress).toFixed(3)})`,
        background: mix(WHITE, BLUE, .08 + .4 * markPress),
      }}>Mark reviewed</span>
    </div>
    <div style={{ height: listH, overflow: "hidden" }}>
    <div style={{ transform: `translateY(${(-reviewScroll(review)).toFixed(2)}px)` }}>
    {DECISIONS.map((decision, d) => {
    const headShown = d < GRADED_DECISIONS ? 1 : 1 - zoom;
    const omitters = MODELS.filter((model) => (JUDGE[model]?.omitted ?? []).includes(decision.id));
    const omitted = Math.max(0, ...omitters.map((model) => lineDraw(time, MODELS.indexOf(model), gradeTargets(model).findIndex((target) => target.id === decision.id)))) * linesFade(time);
    return <Fragment key={decision.id}>
    <div className={styles.decisionHead} style={{
      height: D1_HEAD_H * headShown,
      overflow: "hidden",
      position: "relative",
    }}>
      {omitted > 0 && <Mark draw={omitted} fade={1 - easeInOut(span(real, OMIT_FADE_REAL, .4))} color={HARM_RED} padX={-3} padY={-3} width={1.5} />}
      <span className={styles.decisionQ}>{decision.question}</span>
      {omitters.map((model) => <span key={model} className={styles.omitTag} style={{ opacity: omitted, transform: `scale(${lerp(.8, 1, omitted).toFixed(3)})` }}>{model}: omitted</span>)}
    </div>
    {decision.rows.map((row) => {
      const rowShown = d < GRADED_DECISIONS && GRADED_ROWS.has(row.id) ? 1 : 1 - zoom;
      const edited = row.id === EDITED_ROW;
      const score = edited && review < REVIEW_PICK ? GENERATED_SCORE : row.score;
      const pill = d1Pill(score);
      const [fillColor, ink] = SCORE_STYLE[score];
      const editing = edited ? Math.sin(Math.PI * span(review, REVIEW_SCORE_CLICK - .04, .4)) : 0;
      const pop = edited ? Math.sin(Math.PI * span(review, REVIEW_PICK, .08)) : 0;
      return <div key={row.id} className={`${styles.d1Grid} ${styles.rubricLine}`} style={{
        height: D1_ROW_H * rowShown,
        opacity: rowShown < 1 ? clamp(rowShown * 1.5) : undefined,
        overflow: edited && zoom <= 0 ? "visible" : "hidden",
        position: "relative",
        zIndex: edited ? 2 : undefined,
        background: editing > 0 ? `rgba(${rgb(BLUE)}, ${(.05 * editing).toFixed(3)})` : undefined,
      }}>
        <span className={styles.scoreBadge} style={{ background: fillColor, color: ink, transform: `scale(${(1 + .25 * pop).toFixed(3)})` }}>{score}</span>
        <span className={styles.d1Text}>{row.text}</span>
        <span className={`${styles.harmChip} ${HARM_CLASS[pill.level]}`}>{pill.text}</span>
        {edited && <HarmPicker review={review} />}
      </div>;
    })}
    </Fragment>;
    })}
    </div>
    </div>
    <Pointer review={review} />
  </div>;
}

/** A heading over the one-case leaderboard (a title, not a callout); it leaves as act 2 begins. */
/** A heading over the act 2 case wall while the new cases are written; it leaves as the model chips arrive. */
function ScaleTitle({ time }: { time: number }) {
  const show = easeOut(span(time, T2 + .3, .6)) * (1 - easeInOut(span(time, CHIPS_IN - .15, .5)));
  if (show <= 0) return null;
  return <p className={styles.boardTitle} style={{ opacity: show, transform: place(GRID_SHIFT, cellPos(0)[1] - PITCH_Y / 2 - 30 + 10 * (1 - show), 0) }}>Scale from one case to many</p>;
}

/** A heading over the final eight-model leaderboard; it leaves as the end card arrives. */
function FinalTitle({ time }: { time: number }) {
  const show = easeOut(span(time, 20.6, .6)) * (1 - easeInOut(span(time, OUTRO - .4, .5)));
  if (show <= 0) return null;
  return <p className={styles.boardTitle} style={{ opacity: show, transform: place(0, ROW8_Y[0] - ROW8_H / 2 - 40 + 10 * (1 - show), 0) }}>Your benchmark tested on all the latest models</p>;
}

function BoardTitle({ time }: { time: number }) {
  const show = easeOut(span(time, ACT1[5] + .25, .6)) * (1 - easeInOut(span(time, T2 - .3, .5)));
  if (show <= 0) return null;
  return <p className={styles.boardTitle} style={{ opacity: show, transform: place(0, ROW_Y[0] - 84 + 10 * (1 - show), 0) }}>Compare model performance</p>;
}

/**
 * Act 1 autograding, in a 1000 x 620 space: from each response a thread to every rubric row it
 * matches (staggered, so B and C fan out across decisions), and a dashed red thread ending in a
 * hollow circle at each decision the answer omitted.
 */
function GradeLines({ time }: { time: number }) {
  if (time < ACT1[3] || time >= ACT1[5] + .3) return null;
  const end = (x: number, y: number, color: string, opacity: number) =>
    <circle cx={x} cy={y} r="3" fill="#ffffff" stroke={color} strokeWidth="1.25" opacity={opacity.toFixed(3)} />;
  const fade = linesFade(time);
  const x0 = 500 + RESP_X - RESP_W / 2;
  const x1 = 500 + D1_X + PANEL_W / 2 - 12;
  return <svg className={styles.streams} viewBox="0 0 1000 620" preserveAspectRatio="none" style={{ width: sx(1000), transform: place(0, 0, 2), opacity: fade }}>
    {MODELS.flatMap((model, m) => gradeTargets(model).map((target, k) => {
      const y0 = 310 + RESP_Y[m];
      const y1 = 310 + GRADE_TOP + GRADE_LAYOUT.centers[target.id];
      const d = `M${x0} ${y0} C${x0 - 60} ${y0} ${x1 + 60} ${y1} ${x1} ${y1}`;
      const draw = lineDraw(time, m, k);
      if (draw <= 0) return null;
      if (target.kind === "omit") {
        return <g key={`${model}-${target.id}`}>
          <path d={d} fill="none" stroke={HARM_RED} strokeWidth="1.25" strokeDasharray="5 4" opacity={draw.toFixed(3)} />
          {end(x0, y0, HARM_RED, clamp(draw * 3))}
          {end(x1, y1, HARM_RED, clamp(draw * 1.5 - .5))}
        </g>;
      }
      const scored = score1(time, m);
      const tone = isSevereResponse(model) ? RED : SAFE;
      const color = mix(BLUE, tone, scored);
      return <g key={`${model}-${target.id}`}>
        <path d={d} fill="none" stroke={color} strokeWidth="1.25" {...inked(draw)} />
        {end(x0, y0, color, clamp(draw * 3))}
        {end(x1, y1, color, clamp(draw * 1.2 - .2))}
      </g>;
    }))}
  </svg>;
}

/**
 * Feeding the case to the models, as fractions of `feed`: response cards slide in, a packet
 * travels from the case to each model, each model thinks briefly, then writes its own answer at
 * its own pace (fixed per-model rates, so they finish at different times).
 */
const FEED_ENTER = 0;
const packetStart = (m: number): number => .06 + m * .06;
const PACKET_LEN = .14;
const THINK = [.09, .12, .07];
const ANSWER_RATE = [44, 52, 40];
const answerStart = (m: number): number => packetStart(m) + PACKET_LEN + THINK[m];
const answerCount = (feed: number, m: number): number =>
  Math.min(responseOf(MODELS[m]).text.length, Math.floor(Math.max(0, feed - answerStart(m)) * FEED * ANSWER_RATE[m]));
const answerTyping = (feed: number, m: number): boolean => {
  const count = answerCount(feed, m);
  return feed > answerStart(m) && count < responseOf(MODELS[m]).text.length;
};
const thinkingAmount = (feed: number, m: number): number => {
  const arrive = packetStart(m) + PACKET_LEN;
  return easeOut(span(feed, arrive - .01, .03)) * (1 - easeInOut(span(feed, answerStart(m) - .02, .03)));
};

/** Three dots pulsing on real time while a model works on the case. */
function Thinking({ real, amount }: { real: number; amount: number }) {
  if (amount <= 0) return null;
  return <span className={styles.thinking} style={{ opacity: amount }} aria-hidden="true">
    {[0, 1, 2].map((i) => <span key={i} className={styles.thinkingDot} style={{ opacity: (.25 + .75 * Math.max(0, Math.sin(real * 7 - i * .9))).toFixed(3) }} />)}
  </span>;
}

/** The case question travels from the docked case card to each model, staggered, in a 1000 x 620 space. */
function CaseFeed({ feed }: { feed: number }) {
  if (feed <= 0 || feed >= 1) return null;
  // Holds while the answers type, then lifts just before the case card leaves for grading.
  const fade = 1 - easeInOut(span(feed, .93, .07));
  const x0 = 500 + CASE_DOCK_X + CASE_DOCK_W / 2;
  const y0 = 310 + CASE_DOCK_TOP + CASE_DOCK_BODY_H / 2;
  const x1 = 500 + RESP_X - RESP_W / 2;
  const start = easeOut(span(feed, .03, .1));
  return <svg className={styles.streams} viewBox="0 0 1000 620" preserveAspectRatio="none" style={{ width: sx(1000), transform: place(0, 0, 4), opacity: fade }}>
    <circle cx={x0} cy={y0} r="3" fill="#ffffff" stroke={ACCENT} strokeWidth="1.25" opacity={start.toFixed(3)} />
    {MODELS.map((model, m) => {
      const y1 = 310 + RESP_Y[m];
      const d = `M${x0} ${y0} C${x0 + 90} ${y0} ${x1 - 90} ${y1} ${x1} ${y1}`;
      const draw = easeInOut(span(feed, packetStart(m) - .02, PACKET_LEN));
      const p = easeInOut(span(feed, packetStart(m), PACKET_LEN));
      const traveling = p > 0 && p < 1;
      return <g key={model}>
        <path d={d} fill="none" stroke={ACCENT} strokeOpacity=".35" strokeWidth="1.25" {...inked(draw)} />
        {traveling && <path d={d} fill="none" stroke={ACCENT} strokeWidth="2" strokeLinecap="round" pathLength={1} strokeDasharray=".08 .92" strokeDashoffset={(-(p - .08)).toFixed(4)} />}
        <circle cx={x1} cy={y1} r="3" fill="#ffffff" stroke={ACCENT} strokeWidth="1.25" opacity={clamp(p * 3 - 2).toFixed(3)} />

      </g>;
    })}
  </svg>;
}

/**
 * One model across the whole film. Act 1 models (A to C): response card, one-case leaderboard row,
 * act 2 chip, final row. Act 2 models (D to H) arrive as chips and end as final rows.
 */
function ModelCard({ time, real, feed, model }: { time: number; real: number; feed: number; model: string }) {
  const s = SCALE.indexOf(model);
  const m = MODELS.indexOf(model);
  const act1 = m >= 0;
  /** Act 2 shows the dataset scaling first; every model, A to H, arrives as a chip only after the cases are written. */
  const chipStart = CHIPS_IN + s * .06;
  if ((act1 ? feed <= 0 : time < chipStart) || time >= OUTRO + .8) return null;
  const inChips = time >= chipStart;
  const chipIn = easeOut(span(time, chipStart, .45));
  const rowOut = act1 ? easeInOut(span(time, T2 - .2 + m * .06, .6)) : 0;
  const [cx, cy] = chipPos(s);
  const rank1 = RANK1.indexOf(model);
  const rank2 = RANK2.indexOf(model);
  const enter = !inChips ? easeOut(span(feed, FEED_ENTER + m * .05, .16)) : chipIn;
  const toRow1 = act1 ? easeInOut(span(time, ACT1[5] + .1 + rank1 * .08, 1)) : 0;
  const toRow2 = easeInOut(span(time, ACT2[5] + .3 + rank2 * .22, 1));
  const leave = easeInOut(span(time, OUTRO, .7));
  // Act 1 path: response card, then one-case leaderboard row, which sinks away as act 2 begins.
  const x = inChips ? lerp(lerp(-760, cx, chipIn), 0, toRow2) : lerp(lerp(760, RESP_X, enter), 0, toRow1);
  const y = inChips ? lerp(cy, ROW8_Y[rank2], toRow2) : lerp(RESP_Y[Math.max(0, m)], ROW_Y[Math.max(0, rank1)], toRow1);
  const width = inChips ? lerp(CHIP_W, ROW8_W, toRow2) : lerp(RESP_W, 540, toRow1);
  const height = inChips ? lerp(CHIP_H, ROW8_H, toRow2) : lerp(108, 76, toRow1);
  const z = inChips ? lerp(-260, 0, chipIn) + CHIP_Z * (1 - toRow2) - 420 * leave : lerp(-260, 0, enter) - 160 * rowOut;
  const row2 = clamp(toRow2 * 2 - 1);
  const count1 = caseCount(model);
  const severe1 = isSevereResponse(model);
  const pulse = .5 + .5 * Math.sin(time * 6 + s * 2) * span(time, ACT2[2], .3) * (1 - span(time, ACT2[3], .5));
  /** The rating is circled once scored; a severe answer also gets its whole sheet outlined in red. */
  const sheetMark = act1 && severe1 ? easeInOut(span(time, ACT1[4] + .1, .6)) * (1 - clamp(toRow1 * 3)) : 0;
  const bar = easeOut(span(time, ACT2[5] + .6 + rank2 * .22, .7));
  /** The leader of the final board gets its rank circled once the bars are in. */
  const bar1 = act1 ? easeOut(span(time, ACT1[5] + .5 + Math.max(0, rank1) * .15, .6)) : 0;
  return <div className={`${styles.card} ${styles.chip}`} style={{
    width: sx(width),
    height,
    opacity: inChips ? clamp(chipIn * 1.5) * (1 - leave) : clamp(enter * 1.5) * (1 - rowOut),
    transform: place(x, y, z, `rotateY(${lerp(inChips ? 30 : -30, 0, enter).toFixed(2)}deg)`),
  }}>
    <Mark draw={sheetMark} fade={1 - easeInOut(span(real, SEVERE_FADE_REAL, .4))} color={HARM_RED} padX={-2} padY={-2} radius={3} width={1.5} />
    {act1 && !inChips && <div className={styles.respLayer} style={{ opacity: 1 - clamp(toRow1 * 2) }}>
      <div className={styles.respHead}>
        <span className={styles.respName}>{model}<Thinking real={real} amount={act1 ? thinkingAmount(feed, m) : 0} /></span>
        <span className={`${styles.pill} ${styles.pillSmall} ${severe1 ? styles.pillSevere : styles.pillNone}`} style={{ opacity: score1(time, m), transform: `scale(${lerp(.85, 1, score1(time, m)).toFixed(3)})` }}>{harmLabel(responseOf(model).harm)}</span>
      </div>
      <p className={styles.respText}>{responseOf(model).text.slice(0, answerCount(feed, m))}{answerTyping(feed, m) && <span className={styles.caret} />}</p>
    </div>}
    {act1 && !inChips && <div className={styles.rowLayer} style={{ opacity: clamp(toRow1 * 2 - 1), transform: `translateY(${((1 - clamp(toRow1 * 2 - 1)) * 8).toFixed(2)}px)` }}>
      <span className={styles.rank}>{rank1 + 1}</span>
      <span className={styles.rowModel}>{model}</span>
      <span className={styles.boardTrack}>
        <span className={styles.boardBar} style={{ width: `${(BAR_MAX * (1 - .8 * count1) * 100 * bar1).toFixed(1)}%`, background: `rgb(${rgb(SAFE)})` }} />
      </span>
    </div>}
    <div className={styles.chipLayer} style={{ opacity: inChips ? 1 - clamp(toRow2 * 2) : 0 }}>
      <span className={styles.chipDot} style={{ opacity: (.55 + .45 * pulse).toFixed(3) }} />{model}
    </div>
    <div className={styles.boardRow} style={{ opacity: row2, transform: `translateY(${((1 - row2) * 6).toFixed(2)}px)` }}>
      <span className={`${styles.boardRank} ${styles.marked}`}>{rank2 + 1}</span>

      <span className={styles.boardModel}>{model}</span>
      <span className={styles.boardTrack}>
        <span className={styles.boardBar} style={{ width: `${(FINAL_BARS[rank2] * 100 * bar).toFixed(1)}%`, background: `rgb(${rgb(SAFE)})` }} />
      </span>
    </div>
  </div>;
}

/** Every card is fully formed before the typing slow-motion stretch begins at TYPE_AT. */
const fillStart = (index: number): number => T2 + .45 + index * .025;
/**
 * Act 2 typing: every new case is written at once but not in step. Each card starts after its own
 * offset and types at its own rate, both from a fixed formula, so some finish well before others.
 */
const typeStart = (index: number): number => TYPE_REAL + ((index * 5) % 11) / 11 * .6;
const typeRate = (index: number): number => 46 + ((index * 7) % 9) * 6;
const typedCount = (index: number, real: number): number =>
  index === 0 ? CASES[0].text.length : Math.max(0, Math.min(CASES[index].text.length, Math.floor((real - typeStart(index)) * typeRate(index))));

const LEVELS = [styles.levelNone, styles.levelMid, styles.levelSevere];

function Cell({ time, real, index }: { time: number; real: number; index: number }) {
  if (time < T2 || time >= ACT2[5] + .9) return null;
  const { title, text } = CASES[index];
  const col = index % COLS;
  const row = Math.floor(index / COLS);
  const [cx, cy] = cellPos(index);
  // The seed card waits for the one-case board rows to clear, and still settles before the typing stretch at TYPE_AT.
  const seedIn = easeOut(span(time, T2 + .25, .45));
  const seedMove = easeInOut(span(time, T2 + .5, .58));
  const fill = index === 0 ? seedIn : easeOut(span(time, fillStart(index), .35));
  if (fill <= 0) return null;
  const collapse = easeInOut(span(time, ACT2[5] + col * .05 + row * .03, .7));
  const x = lerp(index === 0 ? lerp(0, cx, seedMove) : cx, 0, collapse);
  const y = lerp(index === 0 ? lerp(0, cy, seedMove) : cy, 0, collapse);
  const z = (index === 0 ? -60 * (1 - seedIn) : -40 * (1 - fill)) - 260 * collapse;
  const scale = (index === 0 ? lerp(1.25, 1, seedMove) : lerp(.92, 1, fill)) * (1 - .6 * collapse);
  const rubricStart = ACT2[1] + col * .18 + row * .06;
  const cellScore = easeOut(span(time, ACT2[4] + .05 + col * .08 + row * .03, .5));
  const severe = SCALE.some((model) => isSevere(model, title));
  const tone = rgb(severe ? RED : SAFE);
  const count = typedCount(index, real);
  const typing = count > 0 && count < text.length;
  return <div className={`${styles.card} ${styles.cell}`} style={{
    width: sx(CELL_W),
    opacity: fill * (1 - collapse),
    transform: place(x, y, z, `scale(${scale.toFixed(3)})`),
    borderColor: !severe && cellScore > 0 ? `rgba(${tone}, ${(.12 + cellScore * .22).toFixed(3)})` : typing ? `rgba(${rgb(BLUE)}, .35)` : undefined,
  }}>
    <p className={styles.cellText}>{text.slice(0, count)}{typing && <span className={styles.caret} />}</p>
    <div className={styles.cellStrip}>
      <span className={styles.stripLabel} style={{ opacity: easeOut(span(time, rubricStart, .4)) }}>Rubric</span>
      {LEVELS.map((level, k) => {
        const chip = easeOut(span(time, rubricStart + .08 + k * .06, .4));
        return <span key={level} className={`${styles.chipLevel} ${level}`} style={{ opacity: chip, transform: `scaleX(${chip.toFixed(3)})`, transformOrigin: "left center" }} />;
      })}
    </div>
    <div className={styles.cellMarks}>
      {SCALE.map((model, m) => {
        const appear = easeOut(span(time, ACT2[2] + .1 + col * .16 + row * .04 + m * .04, .35));
        const graded = easeOut(span(time, ACT2[3] + (col + .5) * .18, .3));
        const score = easeOut(span(time, ACT2[4] + col * .08 + row * .03, .35));
        const bad = isSevere(model, title);
        const toneFill = bad ? RED : SAFE;
        const toneInk = bad ? RED_INK : SAFE_INK;
        return <span key={model} className={styles.markDot} style={{
          opacity: appear,
          transform: `scale(${(.6 + .4 * appear + .15 * Math.sin(Math.PI * graded)).toFixed(3)})`,
          background: mix(BLUE, toneFill, score, lerp(.12 + .14 * graded, bad ? .92 : .7, score)),
          borderColor: mix(BLUE, toneInk, score, lerp(.35 + .4 * graded, .9, score)),
        }} />;
      })}
    </div>
  </div>;
}

/** Act 2 responses: threads from each model chip into each grid row, in a 1000 x 620 space. */
function Streams({ time }: { time: number }) {
  if (time < ACT2[2] - .1 || time >= ACT2[3] + .2) return null;
  const visible = easeOut(span(time, ACT2[2], .3)) * (1 - easeInOut(span(time, ACT2[3] - .2, .4)));
  const edge = 500 + cellPos(0)[0] - CELL_W / 2;
  const end = 500 + cellPos(3)[0] + CELL_W / 2;
  return <svg className={styles.streams} viewBox="0 0 1000 620" preserveAspectRatio="none" style={{ width: sx(1000), transform: place(0, 0, -8), opacity: visible }}>
    {SCALE.map((_, i) => [-1, 0, 1].map((rowOffset, j) => {
      const [chipX, chipY] = chipPos(i);
      const x0 = 500 + chipX + CHIP_W / 2;
      const y0 = 310 + chipY;
      const y1 = 310 + rowOffset * PITCH_Y;
      const d = `M${x0} ${y0} C${x0 + 60} ${y0} ${edge - 60} ${y1} ${edge} ${y1} L${end} ${y1}`;
      const draw = easeInOut(span(time, ACT2[2] + .05 + i * .06 + j * .04, .8));
      const travel = -((time * .45 + i * .17 + j * .29) % 1);
      return <g key={`${i}-${j}`}>
        <path d={d} fill="none" stroke={ACCENT} strokeOpacity=".35" strokeWidth="1.25" {...inked(draw)} />
        <path d={d} fill="none" stroke={ACCENT} strokeOpacity={(.9 * draw).toFixed(3)} strokeWidth="1.75" strokeLinecap="round" pathLength={1} strokeDasharray=".05 .95" strokeDashoffset={travel.toFixed(4)} />
      </g>;
    }))}
  </svg>;
}

function Scan({ time }: { time: number }) {
  if (time < ACT2[3] || time >= ACT2[4] + .1) return null;
  const p = easeInOut(span(time, ACT2[3] + .05, .8));
  return <div className={styles.scan} style={{ opacity: Math.sin(Math.PI * p).toFixed(3), transform: place(lerp(-360, 560, p), 0, 6) }} />;

}

function Scene({ time, real, fill, gen, review, feed }: { time: number; real: number; fill: number; gen: number; review: number; feed: number }) {
  return <>
    <Composer time={time} real={real} />
    <Premise time={time} gen={gen} />
    <RubricPanel gen={gen} review={review} />
    <CaseCard time={time} real={real} fill={fill} gen={gen} />
    <D1Card time={time} real={real} review={review} />
    <GradeLines time={time} />
    <BoardTitle time={time} />
    <ScaleTitle time={time} />
    <FinalTitle time={time} />
    <Streams time={time} />
    {CASES.map((item, index) => <Cell key={item.title} time={time} real={real} index={index} />)}
    <Scan time={time} />
    <CaseFeed feed={feed} />
    <KitFork real={real} />
    {SCALE.map((model) => <ModelCard key={model} time={time} real={real} feed={feed} model={model} />)}
  </>;
}

/** ARISEKit kits; the framing's task decides which one builds the benchmark. */
const KITS = [
  { name: "MultiturnKit", task: "Multi-turn conversations", icon: "conversation" },
  { name: "NOHARMKit", task: "Medical cases", icon: "rubric" },
  { name: "PhysicianBenchKit", task: "Clinical agent tasks", icon: "agent" },
] as const;
const KIT_X = [-270, 0, 270];
const KIT_Y = 10;
const KIT_W = 230;
const KIT_H = 96;
const CHOSEN_KIT = 1;

/** Kit names as wordmarks: the prefix bold, "Kit" in the lighter weight. */
function KitName({ name }: { name: string }) {
  return <><span className={styles.wordmarkBold}>{name.slice(0, -3)}</span><span className={styles.wordmarkLight}>Kit</span></>;
}

function KitIcon({ kind }: { kind: "rubric" | "agent" | "conversation" }) {
  return <svg viewBox="0 0 48 48" width="30" height="30" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
    {kind === "rubric" && <><rect x="8" y="7" width="32" height="34" rx="5" /><path d="M8 18h32M20 18v23M26 25h8M26 33h8" /><path d="m12 25 2 2 3-4m-5 11 2 2 3-4" strokeLinecap="round" strokeLinejoin="round" /></>}
    {kind === "agent" && <><rect x="18" y="18" width="12" height="12" rx="3" /><rect x="3" y="3" width="10" height="10" rx="3" /><rect x="35" y="3" width="10" height="10" rx="3" /><rect x="3" y="35" width="10" height="10" rx="3" /><rect x="35" y="35" width="10" height="10" rx="3" /><path d="m12 12 7 7m10 0 7-7m-24 24 7-7m10 0 7 7" /></>}
    {kind === "conversation" && <><path d="M23 18h14a5 5 0 0 1 5 5v20l-9-6H23a5 5 0 0 1-5-5v-9a5 5 0 0 1 5-5Z" strokeLinejoin="round" /><path d="M10 6h19a5 5 0 0 1 5 5v12a5 5 0 0 1-5 5H17L5 35V11a5 5 0 0 1 5-5Z" fill="#ffffff" strokeLinejoin="round" /></>}
  </svg>;
}

/**
 * Kit fork, as a fraction `kit` of its beat: dashed threads run from the question to all three kits,
 * the medical-cases thread turns solid and NOHARMKit is picked, then the other kits fall away.
 */
function KitFork({ real }: { real: number }) {
  const kit = (real - KIT_REAL) / KIT;
  if (kit <= 0 || kit >= 1.05) return null;
  const pick = easeInOut(span(kit, .36, .12));
  const away = easeInOut(span(kit, .82, .18));
  const x0 = 500;
  const y0 = 310 - 160;
  return <>
    <svg className={styles.streams} viewBox="0 0 1000 620" preserveAspectRatio="none" style={{ width: sx(1000), transform: place(0, 0, 2), opacity: 1 - away }}>
      {KITS.map((item, i) => {
        const x1 = 500 + KIT_X[i];
        const y1 = 310 + KIT_Y - KIT_H / 2;
        const d = `M${x0} ${y0} C${x0} ${y0 + 60} ${x1} ${y1 - 60} ${x1} ${y1}`;
        const draw = easeInOut(span(kit, .02 + i * .04, .2));
        const chosen = i === CHOSEN_KIT;
        return <g key={item.name}>
          <path d={d} fill="none" stroke={`rgba(${rgb(INK)}, .28)`} strokeWidth="1.25" strokeDasharray="4 5" style={{ opacity: +(draw * (chosen ? 1 - pick : 1 - .6 * pick)).toFixed(3) }} />
          {chosen && <path d={d} fill="none" stroke={ACCENT} strokeWidth="1.75" {...inked(pick)} />}
          <circle cx={x1} cy={y1} r="3" fill="#ffffff" stroke={chosen ? ACCENT : `rgba(${rgb(INK)}, .35)`} strokeWidth="1.25" opacity={draw.toFixed(3)} />
        </g>;
      })}
      <circle cx={x0} cy={y0} r="3" fill="#ffffff" stroke={ACCENT} strokeWidth="1.25" />
    </svg>
    {KITS.map((item, i) => {
      const chosen = i === CHOSEN_KIT;
      const appear = easeOut(span(kit, .1 + i * .06, .2));
      const dim = chosen ? 0 : pick;
      const leave = chosen ? away : easeInOut(span(kit, .74, .14));
      return <div key={item.name} className={`${styles.card} ${styles.kitCard}`} style={{
        width: sx(KIT_W),
        height: KIT_H,
        opacity: +(appear * (1 - .6 * dim) * (1 - leave)).toFixed(3),
        borderColor: chosen ? mix(HAIRLINE, BLUE, pick) : undefined,
        transform: place(KIT_X[i], KIT_Y + 14 * (1 - appear) - 10 * leave, 6, `scale(${(1 + .03 * (chosen ? pick : 0)).toFixed(3)})`),
      }}>
        <span className={styles.kitIcon} style={{ color: chosen ? mix(MUTED, BLUE, pick) : `rgb(${rgb(MUTED)})` }}><KitIcon kind={item.icon} /></span>
        <span className={styles.kitText}><strong><KitName name={item.name} /></strong><span>{item.task}</span></span>
      </div>;
    })}
  </>;
}

function EndCard({ time }: { time: number }) {
  const start = OUTRO + .1;
  if (time < start) return null;
  const mark = easeOut(span(time, start + .1, .8));
  const line = easeInOut(span(time, start + .45, .8));
  return <div className={styles.endCard}>
    <div className={styles.wordmarkWrap} style={{ opacity: mark, transform: `translateY(${((1 - mark) * 8).toFixed(2)}px)` }}>
      <h2 className={styles.wordmark}><strong className={styles.wordmarkBold}>ARISE</strong><span className={styles.wordmarkLight}>Kit</span></h2>
    </div>
    <div className={styles.sweepLine}><Line draw={line} offset={0} width={2} /></div>
  </div>;
}

/**
 * Film time stops at each pause while real time runs on:
 * HOLD while the framing's specialty slot flips, FILL while the case card's fields fill in and
 * hold, GEN while the rubric is generated, SCORE on the graded result, BOARD on the one-case leaderboard.
 */
const HOLD_AT = 2.35;
const HOLD = 6.9;
const FILL_AT = 4.1;
const FILL = 3.6;
const GEN_AT = 4.55;
const GEN = 8;
const REVIEW = 7.5;
/**
 * Slow-motion stretches (not freezes) so the responses and autograding callouts can be read: film
 * time keeps running at a smoothly reduced speed, so cards settle and grading lines draw in slowly.
 */
/** The case is fed to the three models and their answers are written; film time creeps forward slowly. */
const FEED_AT = 5.4;
const FEED = 5;
const FEED_ADVANCE = .6;
const GRADE_AT = 7.1;
const GRADE_SLOW = 2;
/** Grading lines draw at normal speed, then the matches hold until scoring starts. */
const GRADE_ADVANCE = 1.1;
const SCORE_AT = 9;
const SCORE_HOLD = .9;
const BOARD_AT = 10.6;
const BOARD_HOLD = .9;
/** Act 2 hold while the new cases type in (typing runs on real time); the model chips arrive only after it. */
const TYPE_AT = T2 + 1.1;
const TYPE_SLOW = 1.6;
const TYPE_ADVANCE = .5;
const CHIPS_IN = T2 + 1.75;
/** [film time, real length, film advance]: film plays `advance` seconds at normal speed, then holds for the rest of `length`. */
/** The question routes to a kit while the premise holds, before the first case arrives. */
const KIT_AT = 3.28;
const KIT = 3.4;
const PAUSES: Array<[number, number, number]> = [[HOLD_AT, HOLD, 0], [FILL_AT, FILL, 0], [GEN_AT, GEN, 0], [GEN_AT, REVIEW, 0], [FEED_AT, FEED, FEED_ADVANCE], [GRADE_AT, GRADE_SLOW, GRADE_ADVANCE], [SCORE_AT, SCORE_HOLD, 0], [BOARD_AT, BOARD_HOLD, 0], [TYPE_AT, TYPE_SLOW, TYPE_ADVANCE], [KIT_AT, KIT, 0]];
const PAUSE_TOTAL = PAUSES.reduce((sum, [, length, advance]) => sum + length - advance, 0);
/** Longest ease into or out of a hold, in film seconds; shorter where the neighbouring hold is close. */
const MAX_RAMP = .5;
/**
 * Real-time layout of the film clock. Each hold sits at film time F (a pause's start plus its advance).
 * Instead of stopping dead, the clock eases from full speed to rest over film [F - pre, F] and back up
 * over [F, F + post] (smoothstep speed, so speed never jumps). The ramps come out of the hold's own
 * length, so the total running time is unchanged.
 */
type ClockSegment = { real: number; film: number; length: number; kind: "play" | "decel" | "hold" | "accel"; span: number };
const CLOCK: ClockSegment[] = (() => {
  const holds: Array<{ at: number; length: number }> = [];
  for (const [at, length, advance] of PAUSES) {
    const point = at + advance;
    const existing = holds.find((hold) => hold.at === point);
    if (existing) existing.length += length - advance;
    else holds.push({ at: point, length: length - advance });
  }
  holds.sort((a, b) => a.at - b.at);
  const segments: ClockSegment[] = [];
  let real = 0;
  let film = 0;
  const push = (kind: ClockSegment["kind"], length: number, span: number) => {
    if (length <= 0) return;
    segments.push({ real, film, length, kind, span });
    real += length;
    film += span;
  };
  holds.forEach((hold, i) => {
    const before = hold.at - (i === 0 ? 0 : holds[i - 1].at);
    const after = (i === holds.length - 1 ? DURATION : holds[i + 1].at) - hold.at;
    let pre = Math.min(MAX_RAMP, before / 2.2);
    let post = Math.min(MAX_RAMP, after / 2.2);
    // Each ramp costs its own length in extra real time; keep a sliver of true rest when the hold is short.
    const room = hold.length * .9;
    if (pre + post > room) { const k = room / (pre + post); pre *= k; post *= k; }
    push("play", hold.at - pre - film, hold.at - pre - film);
    push("decel", 2 * pre, pre);
    push("hold", hold.length - pre - post, 0);
    push("accel", 2 * post, post);
  });
  push("play", DURATION - film, DURATION - film);
  return segments;
})();
const warp = (real: number): number => {
  const segment = CLOCK.find((item) => real < item.real + item.length) ?? CLOCK[CLOCK.length - 1];
  const u = clamp((real - segment.real) / segment.length);
  const T = segment.length;
  if (segment.kind === "play") return segment.film + u * segment.span;
  if (segment.kind === "hold") return segment.film;
  // Speed 1 - smoothstep(u) while easing in, smoothstep(u) while easing out; integrals in closed form.
  if (segment.kind === "decel") return segment.film + T * (u - u ** 3 + u ** 4 / 2);
  return segment.film + T * (u ** 3 - u ** 4 / 2);
};
/**
 * Camera clock. Through each hold the camera keeps travelling along its planned path, slowly, then
 * runs a touch slower than the film over the following stretch until the two are back in step. The
 * camera never stops and never reverses because of a hold; it only ever moves the way its path goes.
 * Each lead is a smoothstep rise across the hold and a smoothstep fall across the next stretch, so
 * the camera's speed changes gently at every boundary.
 */
const CAMERA_LEADS: Array<{ riseFrom: number; riseTo: number; fallTo: number; lead: number }> = (() => {
  const windows: Array<{ from: number; to: number; filmEnd: number }> = [];
  for (let i = 0; i < CLOCK.length; i++) {
    if (CLOCK[i].kind !== "hold") continue;
    const first = CLOCK[i - 1]?.kind === "decel" ? CLOCK[i - 1] : CLOCK[i];
    const last = CLOCK[i + 1]?.kind === "accel" ? CLOCK[i + 1] : CLOCK[i];
    windows.push({ from: first.real, to: last.real + last.length, filmEnd: last.film + last.span });
  }
  return windows.map((window, i) => {
    const next = windows[i + 1];
    const fallTo = next ? next.from : DURATION + PAUSE_TOTAL;
    const gap = (next ? warp(next.from) : DURATION) - window.filmEnd;
    // Lead at most a third of the film stretch that follows, so the camera is back in step before the next hold.
    const lead = Math.max(0, Math.min(.3, gap / 3));
    return { riseFrom: window.from, riseTo: window.to, fallTo, lead };
  });
})();
const smooth = (u: number): number => { const x = clamp(u); return x * x * (3 - 2 * x); };
const cameraClock = (real: number): number => warp(real) + CAMERA_LEADS.reduce((sum, item) => {
  if (real <= item.riseFrom || real >= item.fallTo) return sum;
  if (real < item.riseTo) return sum + item.lead * smooth((real - item.riseFrom) / (item.riseTo - item.riseFrom));
  return sum + item.lead * (1 - smooth((real - item.riseTo) / (item.fallTo - item.riseTo)));
}, 0);

/** Real time at which film time first reaches `film` (the start of any hold sitting exactly there). */
const realAt = (film: number): number => {
  let lo = 0, hi = DURATION + PAUSE_TOTAL;
  for (let i = 0; i < 40; i++) { const mid = (lo + hi) / 2; if (warp(mid) < film) lo = mid; else hi = mid; }
  return hi;
};
const realOf = realAt;
/** Real time at which pause k's beat starts; pauses sharing a film time run back to back. */
const pauseStart = (k: number): number => realAt(PAUSES[k][0]) + PAUSES.slice(0, k).filter(([at]) => at === PAUSES[k][0]).reduce((sum, [, length]) => sum + length, 0);
const FILL_REAL = pauseStart(1);
const GEN_REAL = pauseStart(2);
const REVIEW_REAL = pauseStart(3);
const FEED_REAL = pauseStart(4);
const KIT_REAL = pauseStart(PAUSES.length - 1);
const reviewReal = (fraction: number): number => REVIEW_REAL + fraction * REVIEW;
const genReal = (fraction: number): number => GEN_REAL + fraction * GEN;
/** Marks hold briefly in real time, then lift. */
const OMIT_FADE_REAL = realAt(ACT1[3] + .8) + .9;
const SEVERE_FADE_REAL = realAt(ACT1[4] + .7) + .7;
const TYPE_REAL = realOf(T2 + 1);

/**
 * Margin notes, one at a time, anchored beside whatever is animating. Windows are in real
 * time so they ease in and out even while film time is paused. Anchor x is in design units
 * (scaled by --spread) plus a px offset; a thin leader runs from the note toward its target on the given side.
 */
type Callout = { start: number; end: number; x: number; dx?: number; y: number; z?: number; tail: "left" | "up" | "upStart" | "down"; text: string; width?: number; harm?: boolean };
const CALLOUTS: Callout[] = [
  { start: KIT_REAL + .42 * KIT, end: KIT_REAL + .84 * KIT, x: KIT_X[CHOSEN_KIT], y: KIT_Y + KIT_H / 2 + 18, tail: "up", text: "Medical cases use NOHARMKit", width: 280 },
  { start: realOf(3.75), end: genReal(.03), x: CASE_X + CASE_W / 2, dx: 16, y: CASE_TOP + 110, tail: "left", text: "Start with one of your own cases", width: 185 },
  // Sits beside the Generate button and leaves as the case card starts to dock.
  { start: genReal(.05), end: genReal(GEN_LAYOUT[0] + .02), x: CASE_X, dx: BUTTON_HALF + 20, y: BUTTON_Y - 8, tail: "left", text: "Auto-generate a NOHARM-style rubric", width: 440 },
  { start: genReal(.42), end: genReal(.97), x: PANEL_X - 40, y: 175, z: 60, tail: "up", text: "Highly detailed NOHARM rubrics, refined by multi-agent review", width: 330 },
  { start: reviewReal(.08), end: reviewReal(.97), x: REVIEW_X, y: REVIEW_TOP + D1_H + 16, z: 40, tail: "up", text: "Every step can be audited and revised by physicians", width: 260 },
  { start: FEED_REAL + .15, end: FEED_REAL + FEED + .6, x: RESP_X, y: RESP_Y[2] + 68, tail: "up", text: "Test your favorite models on the case", width: 260 },
  { start: realOf(7.1), end: realOf(7.1) + 2.8, x: D1_X, y: GRADE_TOP + GRADE_LAYOUT.height + 16, tail: "up", text: "The autograder maps each answer to the rubric" },
  { start: realOf(8.3), end: realOf(9.05), x: RESP_X, y: RESP_Y[0] - 62, tail: "down", text: "Model A: severe harm", harm: true },
  { start: realOf(CHIPS_IN + .2), end: realOf(ACT2[3]), x: chipPos(0)[0], y: chipPos(7)[1] + CHIP_H / 2 + 16, z: 40, tail: "up", text: "Test as many models as you want", width: 230 },
];

/** 0..1 visibility of a callout shown from `start` to `end` (real seconds). */
const calloutAmount = (real: number, start: number, end: number): number =>
  real < start || real >= end ? 0 : Math.min(easeOut(span(real, start, .3)), 1 - easeInOut(span(real, end - .3, .3)));

const TAIL_TRANSFORM: Record<Callout["tail"], string> = {
  left: "translate(0, -50%)",
  up: "translate(-50%, 0)",
  upStart: "translate(-14px, 0)",
  down: "translate(-50%, -100%)",
};
/** Leader geometry per side: a short stroke out of the note ending in a small open circle near the target. */
const LEADER: Record<Callout["tail"], { w: number; h: number; d: string; cx: number; cy: number }> = {
  left: { w: 18, h: 10, d: "M18 5H5.5", cx: 3, cy: 5 },
  up: { w: 10, h: 18, d: "M5 18V5.5", cx: 5, cy: 3 },
  upStart: { w: 10, h: 18, d: "M5 18V5.5", cx: 5, cy: 3 },
  down: { w: 10, h: 18, d: "M5 0V12.5", cx: 5, cy: 15 },
};

/** Every callout whose window is open; windows may overlap when two steps run together. */
function Callouts({ real }: { real: number }) {
  return <>{CALLOUTS.filter(({ start, end }) => real >= start && real < end).map((callout) => <Callout key={callout.text} callout={callout} real={real} />)}</>;
}

function Callout({ callout, real }: { callout: (typeof CALLOUTS)[number]; real: number }) {
  const { start, end, x, dx = 0, y, z = 30, tail, text, width = 300, harm = false } = callout;
  const draw = easeInOut(span(real, start, .35));
  const amount = calloutAmount(real, start, end);
  const color = harm ? HARM_RED : ACCENT;
  const leader = LEADER[tail];
  return <div className={`${styles.callout} ${styles[`leader_${tail}`]}`} style={{
    maxWidth: width,
    opacity: amount,
    transform: `translate3d(calc(${x.toFixed(2)} * var(--spread) + ${dx}px), ${y.toFixed(2)}px, ${z}px) ${TAIL_TRANSFORM[tail]}`,
  }}>
    <svg className={styles.leader} width={leader.w} height={leader.h} viewBox={`0 0 ${leader.w} ${leader.h}`} aria-hidden="true">
      <path d={leader.d} fill="none" stroke={color} strokeWidth="1.25" {...inked(draw)} />
      <circle cx={leader.cx} cy={leader.cy} r="2.5" fill="#ffffff" stroke={color} strokeWidth="1.25" opacity={clamp(draw * 4 - 3).toFixed(3)} />
    </svg>
    <span className={styles.calloutText} style={harm ? { color: "var(--red-ink)" } : undefined}>{text}</span>
  </div>;
}

function Film({ time: real }: { time: number }) {
  const time = warp(real);
  const fill = clamp((real - FILL_REAL + .15) / (FILL - .8));
  const gen = clamp((real - GEN_REAL) / GEN);
  const review = clamp((real - REVIEW_REAL) / REVIEW);
  const feed = clamp((real - FEED_REAL) / FEED);
  const [baseZ, rx, baseY] = camera(cameraClock(real));
  const view = `translateZ(${baseZ.toFixed(2)}px) rotateX(${rx.toFixed(3)}deg) rotateY(${baseY.toFixed(3)}deg)`;
  return <div className={styles.root}>
    <div className={styles.stage}>
      <div className={styles.world} style={{ transform: view }}>
        <Scene time={time} real={real} fill={fill} gen={gen} review={review} feed={feed} />
        <Callouts real={real} />
      </div>
    </div>
    <Rail time={time} />
    <EndCard time={time} />
  </div>;
}

const DayAnnotFilm: TrailerFilm = {
  id: "annot",
  name: "Annotated",
  duration: Number((DURATION + PAUSE_TOTAL).toFixed(2)),
  stepTimes: ACT1.map(realOf),
  Film,
};

export default DayAnnotFilm;
