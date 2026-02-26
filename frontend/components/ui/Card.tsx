"use client";

import type { ReactNode } from "react";

type CardVariant = "default" | "hero" | "flat";

type Props = {
  children: ReactNode;
  className?: string;
  variant?: CardVariant;
  testId?: string;
  id?: string;
};

function cardClassName(variant: CardVariant, className?: string): string {
  const base = variant === "hero" ? "card hero-card" : variant === "flat" ? "card card-flat" : "card";
  return className ? `${base} ${className}` : base;
}

export default function Card({ children, className, variant = "default", testId, id }: Props) {
  return (
    <section id={id} className={cardClassName(variant, className)} data-testid={testId}>
      {children}
    </section>
  );
}
