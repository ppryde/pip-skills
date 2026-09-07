import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SubagentDrawer, { agentLabel, shortAgent } from "./SubagentDrawer";
import * as client from "../../api/client";
import type { ChronicleAgentDetail, ChronicleSubagent } from "../../api/types";

vi.mock("../../api/client");
const mocked = vi.mocked(client);

function agent(overrides: Partial<ChronicleSubagent> & { agent_id: string }): ChronicleSubagent {
  return {
    turns: 10, context_tokens: 1000, output_tokens: 500, tool_calls: 4,
    first_ts: 1_788_256_800, last_ts: 1_788_260_400,
    task: null, agent_type: "general-purpose",
    ...overrides,
  };
}

function detail(overrides: Partial<ChronicleAgentDetail> = {}): ChronicleAgentDetail {
  return {
    session_id: "s1", agent_id: "a11111111aaaa", task: "Find the auth flow",
    agent_type: "Explore", turns: 10, context_tokens: 1000, input_tokens: 10,
    cache_read_tokens: 900, cache_creation_tokens: 90, output_tokens: 500,
    thinking_tokens: 20, tool_calls: 4, peak_context_tokens: 900,
    first_ts: 1_788_256_800, last_ts: 1_788_260_400, duration_s: 3600,
    cache_hit_rate: 0.9, cost_usd: 0.42, unpriced_turns: 0,
    turn_series: [], tools: [], artifacts: [],
    ...overrides,
  };
}

const AGENTS = [
  agent({ agent_id: "a11111111aaaa", task: "Find the auth flow", agent_type: "Explore" }),
  agent({ agent_id: "a22222222bbbb", task: "Audit the ORM", turns: 4 }),
  agent({ agent_id: "a33333333cccc" }),
];

function renderDrawer(props: Partial<React.ComponentProps<typeof SubagentDrawer>> = {}) {
  const onSelect = vi.fn();
  const onBack = vi.fn();
  const view = render(
    <SubagentDrawer
      sessionId="s1"
      agents={AGENTS}
      agentId="a11111111aaaa"
      onSelect={onSelect}
      onBack={onBack}
      sessionLabel="Fix the widget"
      {...props}
    />,
  );
  return { ...view, onSelect, onBack };
}

describe("agentLabel", () => {
  it("names an agent by the task it was handed", () => {
    expect(agentLabel(AGENTS[0])).toBe("Find the auth flow");
  });

  it("falls back to the id rather than inventing a name", () => {
    // An agent whose opening prompt was pruned has no label. Showing its id
    // says "unnamed"; anything else would be a fabricated summary.
    expect(agentLabel(AGENTS[2])).toBe("33333333");
    expect(shortAgent("a33333333cccc")).toBe("33333333");
  });
});

describe("<SubagentDrawer/>", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocked.getChronicleAgent.mockResolvedValue(detail());
  });

  it("lists every agent of the session in the rail, by task", async () => {
    renderDrawer();
    const rail = within(screen.getByRole("navigation", { name: "Subagents" }));
    expect(rail.getByText("3 subagents")).toBeInTheDocument();
    expect(rail.getByText("Find the auth flow")).toBeInTheDocument();
    expect(rail.getByText("Audit the ORM")).toBeInTheDocument();
    expect(rail.getByText("33333333")).toBeInTheDocument();
  });

  it("marks which agent is open", () => {
    renderDrawer();
    const rail = within(screen.getByRole("navigation", { name: "Subagents" }));
    const open = rail.getByText("Find the auth flow").closest("button");
    const other = rail.getByText("Audit the ORM").closest("button");
    expect(open).toHaveAttribute("aria-current", "true");
    expect(other).not.toHaveAttribute("aria-current");
  });

  it("fetches only the agent whose drawer is open", async () => {
    renderDrawer();
    await waitFor(() => expect(mocked.getChronicleAgent).toHaveBeenCalledWith("s1", "a11111111aaaa"));
    expect(mocked.getChronicleAgent).toHaveBeenCalledTimes(1);
  });

  it("moves between agents without leaving the layer", () => {
    const { onSelect, onBack } = renderDrawer();
    fireEvent.click(screen.getByText("Audit the ORM"));
    expect(onSelect).toHaveBeenCalledWith("a22222222bbbb");
    expect(onBack).not.toHaveBeenCalled();
  });

  it("goes back to the session it belongs to", () => {
    const { onBack } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: /Fix the widget/ }));
    expect(onBack).toHaveBeenCalled();
  });

  it("closes on Escape and on the backdrop", () => {
    const { onBack } = renderDrawer();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onBack).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("subagent-drawer-overlay"));
    expect(onBack).toHaveBeenCalledTimes(2);
  });

  it("does not close when the sheet itself is clicked", () => {
    const { onBack } = renderDrawer();
    fireEvent.click(screen.getByRole("dialog"));
    expect(onBack).not.toHaveBeenCalled();
  });

  it("shows the agent's own figures, not the session's", async () => {
    const { container } = renderDrawer();
    await waitFor(() => expect(screen.getByText("Find the auth flow", { selector: "h2" }))
      .toBeInTheDocument());
    // Scoped to the pane: the rail beside it also names types and tasks.
    const pane = within(container.querySelector(".chr-drawer__pane") as HTMLElement);
    expect(pane.getByText("Explore")).toBeInTheDocument();
    expect(pane.getByText("$0.42")).toBeInTheDocument();
    expect(pane.getByText("a11111111aaaa")).toBeInTheDocument();
  });

  it("renders an untrusted task as text, never as markup", async () => {
    mocked.getChronicleAgent.mockResolvedValue(
      detail({ task: "<img src=x onerror=alert(1)> do the thing" }));
    const { container } = renderDrawer();
    await waitFor(() => expect(
      screen.getByText(/do the thing/, { selector: "h2" })).toBeInTheDocument());
    // The transcript is not a trusted author: its text is a text node.
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows churn only when the agent actually edited something", async () => {
    mocked.getChronicleAgent.mockResolvedValue(detail({
      churn: { lines_added: 120, lines_removed: 8, files: 3, edits: 9,
               files_by_churn: [], sessions: 1, output_tokens: 0, by_day: [] },
    }));
    renderDrawer();
    await waitFor(() => expect(screen.getByText("+120 / -8")).toBeInTheDocument());
    expect(screen.getByText("Files touched")).toBeInTheDocument();
  });

  it("omits the churn tiles for an agent that only read", async () => {
    renderDrawer();
    await waitFor(() => expect(screen.getByText("Turns")).toBeInTheDocument());
    expect(screen.queryByText("Files touched")).not.toBeInTheDocument();
  });

  it("surfaces a failed fetch rather than an empty drawer", async () => {
    mocked.getChronicleAgent.mockRejectedValue(new Error("gone"));
    renderDrawer();
    await waitFor(() => expect(screen.getByText("gone")).toBeInTheDocument());
    // The rail still works, so the reader can pick another agent or go back.
    expect(screen.getByText("Audit the ORM")).toBeInTheDocument();
  });
});
