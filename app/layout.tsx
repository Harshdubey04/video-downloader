import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Fetchly — Download videos online",
  description: "Inspect and download authorized, non-DRM media from supported sources."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
