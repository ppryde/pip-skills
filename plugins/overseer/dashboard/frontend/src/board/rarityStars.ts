/**
 * Maps a card's `complexity` (backend enum "S" | "M" | "L", see
 * plugins/overseer/scripts/cli.py's `--complexity` choices) onto the
 * HANDOFF rarity-star count (1-3 filled pips). Any other value — null,
 * unset, or an unrecognised string — renders zero stars rather than
 * guessing; TileShell only reserves the stars row when this is > 0.
 */
export function rarityStars(complexity: string | null): number {
  switch (complexity) {
    case "S":
      return 1;
    case "M":
      return 2;
    case "L":
      return 3;
    default:
      return 0;
  }
}
