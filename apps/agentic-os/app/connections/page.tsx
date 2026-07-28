import { redirect } from "next/navigation";

/** Secrets UI moved into workflow chat/ticket connection dialogs. */
export default function ConnectionsPage() {
  redirect("/workflows");
}
