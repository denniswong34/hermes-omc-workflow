import Link from "next/link";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/workflows", label: "Workflows" },
  { href: "/mcp", label: "MCP Marketplace" },
  { href: "/agents", label: "Personas" },
  { href: "/memory", label: "Memory" },
  { href: "/kanban", label: "Kanban" },
  { href: "/connections", label: "Secrets" },
];

export function Nav() {
  return (
    <header
      style={{
        display: "flex",
        gap: "1.25rem",
        alignItems: "center",
        padding: "1rem 1.5rem",
        borderBottom: "1px solid #2a3344",
        background: "#0f1419",
      }}
    >
      <strong style={{ letterSpacing: "0.04em", color: "#e8eef7" }}>OMC Agentic OS</strong>
      <nav style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
        {LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            style={{ color: "#9db0c9", textDecoration: "none", fontSize: "0.95rem" }}
          >
            {l.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
