import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { BoardResponse } from "../api/types";

// Mock the SOLE api client module — no real fetch in this test.
vi.mock("../api/client", () => ({ setLabelColor: vi.fn() }));
import { setLabelColor } from "../api/client";
import LabelSettingsDialog from "./LabelSettingsDialog";

const RESPONSE = {
  board: { project: "acme", cards: [], sprints: [], quarantined: [], label_colors: {} },
  context: { pct: null, threshold: null },
  limits: null,
} as unknown as BoardResponse;

// Live mutate double, same family as NewCardDialog.test.tsx/TopBar.test.tsx.
function makeMutate() {
  return vi.fn(async (fn: () => Promise<BoardResponse>) => {
    await fn();
  });
}

function open(
  props: Partial<Parameters<typeof LabelSettingsDialog>[0]> = {}
) {
  const onClose = vi.fn();
  const mutate = props.mutate ?? makeMutate();
  render(
    <LabelSettingsDialog
      open
      onClose={onClose}
      labels={["policy", "architecture"]}
      colors={{}}
      mutate={mutate}
      {...props}
    />
  );
  return { onClose, mutate };
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("<LabelSettingsDialog/>", () => {
  it("renders nothing when closed", () => {
    render(
      <LabelSettingsDialog
        open={false}
        onClose={vi.fn()}
        labels={["policy"]}
        colors={{}}
        mutate={makeMutate()}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders a row per distinct label, each with its current chip", () => {
    open();
    expect(screen.getByRole("dialog", { name: /label colors/i })).toBeInTheDocument();
    expect(screen.getByText("policy")).toBeInTheDocument();
    expect(screen.getByText("architecture")).toBeInTheDocument();
  });

  it("renders all 9 palette swatches per label, aria-labelled '<name>: <key>'", () => {
    open({ labels: ["policy"] });
    const PALETTE_KEYS = [
      "slate", "sage", "plum", "clay", "sky", "violet", "olive", "terracotta", "teal",
    ];
    for (const key of PALETTE_KEYS) {
      expect(
        screen.getByRole("button", { name: `policy: ${key}` })
      ).toBeInTheDocument();
    }
  });

  it("shows a message when there are no labels yet", () => {
    open({ labels: [] });
    expect(screen.getByText(/no labels/i)).toBeInTheDocument();
  });

  it("picking a swatch routes setLabelColor(name, key) through mutate", async () => {
    vi.mocked(setLabelColor).mockResolvedValue(RESPONSE);
    const { mutate } = open({ labels: ["policy"] });

    fireEvent.click(screen.getByRole("button", { name: "policy: sky" }));

    await waitFor(() => expect(mutate).toHaveBeenCalledWith(expect.any(Function)));
    expect(setLabelColor).toHaveBeenCalledWith("policy", "sky");
  });

  it("Reset routes setLabelColor(name, null) through mutate", async () => {
    vi.mocked(setLabelColor).mockResolvedValue(RESPONSE);
    const { mutate } = open({ labels: ["policy"], colors: { policy: "sky" } });

    fireEvent.click(screen.getByRole("button", { name: /^reset$/i }));

    await waitFor(() => expect(mutate).toHaveBeenCalledWith(expect.any(Function)));
    expect(setLabelColor).toHaveBeenCalledWith("policy", null);
  });

  it("marks the label's current registry colour as the pressed swatch", () => {
    open({ labels: ["policy"], colors: { policy: "sky" } });
    expect(
      screen.getByRole("button", { name: "policy: sky" })
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: "policy: slate" })
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("clicking outside (the overlay) closes the dialog", () => {
    const { onClose } = open();
    fireEvent.click(screen.getByRole("dialog").parentElement!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("clicking inside the sheet does not close the dialog", () => {
    const { onClose } = open();
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("Escape closes the dialog", () => {
    const { onClose } = open();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("the close (x) button calls onClose", () => {
    const { onClose } = open();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
