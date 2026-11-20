import Link from "@/components/MotionLink";
import type { ReactNode } from "react";

interface Props { hard: boolean; href: string; children: ReactNode; className?: string; title?: string; "aria-current"?: "page" }

// On the review page the shell reloads the document instead of navigating in place: the editor guards unsaved
// edits only through beforeunload, which client-side navigation never fires.
export default function ShellLink({ hard, children, ...rest }: Props) {
  return hard ? <a {...rest}>{children}</a> : <Link {...rest}>{children}</Link>;
}
