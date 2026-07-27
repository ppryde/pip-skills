import { describe, expect, it } from "vitest";
import { KeyboardSensor, PointerSensor, TouchSensor } from "@dnd-kit/core";
import { DRAG_SENSOR_DESCRIPTORS } from "./dragSensors";

describe("DRAG_SENSOR_DESCRIPTORS", () => {
  it("registers a KeyboardSensor (a11y — the reason @dnd-kit was chosen)", () => {
    expect(DRAG_SENSOR_DESCRIPTORS.some((d) => d.sensor === KeyboardSensor)).toBe(
      true
    );
  });

  it("registers a PointerSensor with an activation distance (so a plain click isn't eaten as a drag)", () => {
    const pointerDescriptor = DRAG_SENSOR_DESCRIPTORS.find(
      (d) => d.sensor === PointerSensor
    );
    expect(pointerDescriptor).toBeDefined();
    expect(
      pointerDescriptor?.options.activationConstraint?.distance
    ).toBeGreaterThan(0);
  });

  it("registers a TouchSensor with a long-press delay + tolerance (so touch drag works without hijacking scroll)", () => {
    const touchDescriptor = DRAG_SENSOR_DESCRIPTORS.find(
      (d) => d.sensor === TouchSensor
    );
    expect(touchDescriptor).toBeDefined();
    expect(
      touchDescriptor?.options.activationConstraint?.delay
    ).toBeGreaterThan(0);
    expect(
      touchDescriptor?.options.activationConstraint?.tolerance
    ).toBeGreaterThan(0);
  });
});
