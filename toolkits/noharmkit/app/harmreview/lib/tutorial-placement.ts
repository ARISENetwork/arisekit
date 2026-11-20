// Where the tutorial popup goes. All boxes are viewport coordinates, as getBoundingClientRect reports them.
export interface Box { top: number; left: number; width: number; height: number }
export interface View { width: number; height: number; topInset: number }
type Side = "below" | "above" | "right" | "left";
export interface Placement { top: number; left: number; side: Side | null; caret: number }

export const GAP = 14;
const MARGIN = 12;
const CARET_INSET = 22;
// An overview sits a little above center, where the eye lands first.
const RISE = 0.35;

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(value, max));

export function unionBox(boxes: readonly Box[]): Box | null {
  const shown = boxes.filter((box) => box.width > 0 && box.height > 0);
  if (!shown.length) return null;
  const top = Math.min(...shown.map((box) => box.top));
  const left = Math.min(...shown.map((box) => box.left));
  return { top, left, width: Math.max(...shown.map((box) => box.left + box.width)) - left, height: Math.max(...shown.map((box) => box.top + box.height)) - top };
}

// The first side the popup fits on, else the side with the most room. Beside or under the target, never over it when it fits.
export function placePopup(target: Box | null, popup: { width: number; height: number }, view: View): Placement {
  if (!target) {
    return { left: (view.width - popup.width) / 2, top: view.topInset + Math.max(MARGIN, (view.height - view.topInset - popup.height) * RISE), side: null, caret: 0 };
  }
  // Room left after the popup on each side of the target, within the viewport below the sticky header.
  const spare: Record<Side, number> = {
    below: view.height - (target.top + target.height) - popup.height,
    above: target.top - view.topInset - popup.height,
    right: view.width - (target.left + target.width) - popup.width,
    left: target.left - popup.width,
  };
  const order: Side[] = ["below", "above", "right", "left"];
  const side = order.find((name) => spare[name] >= GAP + MARGIN) ?? order.reduce((best, name) => (spare[name] > spare[best] ? name : best));
  const vertical = side === "below" || side === "above";
  const beside = side === "right" ? target.left + target.width + GAP : target.left - popup.width - GAP;
  const stacked = side === "below" ? target.top + target.height + GAP : target.top - popup.height - GAP;
  const left = clamp(vertical ? target.left + (target.width - popup.width) / 2 : beside, MARGIN, view.width - popup.width - MARGIN);
  const top = clamp(vertical ? stacked : target.top + (target.height - popup.height) / 2, view.topInset + MARGIN, view.height - popup.height - MARGIN);
  const caret = vertical
    ? clamp(target.left + target.width / 2 - left, CARET_INSET, popup.width - CARET_INSET)
    : clamp(target.top + target.height / 2 - top, CARET_INSET, popup.height - CARET_INSET);
  return { top, left, side, caret };
}

// How far to scroll so the target and the popup show together: nothing when they already do.
export function scrollDelta(target: Box, popupHeight: number, view: View): number {
  const usable = view.height - view.topInset;
  const visible = target.top >= view.topInset + MARGIN && target.top + target.height <= view.height - MARGIN;
  const fits = (space: number): boolean => space >= popupHeight + GAP + MARGIN;
  if (visible && (fits(view.height - target.top - target.height) || fits(target.top - view.topInset))) return 0;
  const region = target.height + GAP + popupHeight;
  const top = region + 2 * MARGIN <= usable ? view.topInset + (usable - region) / 2 : view.topInset + MARGIN;
  return target.top - top;
}
