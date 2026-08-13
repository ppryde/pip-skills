import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import LabelEditor from "./LabelEditor";
import { labelColor } from "../board/labelColor";

describe("<LabelEditor/>", () => {
  it("renders a chip for each existing label", () => {
    render(<LabelEditor labels={["policy", "arch"]} onSave={vi.fn()} />);
    expect(screen.getByText("policy")).toBeInTheDocument();
    expect(screen.getByText("arch")).toBeInTheDocument();
  });

  it("adds a label and calls onSave with the full set", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<LabelEditor labels={["policy"]} onSave={onSave} />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "arch" },
    });
    fireEvent.keyDown(screen.getByRole("textbox"), {
      key: "Enter",
    });
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(["policy", "arch"])
    );
  });

  it("removes a label and calls onSave without it", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<LabelEditor labels={["policy", "arch"]} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: /remove policy/i }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(["arch"]));
  });

  it("clears the add-input after committing", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<LabelEditor labels={[]} onSave={onSave} />);
    const input = screen.getByRole("textbox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "arch" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(["arch"]));
    expect(input.value).toBe("");
  });

  it("does NOT call onSave for a whitespace-only add (no-op)", () => {
    const onSave = vi.fn();
    render(<LabelEditor labels={["policy"]} onSave={onSave} />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).not.toHaveBeenCalled();
  });

  it("does NOT call onSave for an empty add (no-op)", () => {
    const onSave = vi.fn();
    render(<LabelEditor labels={["policy"]} onSave={onSave} />);
    fireEvent.keyDown(screen.getByRole("textbox"), {
      key: "Enter",
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it("does NOT add a duplicate label (no-op, no onSave call)", () => {
    const onSave = vi.fn();
    render(<LabelEditor labels={["policy"]} onSave={onSave} />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "policy" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).not.toHaveBeenCalled();
    // Still exactly one "policy" chip — nothing duplicated in the DOM either.
    expect(screen.getAllByText("policy")).toHaveLength(1);
  });

  it("trims surrounding whitespace off an added label", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<LabelEditor labels={[]} onSave={onSave} />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "  arch  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(["arch"]));
  });

  it("colours a chip from the F10 registry when the label has an entry (WF-067)", () => {
    const hashKey = labelColor("policy");
    const overrideKey = (
      ["slate", "sage", "plum", "clay", "sky", "violet", "olive", "terracotta", "teal"] as const
    ).find((k) => k !== hashKey)!;
    const { container } = render(
      <LabelEditor
        labels={["policy"]}
        onSave={vi.fn()}
        colorRegistry={{ policy: overrideKey }}
      />
    );
    const chip = container.querySelector(".label-editor__chip")!;
    expect(chip.className).toContain(`label-chip--${overrideKey}`);
  });
});
