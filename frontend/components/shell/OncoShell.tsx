"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import AmbientLayers from "@/components/shell/AmbientLayers";
import SidebarNav from "@/components/shell/SidebarNav";
import ThemeToggle from "@/components/shell/ThemeToggle";

type OncoShellProps = {
  children: ReactNode;
};

function loadInitialTheme(): "dark" | "light" {
  if (typeof window === "undefined") return "dark";
  const persisted = window.localStorage.getItem("onco-theme");
  if (persisted === "light" || persisted === "dark") return persisted;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export default function OncoShell({ children }: OncoShellProps) {
  const pathname = usePathname();
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    setTheme(loadInitialTheme());
  }, []);

  useEffect(() => {
    const body = document.body;
    body.classList.toggle("light-theme", theme === "light");
    window.localStorage.setItem("onco-theme", theme);
  }, [theme]);

  return (
    <>
      <ThemeToggle theme={theme} onToggle={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))} />
      <div className="app-container">
        <AmbientLayers />
        <SidebarNav pathname={pathname} />
        <main className="main-view page-enter">{children}</main>
      </div>
    </>
  );
}

