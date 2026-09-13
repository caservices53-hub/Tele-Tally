import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GPT-Tally Connect Pro V2",
  description: "Local-first AI-assisted bulk accounting control centre for TallyPrime",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
