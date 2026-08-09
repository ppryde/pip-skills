import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../api/client", () => ({ clearRepo: vi.fn() }));
import { clearRepo } from "../api/client";
import ClearDialog from "./ClearDialog";

const CLEARED = {
  scope: "repo",
  backup_path: "/tmp/snap",
  removed: {},
  label: "demo",
  noop: false,
};

function open() {
  const onClose = vi.fn();
  const onCleared = vi.fn();
  render(
    <ClearDialog
      repoLabel="demo"
      repoRoot="/repos/demo"
      cardCount={3}
      onClose={onClose}
      onCleared={onCleared}
    />
  );
  return { onClose, onCleared };
}

afterEach(() => vi.restoreAllMocks());

describe("<ClearDialog/>", () => {
  it("shows step 1 with the card count and a Press on button", () => {
    open();
    expect(screen.getByText(/Dragons be here/i)).toBeInTheDocument();
    expect(screen.getByText(/3/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /press on/i })
    ).toBeInTheDocument();
  });

  it("the final Slay it button is disabled until the repo label is typed exactly", () => {
    open();
    fireEvent.click(screen.getByRole("button", { name: /press on/i }));
    const slay = screen.getByRole("button", { name: /slay it/i });
    expect(slay).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/type the repo label/i), {
      target: { value: "wrong" },
    });
    expect(slay).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/type the repo label/i), {
      target: { value: "demo" },
    });
    expect(slay).toBeEnabled();
  });

  it("Slay it calls clearRepo with the selected scope then onCleared", async () => {
    vi.mocked(clearRepo).mockResolvedValue(CLEARED as never);
    const { onCleared } = open();
    fireEvent.click(screen.getByRole("button", { name: /press on/i }));
    fireEvent.change(screen.getByLabelText(/type the repo label/i), {
      target: { value: "demo" },
    });
    fireEvent.click(screen.getByRole("button", { name: /slay it/i }));
    await waitFor(() =>
      expect(clearRepo).toHaveBeenCalledWith("/repos/demo", "repo")
    );
    await waitFor(() => expect(onCleared).toHaveBeenCalledWith(CLEARED));
  });

  it("Slay it calls clearRepo with the cards scope when selected", async () => {
    vi.mocked(clearRepo).mockResolvedValue({
      ...CLEARED,
      scope: "cards",
    } as never);
    const { onCleared } = open();
    fireEvent.click(
      screen.getByRole("radio", { name: /cards only/i })
    );
    fireEvent.click(screen.getByRole("button", { name: /press on/i }));
    fireEvent.change(screen.getByLabelText(/type the repo label/i), {
      target: { value: "demo" },
    });
    fireEvent.click(screen.getByRole("button", { name: /slay it/i }));
    await waitFor(() =>
      expect(clearRepo).toHaveBeenCalledWith("/repos/demo", "cards")
    );
    await waitFor(() => expect(onCleared).toHaveBeenCalled());
  });

  it("Turn back closes without calling clearRepo", () => {
    const { onClose } = open();
    fireEvent.click(screen.getByRole("button", { name: /turn back/i }));
    expect(onClose).toHaveBeenCalled();
    expect(clearRepo).not.toHaveBeenCalled();
  });

  it("Back on step 2 returns to step 1 without calling clearRepo", () => {
    open();
    fireEvent.click(screen.getByRole("button", { name: /press on/i }));
    fireEvent.click(screen.getByRole("button", { name: /^back$/i }));
    expect(screen.getByText(/Dragons be here/i)).toBeInTheDocument();
    expect(clearRepo).not.toHaveBeenCalled();
  });

  it("shows an inline error and stays open when clearRepo rejects", async () => {
    vi.mocked(clearRepo).mockRejectedValue(new Error("boom"));
    const { onClose, onCleared } = open();
    fireEvent.click(screen.getByRole("button", { name: /press on/i }));
    fireEvent.change(screen.getByLabelText(/type the repo label/i), {
      target: { value: "demo" },
    });
    fireEvent.click(screen.getByRole("button", { name: /slay it/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/boom/i));
    expect(onClose).not.toHaveBeenCalled();
    expect(onCleared).not.toHaveBeenCalled();
  });

  it("Escape closes the dialog", () => {
    const { onClose } = open();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});
