import Link from "next/link";
import kits from "../../../../../docs/kits-data.json";

export const metadata = { title: "Local kits | ARISEKit" };

export default function KitsPage(): React.ReactElement {
  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-12">
      <h1 className="mb-8 text-3xl font-semibold">Local benchmark kits</h1>
      <section className="mb-8 rounded-lg border p-5">
        <h2 className="text-xl font-semibold">NOHARMKit</h2>
        <p className="my-3">Build and score open-ended clinical management benchmarks in the local workspace.</p>
        <Link className="underline" href="/noharm/welcome">Open NOHARMKit</Link>
      </section>
      <h2 className="text-xl font-semibold">Guided authoring</h2>
      <p className="my-3">Open this checkout in your coding agent and use the prompt for your task.</p>
      <ul className="divide-y rounded-lg border px-5">
        {kits.map(kit => (
          <li key={kit.id} className="py-4">
            <details>
              <summary className="cursor-pointer font-semibold">{kit.name} · {kit.task}</summary>
              <p className="my-3">{kit.capability}</p>
              <p className="mb-2 select-all rounded-md border p-3">{kit.prompt}</p>
            </details>
          </li>
        ))}
      </ul>
    </main>
  );
}
