import { notFound } from "next/navigation";

import Dashboard from "@/components/mc/Dashboard";
import { getCurrent } from "@/lib/caseset/current";

export const dynamic = "force-dynamic";

export default async function DashboardPage(): Promise<React.ReactNode> {
  const current = await getCurrent();
  if (!current) notFound();
  return <Dashboard bench={current.bench} exampleProject={current.names.find((name) => name.toLowerCase() === "demo")} />;
}
