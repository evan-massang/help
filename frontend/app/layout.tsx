import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "memeterm",
  description: "Local-first Solana meme-coin analyst",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen font-mono antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
