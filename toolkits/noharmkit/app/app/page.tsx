import { redirect } from "next/navigation";

export const metadata = { title: "ARISEKit" };

export default function Home(): React.ReactNode {
  redirect("/kits");
}
