import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PortfolioPage } from "./PortfolioPage";

describe("PortfolioPage", () => {
  it("explains the agentic product loop and links to evidence", () => {
    render(<PortfolioPage />);

    expect(screen.getByRole("heading", { name: /Brief 到可编辑作品/ })).toBeInTheDocument();
    expect(screen.getByText("LangGraph Parent Graph")).toBeInTheDocument();
    expect(screen.getByText("Human approval gate")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看 Eval 证据" })).toBeInTheDocument();
  });
});
