"use client";

import { Suspense } from "react";
import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

import KeyNav from "@/components/mc/KeyNav";
import WelcomeWorkspace from "@/components/mc/WelcomeWorkspace";
import type { NavData } from "@/components/mc/nav";
import { localPath } from "@/lib/noharm-path";

export default function Frame({ nav, children }: { nav: NavData; children: ReactNode }) {
  const path = localPath(usePathname());
  const opening = path === "/welcome";
  return <Suspense fallback={null}>
    <WelcomeWorkspace nav={nav}>{children}</WelcomeWorkspace>
    {!opening && <KeyNav />}
  </Suspense>;
}
