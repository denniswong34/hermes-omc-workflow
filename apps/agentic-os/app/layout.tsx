import type { ReactNode } from "react";
import { Nav } from "@/components/Nav";
import { Providers } from "@/components/Providers";
import "./globals.css";

export const metadata = {
  title: "OMC Agentic OS",
  description: "Control plane for One Man Company workflows",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0b0f14",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <Nav />
          <main className="page-main">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
