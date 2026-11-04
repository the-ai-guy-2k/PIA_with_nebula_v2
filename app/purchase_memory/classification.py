"""Conservative item labels. Need versus want is left unknown for the user."""

from __future__ import annotations

import re

FOOD = "food"
NON_FOOD = "non-food"
NEED = "need"
WANT = "want"
CONSUMABLE = "consumable"
LONG_TERM = "long-term"
UNKNOWN = "unknown"

FOOD_VALUES = frozenset({FOOD, NON_FOOD, UNKNOWN})
NEED_VALUES = frozenset({NEED, WANT, UNKNOWN})
DURABILITY_VALUES = frozenset({CONSUMABLE, LONG_TERM, UNKNOWN})

# Whole words only. A match is a review hint, not a product identity.
_FOOD_WORDS = frozenset(
    {
        "apple",
        "bacon",
        "banana",
        "bean",
        "beans",
        "beef",
        "bread",
        "butter",
        "carrot",
        "carrots",
        "cereal",
        "cheese",
        "chicken",
        "coffee",
        "egg",
        "eggs",
        "fish",
        "flour",
        "juice",
        "lettuce",
        "milk",
        "oat",
        "oats",
        "onion",
        "orange",
        "pasta",
        "pork",
        "potato",
        "rice",
        "sugar",
        "tea",
        "tomato",
        "yogurt",
    }
)
_NON_FOOD_WORDS = frozenset(
    {
        "batteries",
        "battery",
        "bulb",
        "cable",
        "charger",
        "cleaner",
        "detergent",
        "hdmi",
        "shampoo",
        "soap",
        "towel",
        "towels",
    }
)
_CONSUMABLE_WORDS = frozenset(
    {
        "batteries",
        "battery",
        "cleaner",
        "detergent",
        "shampoo",
        "soap",
        "towel",
        "towels",
    }
)
_LONG_TERM_WORDS = frozenset({"bulb", "cable", "charger", "hdmi"})
_TOKENS = re.compile(r"[a-z0-9]+")


def classify_item_name(item_name: str) -> tuple[str, str, str]:
    tokens = set(_TOKENS.findall(item_name.lower()))
    food_hit = bool(tokens & _FOOD_WORDS)
    non_food_hit = bool(tokens & _NON_FOOD_WORDS)
    if food_hit and not non_food_hit:
        food = FOOD
    elif non_food_hit and not food_hit:
        food = NON_FOOD
    else:
        food = UNKNOWN

    consumable = food == FOOD or bool(tokens & _CONSUMABLE_WORDS)
    long_term = bool(tokens & _LONG_TERM_WORDS)
    if consumable and long_term:
        durability = UNKNOWN
    elif consumable:
        durability = CONSUMABLE
    elif long_term:
        durability = LONG_TERM
    else:
        durability = UNKNOWN
    return food, UNKNOWN, durability
