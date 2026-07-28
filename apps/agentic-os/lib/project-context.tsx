"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { apiGet, apiPut, setApiProjectId } from "@/lib/api";

export type Project = {
  id: string;
  name: string;
  working_directory: string;
  github_repo: string;
  github_username: string;
  has_pat?: boolean;
  created_at?: string;
  updated_at?: string;
};

type ProjectContextValue = {
  projects: Project[];
  activeProject: Project | null;
  loading: boolean;
  error: string;
  refresh: () => Promise<void>;
  switchProject: (projectId: string) => Promise<void>;
};

const ProjectContext = createContext<ProjectContextValue | null>(null);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProject, setActiveProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const pathname = usePathname();
  const router = useRouter();

  const refresh = useCallback(async () => {
    setError("");
    const list = await apiGet<{ projects: Project[] }>("/api/projects");
    const projectsList = list.projects || [];
    setProjects(projectsList);

    const activeRes = await apiGet<{ project: Project | null }>("/api/projects/active");
    let active = activeRes.project;
    if (!active && projectsList.length > 0) {
      active = projectsList[0];
      await apiPut("/api/projects/active", { project_id: active.id });
    }
    setActiveProject(active);
    setApiProjectId(active?.id ?? null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        await refresh();
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  useEffect(() => {
    if (loading) return;
    const onProjectsRoute = pathname === "/projects" || pathname.startsWith("/projects/");
    if (projects.length === 0 && !onProjectsRoute) {
      router.replace("/projects/new");
    }
  }, [loading, projects.length, pathname, router]);

  const switchProject = useCallback(
    async (projectId: string) => {
      const updated = await apiPut<Project>("/api/projects/active", { project_id: projectId });
      setActiveProject(updated);
      setApiProjectId(updated.id);
      setProjects((prev) => {
        const exists = prev.some((p) => p.id === updated.id);
        if (exists) {
          return prev.map((p) => (p.id === updated.id ? { ...p, ...updated } : p));
        }
        return [...prev, updated];
      });
    },
    []
  );

  const value = useMemo(
    () => ({
      projects,
      activeProject,
      loading,
      error,
      refresh,
      switchProject,
    }),
    [projects, activeProject, loading, error, refresh, switchProject]
  );

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export function useProject() {
  const ctx = useContext(ProjectContext);
  if (!ctx) {
    throw new Error("useProject must be used within ProjectProvider");
  }
  return ctx;
}
