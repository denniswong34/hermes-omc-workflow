"use client";

import type { ReactNode } from "react";
import { ProjectProvider } from "@/lib/project-context";

export function Providers({ children }: { children: ReactNode }) {
  return <ProjectProvider>{children}</ProjectProvider>;
}
