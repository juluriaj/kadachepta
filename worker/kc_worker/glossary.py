"""Telugu story nouns the 8B model misreads, looked up in code instead of trusted to the model.

qwen3-8b barely reads Telugu: given one example ("కాకి is a crow") it turned monkeys, frogs, pigeons, cranes,
and rats into crows in 26 of 319 English teasers (2026-10-12). So each prompt gets a glossary of the
characters that actually occur in the story, and the English output is checked against the transcript.

A transcript word matches a form when it starts with the form and the next letter is not a vowel sign or
virama, so కప్ప (frog) matches కప్పలు and కప్పను but not కప్పు (cup).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    gloss: str               # what the model is told, e.g. "monkey"
    forms: tuple[str, ...]   # Telugu word starts; the first is shown in the glossary
    check: tuple[str, ...]   # English words that need this entry in the transcript (singular; plurals derived)
    roman: tuple[str, ...] = ()  # romanized title words, e.g. "kothi"


ENTRIES = [
    # Animals
    Entry("monkey", ("కోతి", "కోతు", "వానరం", "వానరా", "వానరు", "మర్కటం", "మర్కటా"), ("monkey", "ape"),
          ("koti", "kothi", "kotulu", "kothulu", "kotula", "kothula")),
    Entry("crow", ("కాకి", "కాకుల", "వాయసం"), ("crow",), ("kaki", "kaaki", "kakulu", "kaakulu", "kaakula")),
    Entry("frog", ("కప్ప", "మండూకం"), ("frog", "toad"), ("kappa", "kappalu", "kappala")),
    Entry("mouse (rat)", ("ఎలుక", "చిట్టెలుక", "మూషికం", "మూషికా"), ("mouse", "rat"),
          ("eluka", "yeluka", "elukalu", "chitteluka")),
    Entry("cat", ("పిల్లి", "పిల్లు", "మార్జాలం"), ("cat", "kitten"), ("pilli", "pillulu")),
    Entry("dog", ("కుక్క", "శునకం"), ("dog", "puppy"), ("kukka", "kukkalu")),
    Entry("jackal (fox)", ("నక్క", "జంబుకం"), ("jackal", "fox"), ("nakka", "nakkalu")),
    Entry("lion", ("సింహ", "సింహా", "మృగరాజు", "కేసరి"), ("lion", "lioness"), ("simham", "simha", "simhalu")),
    Entry("tiger", ("పులి", "పులుల", "పెద్దపులి", "పెద్దపులు", "బెబ్బులి"), ("tiger",), ("puli", "pululu", "peddapuli")),
    Entry("elephant", ("ఏనుగు", "గజం", "గజరాజు"), ("elephant",), ("enugu", "yenugu", "aenugu", "enugulu", "gajaraju")),
    Entry("crocodile", ("మొసలి", "మొసళ్", "మొసలు"), ("crocodile", "alligator"), ("mosali", "mosallu")),
    Entry("rabbit (hare)", ("కుందేలు", "కుందేళ్", "కుందేలి"), ("rabbit", "hare", "bunny"), ("kundelu",)),
    Entry("tortoise", ("తాబేలు", "తాబేళ్", "తాబేలి", "కూర్మం"), ("tortoise", "turtle"), ("tabelu", "thabelu")),
    Entry("snake", ("పాము", "సర్ప", "నాగుపాము", "త్రాచు"), ("snake", "cobra", "serpent"), ("pamu", "paamu", "paamulu")),
    Entry("deer (stag)", ("జింక", "లేడి", "దుప్పి"), ("deer", "fawn", "antelope"), ("jinka", "jinkalu", "ledi")),
    Entry("cow", ("ఆవు", "గోవు"), ("cow",), ("aavu", "avu", "aavulu", "govu")),
    Entry("calf", ("దూడ",), ("calf",), ("duda", "dooda")),
    Entry("bull (ox)", ("ఎద్దు", "ఆబోతు", "వృషభం"), ("bull", "ox"), ("eddu", "eddulu")),
    Entry("buffalo", ("గేదె", "బర్రె", "దున్నపోతు"), ("buffalo",), ("gede", "barre", "dunnapotu")),
    Entry("goat", ("మేక",), ("goat",), ("meka", "mekalu", "mekapotu")),
    Entry("sheep", ("గొర్రె",), ("sheep", "lamb"), ("gorre", "gorrelu")),
    Entry("donkey", ("గాడిద", "గార్దభం"), ("donkey",), ("gadida", "gaadida", "gadidalu")),
    Entry("horse", ("గుర్రం", "గుర్రా", "గుర్రపు", "అశ్వం", "అశ్వా"), ("horse", "pony"), ("gurram", "gurralu")),
    Entry("camel", ("ఒంటె",), ("camel",), ("onte",)),
    Entry("cattle", ("పశువు", "పశువుల"), ("cattle", "cow", "bull", "ox", "buffalo"), ("pasuvulu",)),
    Entry("lizard", ("తొండ", "బల్లి"), ("lizard",), ("tonda", "thonda", "balli")),
    Entry("bear", ("ఎలుగుబంటి", "ఎలుగు", "భల్లూకం"), (), ("elugubanti",)),  # "bear" is also a verb
    Entry("wolf", ("తోడేలు", "తోడేళ్", "తోడేలి"), ("wolf",), ("todelu", "thodelu")),
    Entry("squirrel", ("ఉడత", "ఉడుత"), ("squirrel",), ("udata", "uduta", "udatha")),
    Entry("pig (boar)", ("పంది", "అడవిపంది", "వరాహం"), ("pig", "boar", "hog"), ("pandi",)),
    Entry("mongoose", ("ముంగిస",), ("mongoose",), ("mungisa",)),
    Entry("fish", ("చేప", "మత్స్యం", "మీనం"), ("fish",), ("chepa", "chepalu")),
    Entry("crab", ("పీత",), ("crab",), ("peetha",)),
    Entry("ant", ("చీమ",), ("ant",), ("cheema", "chima", "cheemalu")),
    Entry("bee", ("తేనెటీగ",), ("bee",), ("teneteega",)),
    Entry("fly (the insect)", ("ఈగ",), (), ("eega", "ega")),  # "fly" is also a verb
    Entry("mosquito", ("దోమ",), ("mosquito",), ("doma",)),
    Entry("spider", ("సాలీడు", "సాలెపురుగు"), ("spider",), ("saleedu",)),
    Entry("snail", ("నత్త",), ("snail",), ("natta", "nattha")),
    Entry("grasshopper", ("మిడత",), ("grasshopper", "locust"), ("midata",)),
    Entry("butterfly", ("సీతాకోకచిలుక",), ("butterfly",), ("seethakokachiluka",)),
    Entry("bat", ("గబ్బిలం", "గబ్బిలా"), ("bat",), ("gabbilam",)),
    # Birds
    Entry("swan", ("హంస",), ("swan",), ("hamsa", "hamsalu")),
    Entry("peacock", ("నెమలి", "నెమళ్", "మయూరం"), ("peacock", "peahen"), ("nemali", "nemallu")),
    Entry("parrot", ("చిలుక", "రామచిలుక"), ("parrot",), ("chiluka", "ramachiluka", "chilaka")),
    Entry("pigeon (dove)", ("పావురం", "పావురా", "పావుర", "గువ్వ"), ("pigeon",), ("pavuram", "paavuram", "guvva")),
    Entry("crane (heron)", ("కొంగ",), ("crane", "heron", "stork"), ("konga", "kongalu")),
    Entry("kite (bird of prey)", ("గద్ద", "గ్రద్ద"), ("eagle", "kite", "hawk", "falcon"), ("gadda", "gradda")),
    Entry("hawk", ("డేగ",), ("hawk", "eagle", "falcon"), ("dega",)),
    Entry("kite (paper toy)", ("గాలిపటం", "గాలిపటా"), ("kite",), ("galipatam",)),
    Entry("eagle (Garuda)", ("గరుడ", "గరుత్మం"), ("eagle",), ("garuda",)),
    Entry("owl", ("గుడ్లగూబ",), ("owl",), ("gudlaguba",)),
    Entry("sparrow", ("పిచ్చుక",), ("sparrow",), ("pichuka", "pichchuka")),
    Entry("myna", ("గోరింక", "గోరువంక"), ("myna", "mynah"), ("gorinka", "goruvanka")),
    Entry("cuckoo", ("కోకిల", "కోయిల"), ("cuckoo", "koel"), ("kokila", "koyila")),
    Entry("duck", ("బాతు",), ("duck",), ("baathu", "bathu")),
    Entry("hen (rooster)", ("కోడి", "కోళ్", "పుంజు"), ("hen", "rooster", "chicken"), ("kodi", "kollu", "kodipunju")),
    Entry("woodpecker", ("వడ్రంగిపిట్ట",), ("woodpecker",), ("vadrangipitta",)),
    Entry("vulture", ("రాబందు",), ("vulture",), ("rabandu",)),
    Entry("bird", ("పక్షి", "పిట్ట"), (), ("pakshi", "pitta")),
    # People the model mistranslates
    Entry("carpenter", ("వడ్రంగి", "వడ్రంగు"), (), ("vadrangi",)),
    Entry("woodcutter", ("కట్టెలవాడు",), (), ()),
    Entry("potter", ("కుమ్మరి",), (), ("kummari",)),
    Entry("blacksmith", ("కమ్మరి",), (), ("kammari",)),
    Entry("goldsmith", ("కంసాలి",), (), ("kamsali",)),
    Entry("washerman", ("చాకలి",), (), ("chakali",)),
    Entry("barber", ("మంగలి",), (), ("mangali",)),
    Entry("fisherman", ("జాలరి", "బెస్త"), (), ("jalari", "jaalari", "bestha")),
    Entry("hunter", ("వేటగా", "వేటగాళ్"), (), ("vetagadu", "vetagaadu", "vetagaadi", "vetagadi")),
    Entry("farmer", ("రైతు",), (), ("raitu", "raithu", "rythu")),
    Entry("merchant", ("వ్యాపారి", "వర్తకు", "వర్తకి", "వ్యాపారు"), (), ("vyapari", "vartakudu")),
    Entry("thief", ("దొంగ",), (), ("donga", "dongalu")),
    Entry("ghost", ("దయ్యం", "దెయ్యం", "దయ్యా", "దెయ్యా", "భూతం"), (), ("dayyam", "deyyam")),
    Entry("demon (rakshasa)", ("రాక్షసు", "రాక్షసి", "రాకాసి"), (), ("rakshasudu", "rakshasi", "rakasi")),
]

# Words that start like a glossary form but mean something else: చేపట్టాడు (took up), పులుసు (tamarind stew),
# కప్పడం (to cover), కుక్కర్ (cooker), సర్పంచ్ (village head), సింహాసనం (throne), పిట్టకథ (anecdote),
# తొండం (an elephant's trunk).
NOT_WORDS = ("చేపట్ట", "పులుసు", "కప్పడ", "కప్పట", "కప్పబ", "కుక్కర్", "సర్పంచ", "సింహాసన", "సింహద్వార",
             "పిట్టకథ", "దొంగచాటు", "తొండం")

# How each animal is always drawn, so the monkey in one cover matches the monkey in the next (artwork prompts).
# Short on purpose: SDXL reads only 77 tokens, shared with the style, the scene, and the expressions.
LOOKS = {
    "monkey": "small brown monkey with a long curly tail and big round eyes",
    "crow": "glossy black crow with a grey neck",
    "frog": "round green frog with big golden eyes",
    "mouse (rat)": "tiny grey mouse with big pink ears",
    "cat": "plump orange tabby cat with green eyes",
    "dog": "friendly tan dog with floppy ears",
    "jackal (fox)": "slim sandy jackal with pointed ears and a bushy tail",
    "lion": "golden lion with a big shaggy mane",
    "tiger": "orange tiger with bold black stripes",
    "elephant": "grey Indian elephant with small tusks",
    "crocodile": "long green crocodile with a toothy grin",
    "rabbit (hare)": "small white rabbit with long ears",
    "tortoise": "brown tortoise with a patterned shell",
    "snake": "long green snake",
    "deer (stag)": "spotted deer with small antlers",
    "cow": "white cow with curved horns and a bell",
    "calf": "small white calf",
    "bull (ox)": "white humped bull with long curved horns",
    "buffalo": "dark grey buffalo with wide curved horns",
    "cattle": "white cattle with curved horns",
    "goat": "brown and white goat with small horns",
    "sheep": "fluffy white sheep",
    "donkey": "grey donkey with long ears",
    "horse": "brown horse with a dark mane",
    "camel": "tall sandy camel with one hump",
    "lizard": "small green lizard",
    "bear": "shaggy black bear with a pale snout",
    "wolf": "grey wolf with a long snout",
    "squirrel": "striped palm squirrel with a bushy tail",
    "pig (boar)": "dark bristly wild boar with small tusks",
    "mongoose": "slender grey mongoose",
    "fish": "shiny orange fish",
    "crab": "small red crab",
    "ant": "tiny black ant",
    "bee": "fuzzy yellow and black bee",
    "fly (the insect)": "small black fly",
    "mosquito": "thin grey mosquito",
    "spider": "small brown spider",
    "snail": "brown snail with a spiral shell",
    "grasshopper": "bright green grasshopper",
    "butterfly": "colourful butterfly",
    "bat": "brown bat with wide wings",
    "swan": "graceful white swan",
    "peacock": "blue peacock with a green and gold tail",
    "parrot": "bright green parrot with a red beak",
    "pigeon (dove)": "grey pigeon with a shimmering neck",
    "crane (heron)": "tall white crane with long legs",
    "kite (bird of prey)": "brown kite with a hooked beak",
    "hawk": "brown hawk with sharp eyes",
    "eagle (Garuda)": "golden eagle with wide wings",
    "owl": "round brown owl with big yellow eyes",
    "sparrow": "little brown sparrow",
    "myna": "brown myna with a yellow beak",
    "cuckoo": "black cuckoo with red eyes",
    "duck": "white duck with an orange beak",
    "hen (rooster)": "red-combed hen",
    "woodpecker": "woodpecker with a red crest",
    "vulture": "bald-headed vulture",
}

_TELUGU_WORD = re.compile(r"[\u0C00-\u0C7F]+")
_STEM_CONTINUES = re.compile(r"[\u0C3E-\u0C4D\u0C55\u0C56]")  # vowel signs and virama
_FORMS = sorted(((form, entry) for entry in ENTRIES for form in entry.forms), key=lambda item: -len(item[0]))
_ROMAN = {word: entry for entry in ENTRIES for word in entry.roman}


def _plurals(word: str) -> set[str]:
    irregular = {"mouse": {"mice"}, "wolf": {"wolves"}, "ox": {"oxen"}, "calf": {"calves"}, "puppy": {"puppies"},
                 "fish": {"fishes"}, "sheep": set(), "deer": set(), "buffalo": {"buffaloes", "buffalos"},
                 "fox": {"foxes"}, "bunny": {"bunnies"}, "butterfly": {"butterflies"}, "mosquito": {"mosquitoes"}}
    return {word} | irregular.get(word, {word + "s"})


_CHECK: dict[str, list[Entry]] = {}
for _entry in ENTRIES:
    for _word in _entry.check:
        for _form in _plurals(_word):
            _CHECK.setdefault(_form, []).append(_entry)


def find(text: str) -> Counter:
    """Glossary entries in Telugu text, with how often each occurs."""
    counts: Counter = Counter()
    for word in _TELUGU_WORD.findall(text or ""):
        if word.startswith(NOT_WORDS):
            continue
        for form, entry in _FORMS:  # longest first: వడ్రంగిపిట్ట (woodpecker) before వడ్రంగి (carpenter)
            if word.startswith(form) and not _STEM_CONTINUES.match(word, len(form)):
                counts[entry] += 1
                break
    return counts


def find_roman(title: str) -> list[Entry]:
    """Glossary entries for words in a romanized Telugu title such as "Koti Mosali"."""
    found: list[Entry] = []
    for word in re.findall(r"[a-z]+", (title or "").lower()):
        entry = _ROMAN.get(word)
        if entry and entry not in found:
            found.append(entry)
    return found


def describe(entries) -> str:
    return "; ".join(f"{entry.forms[0]} = {entry.gloss}" for entry in entries)


def glossary_for(text: str, limit: int = 14) -> str:
    """'కోతి = monkey; వడ్రంగి = carpenter', most frequent first; empty when nothing matches."""
    return describe(entry for entry, _ in find(text).most_common(limit))


def unsupported_animals(english: str, transcript: str) -> list[str]:
    """English animal words in a draft with no matching Telugu word in the transcript ("crow" for a monkey story)."""
    present = set(find(transcript))
    english = re.sub(r"\bbull (elephant|frog)", r"\1", (english or "").lower())  # a bull elephant is an elephant
    wrong = []
    for word in re.findall(r"[a-z]+", english):
        entries = _CHECK.get(word)
        if entries and not present.intersection(entries):
            base = next(base for base in entries[0].check if word in _plurals(base))
            if base not in wrong:
                wrong.append(base)
    return wrong


def animals_named(english: str) -> list[Entry]:
    """Animals an English text mentions, in order of first mention ("A monkey and a crocodile" -> monkey, crocodile)."""
    found: list[Entry] = []
    for word in re.findall(r"[a-z]+", re.sub(r"\bbull (elephant|frog)", r"\1", (english or "").lower())):
        for entry in _CHECK.get(word, []):
            if entry.gloss in LOOKS and entry not in found:
                found.append(entry)
    return found


def cast(transcript: str, english: str = "", title: str = "", limit: int = 2, recurring: int = 4) -> list[Entry]:
    """The animals to draw: those the English teaser names (and the transcript confirms), else animals the
    transcript mentions at least ``recurring`` times (a main character, not the ant in a war chronicle), else
    animals in a romanized title."""
    counts = find(transcript)
    in_story = [entry for entry, n in counts.most_common() if entry.gloss in LOOKS and n >= recurring]
    named = [entry for entry in animals_named(english) if not counts or entry in counts]
    chosen = named or in_story or [entry for entry in find_roman(title) if entry.gloss in LOOKS]
    return chosen[:limit]


def telugu_word_for(english: str) -> str:
    entries = _CHECK.get(english.lower()) or []
    return " / ".join(entry.forms[0] for entry in entries)
