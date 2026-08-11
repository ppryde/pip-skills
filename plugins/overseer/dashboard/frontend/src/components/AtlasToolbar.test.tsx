import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import AtlasToolbar from "./AtlasToolbar";

describe("<AtlasToolbar/>", () => {
  it("renders the static complexity-weight label with no toggle beside it", () => {
    render(
      <AtlasToolbar
        showNames
        onToggleNames={vi.fn()}
        hideVanquished
        onToggleVanquished={vi.fn()}
        orientation="across"
        onToggleOrientation={vi.fn()}
      />
    );
    expect(screen.getByText("Trail segments weighed by complexity ★")).toBeInTheDocument();
  });

  it("quest-names toggle defaults reflect the showNames prop and call onToggleNames on click", () => {
    const onToggleNames = vi.fn();
    render(
      <AtlasToolbar
        showNames
        onToggleNames={onToggleNames}
        hideVanquished
        onToggleVanquished={vi.fn()}
        orientation="across"
        onToggleOrientation={vi.fn()}
      />
    );
    const onBtn = screen.getByRole("tab", { name: /name the quests/i });
    const offBtn = screen.getByRole("tab", { name: /hush/i });
    expect(onBtn).toHaveAttribute("aria-pressed", "true");
    expect(offBtn).toHaveAttribute("aria-pressed", "false");
    offBtn.click();
    expect(onToggleNames).toHaveBeenCalledWith(false);
  });

  it("vanquished toggle defaults to Hide and calls onToggleVanquished on click", () => {
    const onToggleVanquished = vi.fn();
    render(
      <AtlasToolbar
        showNames
        onToggleNames={vi.fn()}
        hideVanquished
        onToggleVanquished={onToggleVanquished}
        orientation="across"
        onToggleOrientation={vi.fn()}
      />
    );
    const showBtn = screen.getByRole("tab", { name: /show/i });
    const hideBtn = screen.getByRole("tab", { name: /hide/i });
    expect(hideBtn).toHaveAttribute("aria-pressed", "true");
    expect(showBtn).toHaveAttribute("aria-pressed", "false");
    showBtn.click();
    expect(onToggleVanquished).toHaveBeenCalledWith(false);
  });

  it("mobile orientation toggle calls onToggleOrientation with the clicked value", () => {
    const onToggleOrientation = vi.fn();
    render(
      <AtlasToolbar
        showNames
        onToggleNames={vi.fn()}
        hideVanquished
        onToggleVanquished={vi.fn()}
        orientation="across"
        onToggleOrientation={onToggleOrientation}
      />
    );
    const downBtn = screen.getByRole("tab", { name: /down/i });
    downBtn.click();
    expect(onToggleOrientation).toHaveBeenCalledWith("down");
  });
});
