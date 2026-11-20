import type { Metadata } from "next";
import Script from "next/script";
import type { ReactNode } from "react";
import NavigationMotion from "@/components/NavigationMotion";
import { projectVersion } from "@/lib/arisekit-version";

import "./globals.css";
import "./navigation-motion.css";
import "./severity-colors.css";
import "../../../../apps/web/shared/noharm-theme.css";

const THEME_MODE_SCRIPT = `try {
  localStorage.removeItem("noharm:mode");
  const theme = localStorage.getItem("theme");
  if (theme === "light" || theme === "dark") document.documentElement.dataset.mode = theme;
} catch {}`;

export const metadata: Metadata = {
  title: "ARISEKit",
  description: "Build medical AI benchmarks with MAST frameworks and custom designs",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" data-scroll-behavior="smooth" data-theme="berry" suppressHydrationWarning>
      <body className="antialiased">
        {/* Applies the light or dark choice saved by the local theme toggle before the page draws. */}
        <Script id="theme-mode" strategy="beforeInteractive">{THEME_MODE_SCRIPT}</Script>
        <NavigationMotion><div className="flex min-h-screen flex-col">
          <div className="navigation-content flex-1">{children}</div>
          <div className="kit-version">{projectVersion()}</div>

          <footer className="site-footer shrink-0 border-t border-[hsl(var(--border))]">
            <div className="px-6 py-3">
              <p className="m-0 py-2 text-center text-xs text-[hsl(var(--muted-foreground))]">© ARISE Network</p>
            </div>
          </footer>
        </div></NavigationMotion>
      </body>
    </html>
  );
}
