import "./globals.css";
import OncoShell from "@/components/shell/OncoShell";
import { Cormorant_Garamond, Manrope, Space_Mono } from "next/font/google";
import type { ReactNode } from "react";

const uiSans = Manrope({
  subsets: ["latin", "cyrillic-ext"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-sans",
  display: "swap",
});

const uiSerif = Cormorant_Garamond({
  subsets: ["latin", "cyrillic-ext"],
  weight: ["300", "400", "600", "700"],
  variable: "--font-serif",
  display: "swap",
});

const uiMono = Space_Mono({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata = {
  title: "OncoAI",
  description: "AI assistant for oncology protocol checks"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body className={`${uiSans.variable} ${uiSerif.variable} ${uiMono.variable} app-shell`}>
        <OncoShell>{children}</OncoShell>
      </body>
    </html>
  );
}
