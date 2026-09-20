import type { Metadata } from "next";
import LenisProvider from "@/components/LenisProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Compound Evals", template: "%s · Compound Evals" },
  description:
    "Resettable product environments and the scores models earned in them. Every score is read from the rows the product wrote.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <LenisProvider>{children}</LenisProvider>
      </body>
    </html>
  );
}
