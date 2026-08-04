// Tamagotchi character state and evolution rules (issue #13).
//
// Deliberately free of Arduino/ESP dependencies so it can be built and unit
// tested on the host: g++ -std=c++17 tools/test_character_logic.cpp
#ifndef TOI_CHARACTER_LOGIC_H
#define TOI_CHARACTER_LOGIC_H

#include <stdint.h>
#include <string.h>

// Meal categories — index into CharState::cnt.
enum : uint8_t {
  TOI_CAT_VEGETABLE = 0,
  TOI_CAT_MEAT = 1,
  TOI_CAT_SEAFOOD = 2,
  TOI_CAT_SWEET = 3,
  TOI_CAT_GRAIN = 4,
  TOI_CAT_OTHER = 5,
  TOI_CAT_COUNT = 6,
};

enum : uint8_t {
  TOI_STAGE_BABY = 0,
  TOI_STAGE_CHILD = 1,
  TOI_STAGE_ADULT = 2,
};

// Form ids match the TOI_SPRITES[] table in sprites/sprites.h.
enum : uint8_t {
  TOI_FORM_BABY = 0,
  TOI_FORM_CHILD_A = 1,
  TOI_FORM_CHILD_B = 2,
  TOI_FORM_LEAF = 3,
  TOI_FORM_MUSCLE = 4,
  TOI_FORM_MARINE = 5,
  TOI_FORM_CANDY = 6,
  TOI_FORM_RAINBOW = 7,
};

static const uint8_t TOI_CHAR_VERSION = 1;
static const uint32_t TOI_CHILD_MEALS = 3;
static const uint32_t TOI_ADULT_MEALS = 10;
// An adult branch needs this share of the *effective* meal count (percent).
static const uint32_t TOI_ADULT_SHARE_PCT = 40;

// Persisted verbatim as one NVS blob — changing the layout needs a version bump.
struct CharState {
  uint8_t version;
  uint8_t stage;
  uint8_t form;
  uint16_t cnt[TOI_CAT_COUNT];
  uint32_t kcalDay;
  uint32_t dayKey;  // YYYYMMDD, or 0 = "fed while the clock was invalid"
};

inline CharState toiCharInit() {
  CharState s;
  memset(&s, 0, sizeof(s));
  s.version = TOI_CHAR_VERSION;
  s.stage = TOI_STAGE_BABY;
  s.form = TOI_FORM_BABY;
  return s;
}

inline bool toiCharValid(const CharState &s) {
  return s.version == TOI_CHAR_VERSION && s.stage <= TOI_STAGE_ADULT &&
         s.form <= TOI_FORM_RAINBOW;
}

// Every category counts toward the stage thresholds.
inline uint32_t toiTotalMeals(const CharState &s) {
  uint32_t total = 0;
  for (uint8_t i = 0; i < TOI_CAT_COUNT; ++i) total += s.cnt[i];
  return total;
}

// grain/other are excluded from the adult branch denominator.
inline uint32_t toiEffectiveMeals(const CharState &s) {
  return (uint32_t)s.cnt[TOI_CAT_VEGETABLE] + s.cnt[TOI_CAT_MEAT] +
         s.cnt[TOI_CAT_SEAFOOD] + s.cnt[TOI_CAT_SWEET];
}

inline uint8_t toiChildForm(const CharState &s) {
  const uint32_t light = (uint32_t)s.cnt[TOI_CAT_VEGETABLE] + s.cnt[TOI_CAT_SEAFOOD];
  const uint32_t heavy = (uint32_t)s.cnt[TOI_CAT_MEAT] + s.cnt[TOI_CAT_SWEET];
  return (light >= heavy) ? TOI_FORM_CHILD_A : TOI_FORM_CHILD_B;
}

// Max of the four branching categories, ties resolved to the smaller index
// (which maps to the smaller form id). Rainbow when nobody clears the share.
inline uint8_t toiAdultForm(const CharState &s) {
  const uint32_t effective = toiEffectiveMeals(s);
  if (effective == 0) return TOI_FORM_RAINBOW;
  uint8_t best = TOI_CAT_VEGETABLE;
  for (uint8_t i = TOI_CAT_MEAT; i <= TOI_CAT_SWEET; ++i) {
    if (s.cnt[i] > s.cnt[best]) best = i;
  }
  if ((uint32_t)s.cnt[best] * 100 >= effective * TOI_ADULT_SHARE_PCT) {
    return (uint8_t)(TOI_FORM_LEAF + best);  // veg->3 meat->4 seafood->5 sweet->6
  }
  return TOI_FORM_RAINBOW;
}

// Promotes at most one stage per call and never walks a stage/form backwards.
inline bool toiApplyEvolution(CharState &s) {
  const uint32_t total = toiTotalMeals(s);
  if (s.stage < TOI_STAGE_ADULT && total >= TOI_ADULT_MEALS) {
    s.stage = TOI_STAGE_ADULT;
    s.form = toiAdultForm(s);
    return true;
  }
  if (s.stage < TOI_STAGE_CHILD && total >= TOI_CHILD_MEALS) {
    s.stage = TOI_STAGE_CHILD;
    s.form = toiChildForm(s);
    return true;
  }
  return false;
}

// dateKey is YYYYMMDD, or 0 when the clock is not trustworthy yet.
// The daily kcal counter resets only on a *proven* day change: a 0 sentinel
// means "we do not know which day this was", so the tally is carried over
// instead of being thrown away. Returns true when the counter was reset.
inline bool toiApplyDayRoll(CharState &s, uint32_t dateKey) {
  if (dateKey == 0) return false;
  const bool changed = (s.dayKey != 0 && dateKey != s.dayKey);
  if (changed) s.kcalDay = 0;
  s.dayKey = dateKey;
  return changed;
}

// One meal. Returns true when the character evolved.
inline bool toiApplyFeed(CharState &s, uint8_t category, uint32_t kcal,
                         uint32_t dateKey) {
  if (category >= TOI_CAT_COUNT) category = TOI_CAT_OTHER;
  if (s.cnt[category] != 0xFFFF) ++s.cnt[category];
  if (dateKey == 0) {
    s.dayKey = 0;  // sentinel: fed with an unknown date
  } else {
    toiApplyDayRoll(s, dateKey);
  }
  s.kcalDay += kcal;
  return toiApplyEvolution(s);
}

inline uint8_t toiCategoryFromName(const char *name) {
  if (!name) return TOI_CAT_OTHER;
  if (!strcmp(name, "vegetable")) return TOI_CAT_VEGETABLE;
  if (!strcmp(name, "meat")) return TOI_CAT_MEAT;
  if (!strcmp(name, "seafood")) return TOI_CAT_SEAFOOD;
  if (!strcmp(name, "sweet")) return TOI_CAT_SWEET;
  if (!strcmp(name, "grain")) return TOI_CAT_GRAIN;
  return TOI_CAT_OTHER;
}

inline const char *toiCategoryName(uint8_t category) {
  switch (category) {
    case TOI_CAT_VEGETABLE: return "vegetable";
    case TOI_CAT_MEAT: return "meat";
    case TOI_CAT_SEAFOOD: return "seafood";
    case TOI_CAT_SWEET: return "sweet";
    case TOI_CAT_GRAIN: return "grain";
    default: return "other";
  }
}

#endif  // TOI_CHARACTER_LOGIC_H
