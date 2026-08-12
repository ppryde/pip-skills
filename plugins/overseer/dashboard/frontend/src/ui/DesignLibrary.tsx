import { useState } from "react";
import Button from "./Button";
import Select from "./Select";
import Chip from "./Chip";
import Input, { Textarea } from "./Input";
import Label from "./Label";

/**
 * Design library showcase (v1, WF-097) — a "kitchen sink" page rendering
 * every `src/ui/` primitive in each of its states, grouped under headings.
 * Reachable at the `#design` hash (see App.tsx's hashchange wiring) rather
 * than through a router — this is a diagnostic/reference page, not a real
 * app route, so a plain hash check is enough and adds no new dependency.
 *
 * Each primitive here is a thin wrapper around a `.qb-*` class documented
 * in styles.css's "Design library" section — this page exists to make that
 * documentation visible and interactive, not to add any new look of its
 * own. The raw `.qb-btn` markup at the end of the Buttons group is included
 * deliberately, so the wrapped and unwrapped forms can be compared side by
 * side.
 */
function DesignLibrary() {
  const [text, setText] = useState("");
  const [notes, setNotes] = useState("");
  const [choice, setChoice] = useState("a");

  return (
    <div className="design-library">
      <header>
        <h1>Quest Board — Design Library</h1>
        <p>
          A rudimentary v1 catalogue of the shared <code>.qb-*</code>{" "}
          primitives (see styles.css&apos;s &quot;Design library&quot;
          section) and their typed React wrappers in <code>src/ui/</code>.
          Reach this page any time via the <code>#design</code> hash;
          clearing the hash (or pressing Back) returns to the normal board.
        </p>
      </header>

      <section>
        <h2>Buttons</h2>
        <p>
          <code>&lt;Button/&gt;</code> wraps the Role-A <code>.qb-btn</code>{" "}
          / <code>.qb-btn--primary</code> recipe already used across the
          topbar, filter bar, and — as of this v1 — the card drawer&apos;s
          Save/Cancel/Edit/Pull-children controls.
        </p>
        <div className="design-library__row">
          <Button variant="primary">Primary</Button>
          <Button variant="neutral">Neutral</Button>
          <Button>Default (neutral)</Button>
          <Button disabled>Disabled</Button>
          <button type="button" className="qb-btn">
            Raw .qb-btn, unwrapped
          </button>
        </div>
      </section>

      <section>
        <h2>Selects</h2>
        <p>
          <code>&lt;Select/&gt;</code> wraps <code>.qb-select</code>,
          factored from the topbar&apos;s repo/branch selects and the filter
          bar&apos;s priority/complexity dropdowns.
        </p>
        <div className="design-library__row">
          <Select
            label="Example choice"
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
          >
            <option value="a">Option A</option>
            <option value="b">Option B</option>
            <option value="c">Option C</option>
          </Select>
          <Select aria-label="Disabled example choice" disabled>
            <option>Disabled</option>
          </Select>
        </div>
      </section>

      <section>
        <h2>Chips</h2>
        <p>
          <code>&lt;Chip/&gt;</code> wraps <code>.qb-chip</code>, factored
          from the topbar&apos;s torn-note pills (last-refreshed time, rest
          windows). A <code>tone</code> prop (the curated label-palette key
          from <code>board/labelColor.ts</code>) layers a
          <code>.label-chip--&lt;key&gt;</code> colour on top — the same
          chips a card&apos;s <code>label</code>s render as, via
          <code>LabelChips</code>/<code>LabelEditor</code>/
          <code>LabelSettingsDialog</code>&apos;s own
          <code>className=&quot;label-chip&quot;</code> for the hand-drawn
          wobble shape.
        </p>
        <div className="design-library__row">
          <Chip>last refreshed 2m ago</Chip>
          <Chip>7d window</Chip>
          <Chip tone="sky" className="label-chip">
            ui
          </Chip>
          <Chip tone="terracotta" className="label-chip">
            architecture
          </Chip>
        </div>
      </section>

      <section>
        <h2>Inputs</h2>
        <p>
          <code>&lt;Input/&gt;</code> and <code>&lt;Textarea/&gt;</code> both
          wrap <code>.qb-input</code>, factored from the filter bar&apos;s
          search box and the card drawer&apos;s title/body edit fields.
        </p>
        <div className="design-library__col">
          <Input
            aria-label="Example text input"
            placeholder="Search…"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <Textarea
            aria-label="Example textarea"
            placeholder="Notes…"
            rows={4}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
      </section>

      <section>
        <h2>Labels</h2>
        <p>
          <code>&lt;Label/&gt;</code> wraps <code>.qb-label</code>, the small
          uppercase eyebrow used for the topbar&apos;s &quot;repo&quot;/
          &quot;branch&quot; captions and the filter bar&apos;s &quot;Scry&quot;
          eyebrow.
        </p>
        <div className="design-library__row">
          <Label>eyebrow label</Label>
          <Label>another eyebrow</Label>
        </div>
      </section>
    </div>
  );
}

export default DesignLibrary;
