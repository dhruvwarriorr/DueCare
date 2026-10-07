import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "DueCare | Your academic workspace",
  description: "Keep assignments and tests in one place.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
