// Boss art for the end of each Atlas trail (POC). Hand-drawn monster icons,
// downsized to 128px, living in src/assets/monsters/. Imported here so Vite
// fingerprints + bundles them, and exposed as one array + a random picker.
import e001 from "../assets/monsters/pipoenemy001.png";
import e002 from "../assets/monsters/pipoenemy002.png";
import e003 from "../assets/monsters/pipoenemy003b.png";
import e004 from "../assets/monsters/pipoenemy004.png";
import e005 from "../assets/monsters/pipoenemy005.png";
import e006 from "../assets/monsters/pipoenemy006.png";
import e007 from "../assets/monsters/pipoenemy007.png";
import e008 from "../assets/monsters/pipoenemy008.png";
import e009 from "../assets/monsters/pipoenemy009.png";
import e010 from "../assets/monsters/pipoenemy010.png";
import e011 from "../assets/monsters/pipoenemy011.png";
import e012 from "../assets/monsters/pipoenemy012b.png";
import e013 from "../assets/monsters/pipoenemy013a.png";
import e015 from "../assets/monsters/pipoenemy015b.png";
import e016 from "../assets/monsters/pipoenemy016.png";
import e019 from "../assets/monsters/pipoenemy019.png";

export const monsterIcons: readonly string[] = [
  e001, e002, e003, e004, e005, e006, e007, e008,
  e009, e010, e011, e012, e013, e015, e016, e019,
];

/**
 * A random boss icon URL. Deliberately NOT stable across page loads — callers
 * memoise it per component mount (so it doesn't re-roll on every render) but a
 * fresh load can surface a new monster, which is fine for this POC.
 */
export function randomMonsterIcon(): string {
  return monsterIcons[Math.floor(Math.random() * monsterIcons.length)];
}
