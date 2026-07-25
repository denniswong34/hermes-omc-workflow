/**
 * Client-side preview of agent message layouts.
 * Keep in sync with core/chat_messages.py formats.
 */

export type MessageFormatId = "block" | "card" | "quote" | "sections";

const SAMPLE_BODY =
  "Scoped passwordless magic-link login for mobile.\nPriority P0. Ready for SA design.";

export function normalizeMessageFormat(value?: string | null): MessageFormatId {
  const v = (value || "").trim().toLowerCase();
  if (v === "block" || v === "card" || v === "quote" || v === "sections") return v;
  return "card";
}

export function previewProcessing(fmt: MessageFormatId, role = "PM"): string {
  const roleU = role.toUpperCase();
  if (fmt === "block") {
    return [
      "━━━━━━━━━━━━━━━━━━━━",
      `AGENT  ${roleU} · working…`,
      "━━━━━━━━━━━━━━━━━━━━",
    ].join("\n");
  }
  if (fmt === "quote") return `🗣️ **${roleU}** working…`;
  if (fmt === "sections") {
    return [
      "==============================",
      `RESPONSE · ${roleU}`,
      "STATUS   working…",
      "==============================",
    ].join("\n");
  }
  return [
    "╔══════════════════════════════════",
    `║  ${roleU}  ·  working…`,
    "╚══════════════════════════════════",
  ].join("\n");
}

export function previewReply(fmt: MessageFormatId, role = "PM"): string {
  const roleU = role.toUpperCase();
  const body = SAMPLE_BODY;
  if (fmt === "block") {
    return [
      "━━━━━━━━━━━━━━━━━━━━",
      `AGENT  ${roleU}`,
      "TASK-015 · #engineering",
      "━━━━━━━━━━━━━━━━━━━━",
      "",
      body,
      "",
      "Ticket: https://example.atlassian.net/browse/HOAO-5",
      "Status: todo",
      "",
      "━━━━━━━━━━━━━━━━━━━━",
      "next: @SA",
      "━━━━━━━━━━━━━━━━━━━━",
    ].join("\n");
  }
  if (fmt === "quote") {
    const quoted = body
      .split("\n")
      .map((ln) => (ln.trim() ? `> ${ln}` : ">"))
      .join("\n");
    return [
      `🗣️ **${roleU}** said:`,
      quoted,
      "🎫 TASK-015 · https://example.atlassian.net/browse/HOAO-5",
      "Status: todo",
      "────────────────────",
      "📬 Asking **@SA** next",
    ].join("\n");
  }
  if (fmt === "sections") {
    return [
      "==============================",
      `RESPONSE · ${roleU}`,
      "STATUS   todo",
      "TICKET   TASK-015 / https://example.atlassian.net/browse/HOAO-5",
      "TOPIC    #engineering",
      "==============================",
      "",
      body,
      "",
      "==============================",
      "HANDOFF → @SA",
      "==============================",
    ].join("\n");
  }
  return [
    "╔══════════════════════════════════",
    `║  ${roleU}  ·  reply  ·  TASK-015`,
    "╚══════════════════════════════════",
    body,
    "",
    "Ticket: https://example.atlassian.net/browse/HOAO-5",
    "Status: todo",
    "",
    "── handoff ───────────────────────",
    "→ @SA",
  ].join("\n");
}

export function previewHandoff(fmt: MessageFormatId): string {
  const body = "@SA: Please draft the magic-link login API design (TASK-015).";
  if (fmt === "block") {
    return [
      "━━━━━━━━━━━━━━━━━━━━",
      "AGENT  PM → SA  (depth:1)",
      "━━━━━━━━━━━━━━━━━━━━",
      "",
      body,
    ].join("\n");
  }
  if (fmt === "quote") {
    return ["🔁 **PM → SA**", "────────────────────", body].join("\n");
  }
  if (fmt === "sections") {
    return [
      "==============================",
      "HANDOFF · PM → SA",
      "DEPTH    1",
      "==============================",
      "",
      body,
    ].join("\n");
  }
  return [
    "╔══════════════════════════════════",
    "║  PM → SA  ·  handoff  ·  d1",
    "╚══════════════════════════════════",
    body,
  ].join("\n");
}

export type FormatPreviewParts = {
  processing: string;
  reply: string;
  handoff: string;
};

export function buildFormatPreview(fmtRaw?: string | null): FormatPreviewParts {
  const fmt = normalizeMessageFormat(fmtRaw);
  return {
    processing: previewProcessing(fmt),
    reply: previewReply(fmt),
    handoff: previewHandoff(fmt),
  };
}
