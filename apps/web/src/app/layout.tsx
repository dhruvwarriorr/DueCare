import type { Metadata } from "next";
import { Sofia_Sans, Sofia_Sans_Condensed } from "next/font/google";
import "./globals.css";
const body = Sofia_Sans({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});
const condensed = Sofia_Sans_Condensed({
  subsets: ["latin"],
  variable: "--font-condensed",
  display: "swap",
});
export const metadata: Metadata = {
  title: "DueCare | Your academic workspace",
  description: "Keep assignments and tests in one place.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={body.variable + " " + condensed.variable}>
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
