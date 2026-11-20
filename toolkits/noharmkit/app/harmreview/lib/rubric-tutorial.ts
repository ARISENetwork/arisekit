// The guided tutorial of the rubric editor, on a synthetic UTI case (D190). The owner approved the example's ratings
// (D193); the popup text lives in data/tutorial/copy.json so it can be edited in place on the dev server. Steps name
// real editor elements, so the tutorial cannot drift into a separate approximation of the interface.
import tutorialCopy from "@/harmreview/data/tutorial/copy.json";
import tutorialCase from "@/harmreview/data/tutorial/uti.json";
import type { NeedSeverity, Score } from "./rubric";
import { newV2Item } from "./rubric-text-v2";
import type { TextV2Case, TextV2Item } from "./rubric-text-v2";
import type { CaseSource } from "./types";

export const TUTORIAL_RECORD = tutorialCase.record as TextV2Case;
export const TUTORIAL_SOURCE: CaseSource = tutorialCase.source;

const FIRST = "C2";
// The emergency referral, rated 3 and Mild, shows why a row takes two ratings.
const REFERRAL = "C2.2";
// The row "+ Add" creates: IDs are the next free number, and the tutorial reaches this step with no other row added.
export const ADDED = newV2Item(TUTORIAL_RECORD, TUTORIAL_RECORD.decisions[0]).id;
export const ADDED_TEXT = "Reassess clinically if symptoms have not improved within 48 hours.";

export interface TutorialState { record: TextV2Case; openIds: ReadonlySet<string> }

export function findItem(record: TextV2Case, id: string): TextV2Item | undefined {
  return record.decisions.flatMap((criterion) => criterion.recommendations).find((item) => item.id === id);
}

export interface StepCopy { caption: string; heading: string; text: string[] }
export const TUTORIAL_COPY: Readonly<Record<string, StepCopy>> = tutorialCopy;

interface TutorialStep extends StepCopy {
  id: string;
  // Every element matching is highlighted, as one box; absent on the overview.
  target?: string;
  // The cards open on arriving at this step, so Back and Next always show the same page.
  open: string[];
  // A step with a required action holds Next until it is done, and moves on by itself once it is.
  done?: (state: TutorialState) => boolean;
  // Shown after a wrong choice.
  hint?: (state: TutorialState) => string | null;
  // The control to click next, which glows.
  cue?: (state: TutorialState) => string;
  // Text the tutorial writes into the new row, so nothing has to be typed. Next waits until it is written.
  types?: { item: string; text: string };
}

const row = (item: string): string => `[data-v2-item="${item}"]`;
const zone = (name: "main" | "side"): string => `[data-v2-criterion="${FIRST}"] [data-role-zone="${name}"]`;
const scoreButton = (item: string, score: Score): string => `${row(item)} [data-rating-bar] button[aria-label^="${score}:"]`;
const severityMenu = (item: string): string => `${row(item)} [role="combobox"]`;
const hasScore = (state: TutorialState, item: string, score: Score): boolean => findItem(state.record, item)?.score === score;
const hasHarm = (state: TutorialState, item: string, harm: NeedSeverity): boolean => findItem(state.record, item)?.harm === harm;

// The copy file holds each step's caption, heading and text; a step without copy fails the tests.
const copy = (id: string): StepCopy & { id: string } => ({ id, ...TUTORIAL_COPY[id] });

export const TUTORIAL_STEPS: readonly TutorialStep[] = [
  { ...copy("welcome"), open: [] },
  { ...copy("case"), target: "[data-rubric-text-v2] aside", open: [] },
  // Introduces the criteria list and opens the first one.
  {
    ...copy("open-first"),
    target: "[data-v2-criteria]",
    open: [],
    done: ({ openIds }) => openIds.has(FIRST),
    cue: () => `button[aria-controls="${FIRST}-body"]`,
  },
  // The main approach and the two ratings each row takes.
  { ...copy("main-approach"), target: zone("main"), open: [FIRST] },
  { ...copy("rate-score"), target: `${row(REFERRAL)} [data-score-cell]`, open: [FIRST] },
  { ...copy("severity"), target: `${zone("main")} [data-severity-cell]`, open: [FIRST] },
  { ...copy("rate-severity"), target: `${row(REFERRAL)} [data-severity-cell]`, open: [FIRST] },
  { ...copy("omission"), target: `[data-v2-criterion="${FIRST}"] [data-unaddressed]`, open: [FIRST] },
  // Usual care comes after the omission row, because it caps every omission.
  { ...copy("usual-care"), target: "[data-usual-care-row]", open: ["D0", FIRST] },
  { ...copy("add-ons"), target: zone("side"), open: ["D0", FIRST] },
  {
    ...copy("add"),
    target: `[data-add-v2-item="${FIRST}"]`,
    open: ["D0", FIRST],
    done: (state) => findItem(state.record, ADDED) !== undefined,
    cue: () => `[data-add-v2-item="${FIRST}"]`,
  },
  // The new row's text writes itself in, then the reviewer rates it.
  {
    ...copy("rate-added"),
    target: row(ADDED),
    open: ["D0", FIRST],
    types: { item: ADDED, text: ADDED_TEXT },
    done: (state) => hasScore(state, ADDED, 7) && hasHarm(state, ADDED, "none"),
    hint: (state) => {
      const item = findItem(state.record, ADDED);
      if (item?.score != null && item.score !== 7) return "For this example, click 7.";
      if (item?.harm != null && item.harm !== "none") return "For this example, pick None.";
      return null;
    },
    cue: (state) => (hasScore(state, ADDED, 7) ? severityMenu(ADDED) : scoreButton(ADDED, 7)),
  },
  {
    ...copy("move"),
    target: `${row(ADDED)}, ${zone("side")}`,
    open: ["D0", FIRST],
    done: (state) => findItem(state.record, ADDED)?.addOn === true,
    cue: () => `${row(ADDED)} [data-move-role]`,
  },
  { ...copy("finish"), target: "[data-rubric] header", open: ["D0", FIRST] },
];
