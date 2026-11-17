// The flagpole in a project's Goals room while it has no goals: say or type the goal, hear it read back, say yes,
// and it is set. Nothing is saved without that yes. The page gives save(goal), which keeps it wherever its goals
// live, and the room then shows the goal's flag like any other. Plain module: the demo and any page that embeds
// the building use it, and tests/test_goal_stand.py runs it under Node.
//
// The flagpole is a tappable thing in the room, with a ring to stand in (the building's fill gives it), whose link
// is #/<floor id>/goals/new.

export const isStandHref = (href) => /^#\/[^/?#]+\/goals\/new$/.test(String(href || ''));
export const standFloor = (href) => (isStandHref(href) ? decodeURIComponent(String(href).split('/')[1]) : null);
export const standHref = (floorId) => `#/${encodeURIComponent(floorId)}/goals/new`;

const YES_WORDS = "yes|yeah|yep|yup|sure|ok|okay|go ahead|do it|set it|please do|please|correct|that's right|that is right|right|send it";
// A yes, and nothing more: "yes", "yes please", "ok, set it". Anything longer may be a new goal, which wins.
const YES = new RegExp(`^(?:${YES_WORDS})(?:[\\s,.!]+(?:${YES_WORDS}|thanks|thank you|it is))*[\\s,.!]*$`, 'i');
const YES_ISH = new RegExp(`^(?:${YES_WORDS})\\b`, 'i'); // starts like a yes: never a goal on its own
const NO = /^(no|nope|not yet|cancel|stop|never ?mind|wait|don't|do not|not that)\b/i;
const OPENER = "(?:(?:so|ok|okay|well|right|alright|all right|yes|no|actually)[,.]?\\s+)?";
const GOAL = new RegExp(`^${OPENER}(?:the |our |its |my |this project's |the project's )?goal(?:\\s*[:=]|\\s+(?:is|should be|will be)\\b\\s*:?)\\s*(?:to\\s+)?(.+)$`, 'i');
const SET = new RegExp(`^${OPENER}(?:please\\s+)?(?:set|make|change)\\s+(?:the\\s+|our\\s+|its\\s+)?goal\\s+(?:to|as)\\s*:?\\s*(?:be\\s+)?(.+)$`, 'i');
// Said at the flagpole, but not a goal: questions, greetings, asking to go somewhere, not knowing yet.
const NOT_GOAL = /^(what|why|how|who|when|where|which|is|are|can|could|do|does|should|will|would|hi|hello|hey|thanks|thank you|take me|go to|go back|back to|bring me|tell me|show me|let me|i am not sure|i'm not sure|not sure|i don't know|i do not know|dunno|no idea|hmm+|um+|uh+|er+)\b/i;

const tidy = (s) => String(s || '').trim().replace(/^["'“‘]+|["'”’]+$/g, '').replace(/[.!\s]+$/, '').trim();
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// The goal in "the goal is ...", "goal: ...", "set the goal to ...": the goal, or null when what follows isn't one
// ("the goal is what?"); undefined when it isn't said that way.
function named(text) {
  const m = tidy(text).match(GOAL) || tidy(text).match(SET);
  if (!m) return undefined;
  const g = tidy(tidy(m[1]).replace(/\?+$/, ''));
  if (g.length < 3 || NOT_GOAL.test(g) || YES_ISH.test(g)) return null;
  return capital(g.slice(0, 200));
}

// The goal in what was said, if it gives one: said the usual ways (above), or, typed or said plainly, a few words
// that aren't a question, a greeting, a yes or a no. At most 200 characters, as goals are kept.
export function goalAsked(text) {
  const n = named(text);
  if (n !== undefined) return n;
  const t = tidy(text);
  if (t.endsWith('?') || NOT_GOAL.test(t) || YES_ISH.test(t) || NO.test(t) || /^(?:the |our |its |my )?goal\b/i.test(t) || t.split(/\s+/).length < 2) return null;
  return capital(t.slice(0, 200));
}

// One flagpole's conversation: label is the project's name as people say it; save(goal) sets it (a promise, or
// nothing), and throws or rejects with a message in words when it can't. kept, if given, is said after "Done", such
// as where the goal is kept.
export function createGoalStand({ label, save, kept = '' }) {
  let held = null; // the goal read back, waiting for a yes
  return {
    held: () => held,
    greet() {
      held = null;
      return `No goal yet for ${label}. What is it for? Say "the goal is", then the goal, or type it.`;
    },
    answer(text) {
      const said = String(text || '').trim();
      const fresh = named(said) || null; // a new goal said the usual way wins over a yes or a no: "ok, the goal is ..."
      if (held && !fresh && YES.test(said)) {
        const goal = held;
        held = null;
        return Promise.resolve()
          .then(() => save(goal))
          .then(() => `Done. ${label}'s goal is "${goal}".${kept ? ` ${kept}` : ''}`, (error) => `I couldn't set it: ${error?.message || 'it did not save'}. Say it again to try once more.`);
      }
      if (held && !fresh && NO.test(said)) {
        held = null;
        return 'All right, not set. Say the goal again when you are ready.';
      }
      const goal = fresh || goalAsked(said);
      if (goal) {
        held = goal;
        return `Set ${label}'s goal to "${goal}"? Say yes, or no.`;
      }
      if (held) return `Say yes to set ${label}'s goal to "${held}", or no.`;
      return `What is the goal for ${label}? Say "the goal is", then the goal.`;
    },
  };
}
