import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { RepoEntry } from "../api/types";
import RepoSelector from "./RepoSelector";

function repo(overrides: Partial<RepoEntry> & { label: string; root: string }): RepoEntry {
  return { current: false, ...overrides };
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
});
