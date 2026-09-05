import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { RepoEntry } from "../api/types";
import RepoSelector from "./RepoSelector";

function repo(overrides: Partial<RepoEntry> & { label: string; root: string }): RepoEntry {
  return { current: false, has_board: true, live_sessions: 0, ...overrides };
}

describe("<RepoSelector/>", () => {
  it("renders nothing when the repos list is empty", () => {
    const { container } = render(
      <RepoSelector repos={[]} activeRoot={null} onSelect={() => {}} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("still renders for a single discovered repo", () => {
    render(
      <RepoSelector
        repos={[repo({ label: "solo", root: "/solo", current: true })]}
        activeRoot={null}
        onSelect={() => {}}
      />
    );
    expect(screen.getByLabelText("Repo")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "solo" })).toBeInTheDocument();
  });

  it("falls back to the backend-marked current entry when activeRoot is null", () => {
    render(
      <RepoSelector
        repos={[
          repo({ label: "repo-a", root: "/a" }),
          repo({ label: "repo-b", root: "/b", current: true }),
        ]}
        activeRoot={null}
        onSelect={() => {}}
      />
    );
    expect((screen.getByLabelText("Repo") as HTMLSelectElement).value).toBe("/b");
  });

  it("falls back to the first entry when activeRoot is unknown and nothing is marked current", () => {
    render(
      <RepoSelector
        repos={[repo({ label: "repo-a", root: "/a" }), repo({ label: "repo-b", root: "/b" })]}
        activeRoot="/stale-no-longer-discovered"
        onSelect={() => {}}
      />
    );
    expect((screen.getByLabelText("Repo") as HTMLSelectElement).value).toBe("/a");
  });

  it("reflects activeRoot when it matches a discovered repo", () => {
    render(
      <RepoSelector
        repos={[
          repo({ label: "repo-a", root: "/a", current: true }),
          repo({ label: "repo-b", root: "/b" }),
        ]}
        activeRoot="/b"
        onSelect={() => {}}
      />
    );
    expect((screen.getByLabelText("Repo") as HTMLSelectElement).value).toBe("/b");
  });

  it("calls onSelect with the chosen root on change", () => {
    const onSelect = vi.fn();
    render(
      <RepoSelector
        repos={[
          repo({ label: "repo-a", root: "/a", current: true }),
          repo({ label: "repo-b", root: "/b" }),
        ]}
        activeRoot="/a"
        onSelect={onSelect}
      />
    );

    fireEvent.change(screen.getByLabelText("Repo"), { target: { value: "/b" } });

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("/b");
  });

  describe("All repos option (account-wide pages)", () => {
    it("is absent by default", () => {
      render(<RepoSelector repos={[repo({ label: "repo-a", root: "/a", current: true })]} activeRoot="/a" onSelect={() => {}} />);
      expect(screen.queryByRole("option", { name: "All repos" })).not.toBeInTheDocument();
    });

    it("leads the list, reports its own selection, and clears it when a real repo is picked", () => {
      const onSelect = vi.fn();
      const onAll = vi.fn();
      const { rerender } = render(
        <RepoSelector
          repos={[repo({ label: "repo-a", root: "/a", current: true }), repo({ label: "repo-b", root: "/b" })]}
          activeRoot="/a"
          onSelect={onSelect}
          allOption={{ selected: false, onSelect: onAll }}
        />
      );
      const options = screen.getAllByRole("option");
      expect(options[0]).toHaveTextContent("All repos");
      expect(screen.getByLabelText("Repo")).toHaveValue("/a");

      fireEvent.change(screen.getByLabelText("Repo"), { target: { value: options[0].getAttribute("value") } });
      expect(onAll).toHaveBeenCalledWith(true);
      expect(onSelect).not.toHaveBeenCalled();

      // Selected: the select shows All while activeRoot is left alone underneath.
      rerender(
        <RepoSelector
          repos={[repo({ label: "repo-a", root: "/a", current: true }), repo({ label: "repo-b", root: "/b" })]}
          activeRoot="/a"
          onSelect={onSelect}
          allOption={{ selected: true, onSelect: onAll }}
        />
      );
      expect(screen.getByLabelText("Repo")).toHaveValue(options[0].getAttribute("value"));

      fireEvent.change(screen.getByLabelText("Repo"), { target: { value: "/b" } });
      expect(onAll).toHaveBeenLastCalledWith(false);
      expect(onSelect).toHaveBeenCalledWith("/b");
    });
  });

  describe("unbegun repos (has_board: false — WF-032)", () => {
    it("renders an unbegun repo's option with the distinct class and its live-agent count hint", () => {
      render(
        <RepoSelector
          repos={[
            repo({ label: "acme", root: "/acme", current: true }),
            repo({ label: "sandbox", root: "/sandbox", has_board: false, live_sessions: 6 }),
          ]}
          activeRoot="/acme"
          onSelect={() => {}}
        />
      );

      const option = screen.getByRole("option", { name: /sandbox/i });
      expect(option).toHaveTextContent("⚔ 6");
      expect(option).toHaveClass("repo-option--unbegun");
    });

    it("does not mark a has_board:true repo's option as unbegun", () => {
      render(
        <RepoSelector
          repos={[repo({ label: "acme", root: "/acme", current: true })]}
          activeRoot="/acme"
          onSelect={() => {}}
        />
      );

      const option = screen.getByRole("option", { name: "acme" });
      expect(option).not.toHaveClass("repo-option--unbegun");
      expect(option).not.toHaveTextContent("⚔");
    });

    it("an unbegun repo's option is still selectable", () => {
      const onSelect = vi.fn();
      render(
        <RepoSelector
          repos={[
            repo({ label: "acme", root: "/acme", current: true }),
            repo({ label: "sandbox", root: "/sandbox", has_board: false, live_sessions: 6 }),
          ]}
          activeRoot="/acme"
          onSelect={onSelect}
        />
      );

      fireEvent.change(screen.getByLabelText("Repo"), { target: { value: "/sandbox" } });

      expect(onSelect).toHaveBeenCalledWith("/sandbox");
    });
  });
});
