import { Children, isValidElement } from "react";
import type { ReactNode } from "react";

export interface DropdownOption { value: string; label: string; disabled: boolean }

function textOf(node: ReactNode): string {
  return Children.toArray(node).map((child) => isValidElement<{ children?: ReactNode }>(child)
    ? textOf(child.props.children) : String(child)).join("");
}

export function dropdownOptions(children: ReactNode, disabled = false): DropdownOption[] {
  return Children.toArray(children).flatMap((child) => {
    if (!isValidElement<{ children?: ReactNode; value?: string | number; disabled?: boolean; label?: string }>(child)) return [];
    if (child.type !== "option") return dropdownOptions(child.props.children, disabled || !!child.props.disabled);
    const label = child.props.label ?? textOf(child.props.children);
    return [{ value: String(child.props.value ?? label), label, disabled: disabled || !!child.props.disabled }];
  });
}

export function moveOption(options: DropdownOption[], current: number, amount: number): number {
  const enabled = options.map((option, index) => option.disabled ? -1 : index).filter((index) => index >= 0);
  if (!enabled.length) return -1;
  const position = enabled.indexOf(current);
  const next = position < 0 ? (amount < 0 ? enabled.length - 1 : 0) : Math.max(0, Math.min(enabled.length - 1, position + amount));
  return enabled[next];
}

export function matchingOption(options: DropdownOption[], query: string, current: number): number {
  for (let offset = 1; offset <= options.length; offset += 1) {
    const index = (Math.max(current, -1) + offset) % options.length;
    if (!options[index].disabled && options[index].label.toLocaleLowerCase().startsWith(query.toLocaleLowerCase())) return index;
  }
  return current;
}

export function dropdownPosition(rect: { left: number; top: number; bottom: number; width: number }, viewport: { width: number; height: number }, count: number) {
  const width = Math.min(Math.max(rect.width, 200), viewport.width - 16);
  const below = viewport.height - rect.bottom - 14;
  const above = rect.top - 14;
  const upward = below < Math.min(count * 36 + 8, 180) && above > below;
  return {
    left: Math.max(8, Math.min(rect.left, viewport.width - width - 8)),
    width,
    maxHeight: Math.max(0, Math.min(288, upward ? above : below)),
    ...(upward ? { bottom: viewport.height - rect.top + 6 } : { top: rect.bottom + 6 }),
  };
}
