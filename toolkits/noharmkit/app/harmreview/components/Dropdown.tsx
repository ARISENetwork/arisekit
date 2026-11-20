"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent, SelectHTMLAttributes } from "react";
import { createPortal } from "react-dom";

import { dropdownOptions, dropdownPosition, matchingOption, moveOption } from "@/harmreview/lib/dropdown";
import styles from "./Dropdown.module.css";

type Props = Omit<SelectHTMLAttributes<HTMLSelectElement>, "multiple" | "size">;

// Select-only combobox keyboard model: https://www.w3.org/WAI/ARIA/apg/patterns/combobox/examples/combobox-select-only/
export default function Dropdown({ children, className = "", id, autoFocus, title, disabled, tabIndex, style, ...props }: Props) {
  const generatedId = useId();
  const triggerId = id ?? `dropdown-${generatedId}`;
  const listId = `${triggerId}-list`;
  const trigger = useRef<HTMLButtonElement>(null);
  const native = useRef<HTMLSelectElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const typed = useRef({ text: "", time: 0 });
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [active, setActive] = useState(-1);
  const [label, setLabel] = useState<string>();
  const [position, setPosition] = useState<ReturnType<typeof dropdownPosition> | null>(null);
  // An option's data-description shows beside the highlighted option, by pointer or keyboard.
  const [tip, setTip] = useState<{ left: number; top: number; text: string } | null>(null);
  const options = dropdownOptions(children);
  const [uncontrolledValue, setUncontrolledValue] = useState(() => String(props.defaultValue ?? options[0]?.value ?? ""));
  const value = String(props.value ?? uncontrolledValue);
  const selected = options.findIndex((option) => option.value === value);

  useEffect(() => {
    setMounted(true);
    const text = Array.from(trigger.current?.labels ?? []).map((element) => {
      const copy = element.cloneNode(true) as HTMLElement;
      copy.querySelectorAll("button, select").forEach((control) => control.remove());
      return copy.textContent?.trim();
    }).filter(Boolean).join(" ");
    setLabel(text || undefined);
  }, [triggerId]);

  useEffect(() => {
    if (!open) return;
    const update = (): void => {
      const button = trigger.current;
      if (!button || button.closest("[inert]") || getComputedStyle(button).visibility === "hidden") { setOpen(false); return; }
      setPosition(dropdownPosition(button.getBoundingClientRect(), { width: window.innerWidth, height: window.innerHeight }, options.length));
    };
    const outside = (event: PointerEvent): void => {
      if (!trigger.current?.contains(event.target as Node) && !menu.current?.contains(event.target as Node)) setOpen(false);
    };
    update();
    const observer = new ResizeObserver(update);
    if (trigger.current) observer.observe(trigger.current);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    document.addEventListener("pointerdown", outside);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      document.removeEventListener("pointerdown", outside);
    };
  }, [open, options.length]);

  useEffect(() => {
    if (open && position && active >= 0) document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active, listId, open, position]);

  // The options array is rebuilt every render, so the effect keys on the description text, not the array.
  const activeDescription = open && position && active >= 0 ? options[active]?.description : undefined;
  useEffect(() => {
    const item = activeDescription ? document.getElementById(`${listId}-${active}`) : null;
    if (!activeDescription || !item || !menu.current) { setTip(null); return; }
    const box = menu.current.getBoundingClientRect();
    const width = 256;
    const left = box.right + 8 + width <= window.innerWidth ? box.right + 8 : Math.max(8, box.left - 8 - width);
    const top = item.getBoundingClientRect().top;
    setTip((current) => (current && current.left === left && current.top === top && current.text === activeDescription
      ? current : { left, top, text: activeDescription }));
  }, [active, activeDescription, listId, position]);

  const show = (index = selected): void => {
    if (disabled) return;
    setActive(index >= 0 && !options[index]?.disabled ? index : moveOption(options, -1, 1));
    setOpen(true);
  };
  const choose = (index: number): void => {
    const option = options[index];
    if (!option || option.disabled) return;
    setOpen(false);
    // Keep real form values and React change events, including currentTarget.form,
    // for the existing project switch and controlled editor handlers.
    if (option.value !== value && native.current) {
      if (props.value === undefined) setUncontrolledValue(option.value);
      native.current.value = option.value;
      native.current.dispatchEvent(new Event("change", { bubbles: true }));
    }
  };
  const keyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
    if (event.ctrlKey || event.metaKey) return;
    event.stopPropagation();
    if (event.key === "Tab") { if (open) choose(active); return; }
    if (event.key === "Escape") { event.preventDefault(); setOpen(false); return; }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open) choose(active); else show();
      return;
    }
    const amount = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : event.key === "PageDown" ? 10 : event.key === "PageUp" ? -10 : 0;
    if (amount) {
      event.preventDefault();
      if (open && event.altKey && amount === -1) choose(active);
      else if (open) setActive(moveOption(options, active, amount));
      else show();
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      show(moveOption(options, -1, event.key === "Home" ? 1 : -1));
      return;
    }
    if (event.key.length === 1 && !event.altKey) {
      event.preventDefault();
      const time = Date.now();
      const text = time - typed.current.time < 700 ? typed.current.text + event.key : event.key;
      typed.current = { text, time };
      const repeat = Array.from(text).every((letter) => letter.toLowerCase() === text[0].toLowerCase());
      show(matchingOption(options, repeat ? text[0] : text, repeat ? (open ? active : selected) : -1));
    }
  };

  return (
    <>
      <select {...props} aria-hidden="true" disabled={disabled} hidden ref={native} tabIndex={-1}>{children}</select>
      <button
        aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
        aria-controls={mounted ? listId : undefined}
        aria-describedby={props["aria-describedby"]}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={props["aria-label"] ?? label}
        aria-labelledby={props["aria-labelledby"]}
        aria-required={props.required}
        autoFocus={autoFocus}
        className={`${styles.trigger} ${className || "rounded-md border border-mc-line-strong px-2 py-1 text-sm"}`}
        disabled={disabled}
        id={triggerId}
        onBlur={() => setOpen(false)}
        onClick={() => open ? setOpen(false) : show()}
        onKeyDown={keyDown}
        ref={trigger}
        role="combobox"
        style={style}
        tabIndex={tabIndex}
        title={title}
        type="button"
      >
        <span className={styles.value}>{options[selected]?.label ?? options[0]?.label ?? "Choose"}</span>
        <svg aria-hidden="true" className={`${styles.chevron} ${open ? styles.rotated : ""}`} fill="none" stroke="currentColor" viewBox="0 0 16 16"><path d="m4 6 4 4 4-4" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" /></svg>
      </button>
      {mounted && createPortal(
        <div aria-hidden={!open || undefined} aria-label={props["aria-label"] ?? label} aria-labelledby={props["aria-labelledby"]} className={`${styles.menu} ${open && position ? styles.open : ""}`} id={listId} inert={!open || undefined} ref={menu} role="listbox" style={position ?? { left: 0, top: 0, width: 0, maxHeight: 0 }}>
          {options.map((option, index) => (
            <div aria-disabled={option.disabled || undefined} aria-selected={index === selected} className={`${styles.option} ${index === active ? styles.active : ""}`} id={`${listId}-${index}`} key={`${option.value}-${index}`} onClick={() => { if (!option.disabled) { trigger.current?.focus(); choose(index); } }} onPointerDown={(event) => event.preventDefault()} onPointerMove={() => { if (!option.disabled) setActive(index); }} role="option">
              <span aria-description={option.description}>{option.label}</span>
              {index === selected && <svg aria-hidden="true" className={styles.check} fill="none" stroke="currentColor" viewBox="0 0 16 16"><path d="m3 8 3 3 7-7" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" /></svg>}
            </div>
          ))}
        </div>, trigger.current?.closest("dialog") ?? document.body,
      )}
      {mounted && tip && createPortal(
        <div aria-hidden="true" className="pointer-events-none fixed z-[60] w-64 rounded-md bg-[hsl(var(--tip))] px-2.5 py-1.5 text-[11.5px] leading-snug text-[hsl(var(--tip-foreground))] shadow-lg" style={{ left: tip.left, top: tip.top }}>
          {tip.text.split("\n").map((line, index) => <p className={index ? "mt-1 text-[hsl(var(--tip-foreground))]/75" : ""} key={line}>{line}</p>)}
        </div>, trigger.current?.closest("dialog") ?? document.body,
      )}
    </>
  );
}
