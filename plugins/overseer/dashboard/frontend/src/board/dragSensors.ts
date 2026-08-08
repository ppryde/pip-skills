/**
 * Sensor configuration for the board's DndContext, extracted as plain data
 * so it's testable without invoking the `useSensor`/`useSensors` hooks (which
 * require a component render). Board.tsx just maps this array through
 * `useSensor`.
 *
 * - PointerSensor gets an activation distance so a plain click (drawer-open
 *   in C5, inline controls in C6) isn't eaten as a drag start.
 * - TouchSensor gets a long-press activation (delay + tolerance) so touch
 *   users can drag cards from the handle without the sensor hijacking the
 *   board's horizontal scroll-snap swipe or a lane's vertical scroll: a
 *   swipe moves past the tolerance before the delay elapses and cancels
 *   activation, while a press-and-hold on the handle starts a drag. The
 *   handle already sets `touch-action: none` (styles.css) so the browser
 *   never fights the sensor for gestures that begin on it.
 * - KeyboardSensor is registered for a11y — the documented reason @dnd-kit
 *   was chosen over alternatives (see wf005-context.md).
 */
import { KeyboardSensor, PointerSensor, TouchSensor } from "@dnd-kit/core";
import type { SensorDescriptor, SensorOptions } from "@dnd-kit/core";

export const DRAG_SENSOR_DESCRIPTORS: Array<{
  sensor: SensorDescriptor<SensorOptions>["sensor"];
  options: {
    activationConstraint?: {
      distance?: number;
      delay?: number;
      tolerance?: number;
    };
  };
}> = [
  { sensor: PointerSensor, options: { activationConstraint: { distance: 8 } } },
  {
    sensor: TouchSensor,
    options: { activationConstraint: { delay: 200, tolerance: 8 } },
  },
  { sensor: KeyboardSensor, options: {} },
];
