"use client";

import { useEffect, useRef, useState } from "react";

import DayAnnotFilm from "./film/DayAnnotFilm";
import styles from "./NoharmLoop.module.css";

const { Film } = DayAnnotFilm;
const LOOP_START = 20;
const LOOP_END = 58;
const STILL_TIME = 34;
const FADE = 0.5;

/** Plays the rubric, autograding, and scoring part of the trailer without its player controls. */
export function NoharmLoop() {
  const root = useRef<HTMLDivElement>(null);
  const [time, setTime] = useState(LOOP_START);
  const [box, setBox] = useState({ scale: 0, top: 0, width: 0 });

  useEffect(() => {
    const element = root.current!;
    const fit = (): void => {
      const { clientWidth: width, clientHeight: height } = element;
      const scale = Math.min(height / 620, width / 1240);
      setBox({ scale, top: (height - 620 * scale) / 2, width: width / scale });
    };
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    fit();
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setTime(STILL_TIME);
      return;
    }
    let frame = 0;
    let previous = performance.now();
    let current = LOOP_START;
    let visible = false;
    const tick = (now: number): void => {
      if (visible && !document.hidden) {
        current += (now - previous) / 1000;
        if (current >= LOOP_END) current = LOOP_START;
        setTime(current);
      }
      previous = now;
      frame = requestAnimationFrame(tick);
    };
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; }, { threshold: .15 });
    observer.observe(root.current!);
    frame = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); };
  }, []);

  const opacity = Math.min(1, (time - LOOP_START) / FADE, (LOOP_END - time) / FADE);
  return (
    <div
      className={styles.loop}
      ref={root}
      role="img"
      aria-label="NOHARMKit reviewing a synthetic case, autograding model responses, and comparing scores"
    >
      <div
        className={styles.canvas}
        style={{ top: box.top, width: box.width, transform: `scale(${box.scale})`, opacity }}
        aria-hidden="true"
      >
        <Film time={time} />
      </div>
    </div>
  );
}
