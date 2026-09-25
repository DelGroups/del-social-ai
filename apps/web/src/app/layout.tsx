import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DEL SOCIAL AI",
  description: "AI team for your social media",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="az" data-theme="midnight">
      <body>{children}</body>
    </html>
  );
}
