import { SignIn } from "@/components/sign-in";
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  return <SignIn callbackError={error === "callback"} />;
}
