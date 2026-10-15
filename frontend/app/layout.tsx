import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "PaperWise — Know what your documents say",
  description: "Ask questions about your documents and check every answer against its sources.",
  icons: { icon: "/app-logo.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
