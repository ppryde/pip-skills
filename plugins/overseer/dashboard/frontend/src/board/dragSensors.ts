/**
 * Sensor configuration for the board's DndContext, extracted as plain data
 * so it's testable without invoking the `useSensor`/`useSensors` hooks (which
 * require a component render). Board.tsx just maps this array through
 * `useSensor`.
 *
 * - PointerSensor gets an activation distance so a plain click (drawer-open
 *   in C5, inline controls in C6) isn't eaten as a drag start.
 * - KeyboardSensor is registered for a11y — the documented reason @dnd-kit
 *   was chosen over alternatives (see wf005-context.md).
 */
import { KeyboardSensor, PointerSensor } from "@dnd-kit/core";
import type { SensorDescriptor, SensorOptions } from "@dnd-kit/core";

export const DRAG_SENSOR_DESCRIPTORS: Array<{
  sensor: SensorDescriptor<SensorOptions>["sensor"];
  options: { activationConstraint?: { distance: number } };
}> = [
  { sensor: PointerSensor, options: { activationConstraint: { distance: 8 } } },
  { sensor: KeyboardSensor, options: {} },
];
