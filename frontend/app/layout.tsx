import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "CareFlow — calls needing attention",
  description: "Which calls still need a human, and what the evidence actually shows.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="nav">
          <a href="/calls">CareFlow</a>
          <span className="muted"> · Demo Surgical Associates</span>
        </div>
        <main>{children}</main>
      </body>
    </html>
  );
}
