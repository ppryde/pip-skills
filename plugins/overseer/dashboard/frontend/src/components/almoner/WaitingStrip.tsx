import type { WaitingPerson } from "../../board/almoner/people";
import { formatWait } from "../../board/almoner/people";
import { Label } from "../../ui";

/**
 * "Waiting on you" — the digest read as obligations to people.
 *
 * This is where the last-speaker rule stops being a hidden filter and becomes
 * the headline: `clear` is EARNED (you answered last), not merely "nothing
 * arrived". The strip is a glance, not a list — it scrolls sideways rather
 * than wrapping, and `whosWaiting` caps it so it never becomes a directory.
 */
export interface WaitingStripProps {
  people: WaitingPerson[];
}

export default function WaitingStrip({ people }: WaitingStripProps) {
  if (people.length === 0) return null;

  return (
    <div className="alm-waiting">
      <Label className="alm-waiting__eyebrow">Waiting on you</Label>
      <ul className="alm-waiting__strip">
        {people.map((person) => {
          const wait = formatWait(person.waitedMs);
          return (
            <li
              key={person.name}
              className={`alm-person${person.owed ? " alm-person--owed" : " alm-person--clear"}`}
            >
              <span className="alm-person__disc" aria-hidden="true">{person.initial}</span>
              <span className="alm-person__name">{person.name}</span>
              <span className="alm-person__wait">
                {person.owed ? wait || "waiting" : "clear"}
              </span>
              {/* Said in words as well as colour: someone kept waiting should
                  not depend on an amber border being noticed. */}
              <span className="sr-only">
                {person.owed
                  ? `has been waiting ${wait || "an unknown time"}`
                  : "you answered last"}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
