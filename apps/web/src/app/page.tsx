import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { sessionCookie } from "@/lib/server";
import { Workspace } from "@/components/workspace";
export default async function Page() {
  if (!(await cookies()).get(sessionCookie)) redirect("/sign-in");
  return <Workspace />;
}
