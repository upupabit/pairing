/* A reply's reasoning stages (bubble._reasoning, the "reasoning" live event; app/services/reasoning_stages.py). While
the model reasons, the waiting label after the typing dots is one word for the current stage, taken from its heading
("2. Determine the Goal" -> "Determining…"), else a fixed word for that step number. Once the answer streams it
replaces the label; nothing about the stages is kept or shown with the answer. */
class ReasoningSteps {
  // A heading that doesn't start with a verb gets these, by step number (the last one for later steps).
  static FALLBACK_WORDS = ["Understanding", "Exploring", "Planning", "Drafting", "Checking"];
  // First words that aren't verbs: an "-ing" form of them would read wrong.
  static NOT_VERBS = new Set(["final", "key", "initial", "overall", "summary", "answer", "step", "the", "a", "an", "my",
    "our", "user", "response", "goal", "options", "next", "main", "core", "self", "possible", "potential", "first"]);
  static NOUN_ENDINGS = /(sis|tion|sion|ment|ness|ity|ance|ence|ure|al|ic|ive|ous|ary|ory|er|or|s)$/;

  /* The waiting label: the current stage as one word, or `fallback` before the first stage. */
  static label(bubble, fallback) {
    const stages = bubble._reasoning;
    if (!stages || !stages.length) return fallback;
    return `${ReasoningSteps.word(stages[stages.length - 1], stages.length - 1)}…`;
  }

  static word(stage, index) {
    const first = stage.replace(/^\d+\.\s*/, "").split(/[\s:,(]/)[0] || "";
    const lower = first.toLowerCase();
    const fixed = ReasoningSteps.FALLBACK_WORDS[Math.min(index, ReasoningSteps.FALLBACK_WORDS.length - 1)];
    if (!/^[a-z]{3,}$/.test(lower) || ReasoningSteps.NOT_VERBS.has(lower)) return fixed;
    if (lower.endsWith("ing")) return first[0].toUpperCase() + lower.slice(1);
    if (ReasoningSteps.NOUN_ENDINGS.test(lower)) return fixed;
    return ReasoningSteps.ing(lower);
  }

  /* "analyze" -> "Analyzing", "plan" -> "Planning", "draft" -> "Drafting", "tie" -> "Tying". */
  static ing(verb) {
    let stem = verb;
    if (stem.endsWith("ie")) stem = stem.slice(0, -2) + "y";
    else if (stem.endsWith("e") && !/(ee|ye|oe)$/.test(stem)) stem = stem.slice(0, -1);
    else if ((stem.match(/[aeiou]/g) || []).length === 1 && /[^aeiou][aeiou][^aeiouwxy]$/.test(stem)) {
      stem += stem[stem.length - 1]; // one-syllable consonant-vowel-consonant: plan -> plann
    }
    return stem[0].toUpperCase() + stem.slice(1) + "ing";
  }

  /* A live `reasoning` event: the full list so far. */
  static set(bubble, stages) {
    bubble._reasoning = stages;
  }
}
