"use client";

import Link from "next/link";
import type { ReactNode } from "react";

type SidebarNavProps = {
  pathname: string;
};

type NavItem = {
  href: string;
  title: string;
  icon: ReactNode;
};

const NAV_ITEMS: NavItem[] = [
  {
    href: "/",
    title: "Сессия",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="10" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    )
  },
  {
    href: "/doctor",
    title: "Режим врача",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
      </svg>
    )
  },
  {
    href: "/patient",
    title: "Режим пациента",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
        <circle cx="12" cy="7" r="4" />
      </svg>
    )
  },
  {
    href: "/admin",
    title: "Администратор",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
        <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
        <line x1="6" y1="6" x2="6" y2="6" />
        <line x1="6" y1="18" x2="6" y2="18" />
      </svg>
    )
  }
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function SidebarNav({ pathname }: SidebarNavProps) {
  return (
    <aside className="sidebar no-print">
      <div className="sidebar-logo" aria-hidden="true">
        ◈
      </div>
      <div className="sidebar-divider" />
      {NAV_ITEMS.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          className={`nav-item ${isActive(pathname, item.href) ? "active" : ""}`}
          title={item.title}
          aria-label={item.title}
        >
          {item.icon}
        </Link>
      ))}
      <div className="sidebar-spacer" />
      <div className="sidebar-coords">48°52&apos;N · 002°21&apos;E · AETHER</div>
      <form action="/api/session/logout" method="post" className="sidebar-logout-form">
        <input type="hidden" name="next" value="/" />
        <button type="submit" className="nav-item nav-item-logout" title="Выйти" aria-label="Выйти">
          ↩
        </button>
      </form>
    </aside>
  );
}
