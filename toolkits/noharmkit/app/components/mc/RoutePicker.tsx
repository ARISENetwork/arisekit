"use client";

import Dropdown from "@/components/Dropdown";
import { useLocalModelNavigation } from "@/components/mc/LocalResponses";
import { useOptionalMotionNavigation } from "@/components/NavigationMotion";
import { usePathname } from "next/navigation";
import { tutorialHref } from "@/lib/uti-tutorial";

interface RouteOption { value: string; label: string; href: string }

export default function RoutePicker({ id, label, value, options }: {
  id: string; label: string; value: string; options: RouteOption[];
}) {
  const navigate = useOptionalMotionNavigation();
  const navigateLocal = useLocalModelNavigation();
  const pathname = usePathname();
  const width = id === "mc-model" ? "w-52" : "w-28";
  return (
    <>
      <label className="sr-only" htmlFor={id}>{label}</label>
      <Dropdown aria-label={label} className={`${width} max-w-full shrink-0 rounded-md border border-mc-line bg-mc-surface-2 px-2 py-1 text-[13.5px] text-mc-ink`} id={id} title={options.find((option) => option.value === value)?.label} value={value} onChange={(event) => {
        const option = options.find((option) => option.value === event.target.value);
        if (!option) return;
        if (pathname === "/noharm/tutorial") { const href = tutorialHref(option.href); if (href) { if (id === "mc-model" && navigateLocal?.(href)) return; if (navigate) navigate(href); else window.location.assign(href); return; } }
        if (id === "mc-model" && navigateLocal?.(option.href)) return;
        if (navigate) navigate(option.href);
        else window.location.assign(option.href);
      }}>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </Dropdown>
    </>
  );
}
