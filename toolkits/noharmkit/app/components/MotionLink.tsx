"use client";

import Link from "next/link";
import type { ComponentProps } from "react";

import { useOptionalMotionNavigation } from "@/components/NavigationMotion";

export default function MotionLink({ onNavigate, ...props }: ComponentProps<typeof Link>) {
  const navigate = useOptionalMotionNavigation();
  if (!navigate) return <Link {...props} onNavigate={onNavigate} />;
  return <Link {...props} onNavigate={(event) => {
    let blocked = false;
    onNavigate?.({ preventDefault: () => { blocked = true; event.preventDefault(); } });
    // Object URLs continue through Next's normal resolver; current app links use strings.
    if (blocked || typeof props.href !== "string") return;
    event.preventDefault();
    navigate(props.href, { replace: props.replace, scroll: props.scroll });
  }} />;
}
