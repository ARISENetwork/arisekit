import type { AnchorHTMLAttributes, ReactNode } from "react";

export default function Link(props: AnchorHTMLAttributes<HTMLAnchorElement>): ReactNode {
  return <a {...props} />;
}
