import { createFileRoute } from "@tanstack/react-router";
import { LoginRoute } from "../App";

export const Route = createFileRoute("/login")({
  component: LoginRoute,
});
