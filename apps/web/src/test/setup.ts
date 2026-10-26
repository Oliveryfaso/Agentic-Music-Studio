import "@testing-library/jest-dom/vitest";

// jsdom has no viewport scrolling; the browser smoke checks the actual geometry.
Object.defineProperty(window, "scrollTo", { configurable: true, value: () => {} });

Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
  configurable: true,
  value: () => null,
});
