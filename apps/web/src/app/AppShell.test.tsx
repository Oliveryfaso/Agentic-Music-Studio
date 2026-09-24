import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AppShell } from "./AppShell";

afterEach(() => { cleanup(); window.history.replaceState({}, "", "/"); });

it("keeps creation pages in the workspace navigation and exposes a keyboard skip target", () => {
  window.history.replaceState({}, "", "/projects/demo/new-composition");
  render(<AppShell><h1>创作</h1></AppShell>);
  expect(screen.getByRole("link", { name: "作品" })).toHaveAttribute("aria-current", "page");
  const skip = screen.getByRole("link", { name: "跳至正文" });
  expect(skip).toHaveAttribute("href", "#main-content");
  expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
});

it("identifies the evaluation destination without marking the workspace active", () => {
  window.history.replaceState({}, "", "/evaluation");
  render(<AppShell><h1>评估</h1></AppShell>);
  expect(screen.getByRole("link", { name: "评估" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("link", { name: "作品" })).not.toHaveAttribute("aria-current");
});
