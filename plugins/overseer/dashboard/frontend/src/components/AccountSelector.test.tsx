import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import AccountSelector from "./AccountSelector";
import type { AccountEntry } from "../api/types";

function account(overrides: Partial<AccountEntry> & { account_uuid: string }): AccountEntry {
  return {
    short_uuid: overrides.account_uuid.slice(0, 8),
    plan: null,
    config_dirs: [],
    sessions: 0,
    last_activity_at: null,
    ...overrides,
  };
}

describe("<AccountSelector/>", () => {
  it("renders nothing with fewer than two accounts", () => {
    const { container: empty } = render(
      <AccountSelector accounts={[]} activeAccount={null} onSelect={() => {}} />
    );
    expect(empty).toBeEmptyDOMElement();

    const { container: one } = render(
      <AccountSelector
        accounts={[account({ account_uuid: "11111111-aaaa" })]}
        activeAccount={null}
        onSelect={() => {}}
      />
    );
    expect(one).toBeEmptyDOMElement();
  });

  it("renders an 'All accounts' option plus one per account, labelled by plan and short uuid", () => {
    render(
      <AccountSelector
        accounts={[
          account({ account_uuid: "11111111-aaaa", plan: "claude_max" }),
          account({ account_uuid: "22222222-bbbb" }),
        ]}
        activeAccount={null}
        onSelect={() => {}}
      />
    );
    expect(screen.getByLabelText("Account")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "All accounts" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Max · 11111111" })).toBeInTheDocument();
    // No live plan (chronicle-history-only uuid, WF-116): the short uuid alone.
    expect(screen.getByRole("option", { name: "22222222" })).toBeInTheDocument();
  });

  it("defaults the select to 'All accounts' when activeAccount is null", () => {
    render(
      <AccountSelector
        accounts={[
          account({ account_uuid: "11111111-aaaa" }),
          account({ account_uuid: "22222222-bbbb" }),
        ]}
        activeAccount={null}
        onSelect={() => {}}
      />
    );
    expect((screen.getByLabelText("Account") as HTMLSelectElement).value).toBe("");
  });

  it("reflects activeAccount when it's a known account", () => {
    render(
      <AccountSelector
        accounts={[
          account({ account_uuid: "11111111-aaaa" }),
          account({ account_uuid: "22222222-bbbb" }),
        ]}
        activeAccount="22222222-bbbb"
        onSelect={() => {}}
      />
    );
    expect((screen.getByLabelText("Account") as HTMLSelectElement).value).toBe(
      "22222222-bbbb"
    );
  });

  it("falls back to 'All accounts' when activeAccount names an account no longer listed", () => {
    render(
      <AccountSelector
        accounts={[
          account({ account_uuid: "11111111-aaaa" }),
          account({ account_uuid: "22222222-bbbb" }),
        ]}
        activeAccount="stale-uuid"
        onSelect={() => {}}
      />
    );
    expect((screen.getByLabelText("Account") as HTMLSelectElement).value).toBe("");
  });

  it("calls onSelect with the chosen account uuid on change", () => {
    const onSelect = vi.fn();
    render(
      <AccountSelector
        accounts={[
          account({ account_uuid: "11111111-aaaa" }),
          account({ account_uuid: "22222222-bbbb" }),
        ]}
        activeAccount={null}
        onSelect={onSelect}
      />
    );

    fireEvent.change(screen.getByLabelText("Account"), {
      target: { value: "22222222-bbbb" },
    });

    expect(onSelect).toHaveBeenCalledWith("22222222-bbbb");
  });

  it("calls onSelect(null) when 'All accounts' is chosen", () => {
    const onSelect = vi.fn();
    render(
      <AccountSelector
        accounts={[
          account({ account_uuid: "11111111-aaaa" }),
          account({ account_uuid: "22222222-bbbb" }),
        ]}
        activeAccount="11111111-aaaa"
        onSelect={onSelect}
      />
    );

    fireEvent.change(screen.getByLabelText("Account"), {
      target: { value: "" },
    });

    expect(onSelect).toHaveBeenCalledWith(null);
  });
});
