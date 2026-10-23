import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NavigationGuard, useUnsavedNavigation } from "./NavigationGuard";
import { HISTORY_INDEX, navigate, navigateHref, parseRoute, subscribeToRoute } from "./routes";

const studio = "/projects/p/studio/r1";
function Editor() {
  const [text, setText] = useState("");
  useUnsavedNavigation(text !== "", window.location.pathname);
  return <><input aria-label="草稿" value={text} onChange={e => setText(e.target.value)} /><a href="/">作品</a><button onClick={() => navigate({name:"studio",projectId:"p",revisionId:"r2"})}>换版本</button><button onClick={() => navigateHref(`${studio}?view=mix&piano_preview=keep`)}>混音视图</button></>;
}
function Harness() {
  const [route, setRoute] = useState(parseRoute);
  useEffect(() => subscribeToRoute(setRoute), []);
  return <NavigationGuard>{route.name === "studio" ? <Editor key={route.revisionId} /> : <p>作品列表</p>}</NavigationGuard>;
}
beforeEach(() => window.history.replaceState({}, "", studio + "?piano_preview=keep"));
afterEach(() => {cleanup(); vi.restoreAllMocks(); window.history.replaceState({}, "", "/");});
const dirty = () => fireEvent.change(screen.getByLabelText("草稿"), {target:{value:"保留我的修改"}});

it("guards ordinary href and preserves draft on cancel, leaves only after explicit discard", () => {
  render(<Harness/>); dirty(); fireEvent.click(screen.getByRole("link",{name:"作品"}));
  expect(screen.getByRole("alertdialog")).toBeVisible(); expect(window.location.pathname).toBe(studio);
  fireEvent.click(screen.getByRole("button",{name:"留在此页"}));
  expect(screen.getByLabelText("草稿")).toHaveValue("保留我的修改");
  fireEvent.click(screen.getByRole("link",{name:"作品"})); fireEvent.click(screen.getByRole("button",{name:"放弃草稿并离开"}));
  expect(screen.getByText("作品列表")).toBeVisible();
});
it("guards programmatic revision navigation and uses standard close protection", () => {
  render(<Harness/>); dirty(); fireEvent.click(screen.getByText("换版本"));
  expect(window.location.pathname).toBe(studio); expect(screen.getByRole("alertdialog")).toBeVisible();
  const close = new Event("beforeunload", {cancelable:true}); window.dispatchEvent(close); expect(close.defaultPrevented).toBe(true);
  fireEvent.click(screen.getByText("放弃草稿并离开")); expect(window.location.pathname).toBe("/projects/p/studio/r2");
});
it("keeps same-revision query changes mounted with preview identity and no discard prompt", () => {
  render(<Harness/>); dirty(); fireEvent.click(screen.getByText("混音视图"));
  expect(window.location.search).toBe("?view=mix&piano_preview=keep"); expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(screen.getByLabelText("草稿")).toHaveValue("保留我的修改");
});
it("restores dirty history back then allows discard and a forward return", async () => {
  window.history.replaceState({}, "", "/"); render(<Harness/>);
  act(()=>navigate({name:"studio",projectId:"p",revisionId:"r1"})); await screen.findByLabelText("草稿"); dirty();
  window.history.back(); await screen.findByRole("alertdialog");
  await waitFor(() => expect(window.location.pathname).toBe(studio));
  fireEvent.click(screen.getByText("留在此页")); expect(screen.getByLabelText("草稿")).toHaveValue("保留我的修改");
  window.history.back(); await screen.findByRole("alertdialog"); fireEvent.click(screen.getByText("放弃草稿并离开"));
  await screen.findByText("作品列表"); window.history.forward(); await screen.findByLabelText("草稿");
  expect(window.location.pathname).toBe(studio);
});

it("also protects forward navigation from a dirty historical revision", async () => {
  render(<Harness/>);act(()=>navigate({name:"studio",projectId:"p",revisionId:"r2"}));
  window.history.back();await waitFor(()=>expect(window.location.pathname).toBe(studio));dirty();
  window.history.forward();await screen.findByRole("alertdialog");await waitFor(()=>expect(window.location.pathname).toBe(studio));
  fireEvent.click(screen.getByText("留在此页"));expect(screen.getByLabelText("草稿")).toHaveValue("保留我的修改");
});

it("waits for the restored history entry before offering discard", async () => {
  window.history.replaceState({}, "", "/");render(<Harness/>);act(()=>navigate({name:"studio",projectId:"p",revisionId:"r1"}));await screen.findByLabelText("草稿");dirty();
  const restoredState=window.history.state;
  const go=vi.spyOn(window.history,"go").mockImplementation(()=>undefined);
  window.history.replaceState({[HISTORY_INDEX]:0},"","/");
  act(()=>window.dispatchEvent(new PopStateEvent("popstate",{state:window.history.state})));
  expect(screen.queryByRole("alertdialog")).toBeNull();expect(go).toHaveBeenCalledWith(1);
  act(()=>navigateHref(studio+"?view=mix"));expect(window.location.pathname).toBe("/");expect(screen.queryByRole("alertdialog")).toBeNull();
  window.history.replaceState(restoredState,"",studio);
  act(()=>window.dispatchEvent(new PopStateEvent("popstate",{state:restoredState})));
  expect(screen.getByRole("alertdialog")).toBeVisible();fireEvent.click(screen.getByText("放弃草稿并离开"));
  expect(go).toHaveBeenLastCalledWith(-1);
});
