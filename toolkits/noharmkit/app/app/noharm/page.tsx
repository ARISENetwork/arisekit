import { redirect } from "next/navigation";

export default function NoharmIndex(): never {
  redirect("/noharm/welcome");
}
