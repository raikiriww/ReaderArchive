import { createFileRoute } from "@tanstack/react-router";
import { MainApp } from "../App";

export const Route = createFileRoute("/")({
  component: MainApp,
});
