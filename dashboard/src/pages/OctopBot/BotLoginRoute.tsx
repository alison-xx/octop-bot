import { lazy, Suspense } from "react";
import BrandLoading from "../../components/BrandLoading";

const Login = lazy(() => import("./BotLogin"));

/** Bot web build sign-in, outside the authenticated Bot client shell. */
export default function BotLoginRoute() {
  return (
    <Suspense fallback={<BrandLoading viewport />}>
      <Login />
    </Suspense>
  );
}
