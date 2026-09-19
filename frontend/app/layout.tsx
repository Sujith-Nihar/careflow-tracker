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
        <header className="masthead">
          <div className="masthead-inner">
            <a className="wordmark" href="/calls">
              <span className="wordmark-dot" aria-hidden="true" />
              CareFlow
            </a>
            <span className="masthead-sub">Demo Surgical Associates</span>
          </div>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
