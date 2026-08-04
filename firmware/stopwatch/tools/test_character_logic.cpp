// Host unit test for the issue #13 evolution rules.
//
//   g++ -std=c++17 -o /tmp/toi_char_test firmware/stopwatch/tools/test_character_logic.cpp
//   /tmp/toi_char_test
//
// No framework on purpose: plain assert(), so it runs anywhere a compiler does.
#include <assert.h>
#include <stdio.h>

#include "../src/character_logic.h"

static int gChecks = 0;

#define CHECK(cond)                                                        \
  do {                                                                     \
    ++gChecks;                                                             \
    if (!(cond)) {                                                         \
      printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond);               \
      assert(cond);                                                        \
    }                                                                      \
  } while (0)

// Feed n meals of one category on a fixed day.
static void feed(CharState &s, uint8_t cat, int n, uint32_t kcal = 100,
                 uint32_t dateKey = 20260804) {
  for (int i = 0; i < n; ++i) toiApplyFeed(s, cat, kcal, dateKey);
}

// Build a state by feeding the given per-category counts in category order.
static CharState fedWith(int veg, int meat, int seafood, int sweet, int grain,
                         int other) {
  CharState s = toiCharInit();
  feed(s, TOI_CAT_VEGETABLE, veg);
  feed(s, TOI_CAT_MEAT, meat);
  feed(s, TOI_CAT_SEAFOOD, seafood);
  feed(s, TOI_CAT_SWEET, sweet);
  feed(s, TOI_CAT_GRAIN, grain);
  feed(s, TOI_CAT_OTHER, other);
  return s;
}

static void testAdultBranches() {
  printf("-- adult branches (10 meals, >=40%% of veg+meat+seafood+sweet)\n");

  const CharState leaf = fedWith(5, 2, 2, 1, 0, 0);
  CHECK(leaf.stage == TOI_STAGE_ADULT);
  CHECK(leaf.form == TOI_FORM_LEAF);
  printf("   veg5 meat2 sea2 sweet1        -> form %u (leaf)\n", leaf.form);

  const CharState muscle = fedWith(2, 4, 2, 2, 0, 0);
  CHECK(muscle.form == TOI_FORM_MUSCLE);
  printf("   veg2 meat4 sea2 sweet2        -> form %u (muscle)\n", muscle.form);

  const CharState marine = fedWith(2, 2, 4, 2, 0, 0);
  CHECK(marine.form == TOI_FORM_MARINE);
  printf("   veg2 meat2 sea4 sweet2        -> form %u (marine)\n", marine.form);

  const CharState candy = fedWith(2, 2, 1, 5, 0, 0);
  CHECK(candy.form == TOI_FORM_CANDY);
  printf("   veg2 meat2 sea1 sweet5        -> form %u (candy)\n", candy.form);

  // Nobody reaches 40% of 10 -> the hidden "balanced" ending.
  const CharState rainbow = fedWith(3, 3, 2, 2, 0, 0);
  CHECK(rainbow.stage == TOI_STAGE_ADULT);
  CHECK(rainbow.form == TOI_FORM_RAINBOW);
  printf("   veg3 meat3 sea2 sweet2        -> form %u (rainbow, balanced)\n",
         rainbow.form);
}

static void testAdultTiesGoToSmallerId() {
  printf("-- adult ties resolve to the smaller form id\n");

  const CharState vegMeat = fedWith(4, 4, 1, 1, 0, 0);
  CHECK(vegMeat.form == TOI_FORM_LEAF);
  printf("   veg4 == meat4                 -> form %u (leaf, not muscle)\n",
         vegMeat.form);

  const CharState meatSea = fedWith(1, 4, 4, 1, 0, 0);
  CHECK(meatSea.form == TOI_FORM_MUSCLE);
  printf("   meat4 == sea4                 -> form %u (muscle, not marine)\n",
         meatSea.form);
}

static void testGrainOtherExcludedFromDenominator() {
  printf("-- grain/other count toward totals but not the 40%% denominator\n");

  // 10 meals total (so the adult check fires), but only 4 effective ones.
  // veg is 3/4 = 75% of the effective count; it would be 30% if grain counted.
  const CharState s = fedWith(3, 1, 0, 0, 5, 1);
  CHECK(toiTotalMeals(s) == 10);
  CHECK(toiEffectiveMeals(s) == 4);
  CHECK(s.stage == TOI_STAGE_ADULT);
  CHECK(s.form == TOI_FORM_LEAF);
  printf("   veg3 meat1 grain5 other1      -> total %u, effective %u, form %u\n",
         toiTotalMeals(s), toiEffectiveMeals(s), s.form);

  // Nothing but filler: the denominator is empty -> rainbow, not a crash.
  const CharState filler = fedWith(0, 0, 0, 0, 7, 3);
  CHECK(toiTotalMeals(filler) == 10);
  CHECK(toiEffectiveMeals(filler) == 0);
  CHECK(filler.form == TOI_FORM_RAINBOW);
  printf("   grain7 other3                 -> effective 0, form %u (rainbow)\n",
         filler.form);
}

static void testChildBranch() {
  printf("-- child branch at 3 meals ((veg+seafood) >= (meat+sweet))\n");

  CharState light = toiCharInit();
  CHECK(light.form == TOI_FORM_BABY && light.stage == TOI_STAGE_BABY);
  feed(light, TOI_CAT_VEGETABLE, 2);
  CHECK(light.stage == TOI_STAGE_BABY);  // still a baby at 2 meals
  feed(light, TOI_CAT_SEAFOOD, 1);
  CHECK(light.stage == TOI_STAGE_CHILD);
  CHECK(light.form == TOI_FORM_CHILD_A);
  printf("   veg2 sea1                     -> form %u (child_a)\n", light.form);

  CharState heavy = toiCharInit();
  feed(heavy, TOI_CAT_MEAT, 2);
  feed(heavy, TOI_CAT_SWEET, 1);
  CHECK(heavy.stage == TOI_STAGE_CHILD);
  CHECK(heavy.form == TOI_FORM_CHILD_B);
  printf("   meat2 sweet1                  -> form %u (child_b)\n", heavy.form);

  // A tie must fall to child_a — and grain pushes the total to 3 without
  // touching either side of the comparison.
  CharState tie = toiCharInit();
  feed(tie, TOI_CAT_VEGETABLE, 1);
  feed(tie, TOI_CAT_MEAT, 1);
  feed(tie, TOI_CAT_GRAIN, 1);
  CHECK(tie.stage == TOI_STAGE_CHILD);
  CHECK(tie.form == TOI_FORM_CHILD_A);
  printf("   veg1 meat1 grain1 (1 == 1)    -> form %u (child_a on the tie)\n",
         tie.form);
}

static void testNoDevolution() {
  printf("-- no devolution\n");

  CharState s = fedWith(5, 2, 2, 1, 0, 0);
  CHECK(s.form == TOI_FORM_LEAF);
  feed(s, TOI_CAT_SWEET, 40);  // a sugar binge must not re-brand an adult
  CHECK(s.stage == TOI_STAGE_ADULT);
  CHECK(s.form == TOI_FORM_LEAF);
  CHECK(s.cnt[TOI_CAT_SWEET] == 41);
  printf("   leaf + sweet40                -> stage %u form %u (unchanged)\n",
         s.stage, s.form);

  // A child that keeps eating filler stays a child until 10 meals, and never
  // reverts to a baby.
  CharState child = toiCharInit();
  feed(child, TOI_CAT_VEGETABLE, 3);
  CHECK(child.form == TOI_FORM_CHILD_A);
  feed(child, TOI_CAT_GRAIN, 2);
  CHECK(child.stage == TOI_STAGE_CHILD);
  CHECK(child.form == TOI_FORM_CHILD_A);
  printf("   child_a + grain2              -> stage %u form %u (still child)\n",
         child.stage, child.form);
}

static void testDayKeySentinel() {
  printf("-- dayKey sentinel / daily kcal\n");

  // Fed before the clock was ever trusted: the tally survives, dayKey = 0.
  CharState s = toiCharInit();
  toiApplyFeed(s, TOI_CAT_MEAT, 500, 0);
  CHECK(s.kcalDay == 500);
  CHECK(s.dayKey == 0);
  printf("   feed 500 with invalid clock   -> kcalDay %u dayKey %u\n", s.kcalDay,
         s.dayKey);

  // Clock comes back: adopt the date, do NOT wipe what was already eaten.
  toiApplyFeed(s, TOI_CAT_VEGETABLE, 300, 20260804);
  CHECK(s.kcalDay == 800);
  CHECK(s.dayKey == 20260804);
  printf("   feed 300 once the clock is ok -> kcalDay %u dayKey %u (kept)\n",
         s.kcalDay, s.dayKey);

  // Same day accumulates.
  toiApplyFeed(s, TOI_CAT_GRAIN, 200, 20260804);
  CHECK(s.kcalDay == 1000);
  printf("   feed 200 same day             -> kcalDay %u\n", s.kcalDay);

  // A real day change is the only thing that resets the counter.
  toiApplyFeed(s, TOI_CAT_SEAFOOD, 250, 20260805);
  CHECK(s.kcalDay == 250);
  CHECK(s.dayKey == 20260805);
  printf("   feed 250 next day             -> kcalDay %u dayKey %u (reset)\n",
         s.kcalDay, s.dayKey);

  // Back to an invalid clock: still no reset, just the sentinel again.
  toiApplyFeed(s, TOI_CAT_OTHER, 50, 0);
  CHECK(s.kcalDay == 300);
  CHECK(s.dayKey == 0);
  printf("   feed 50 with invalid clock    -> kcalDay %u dayKey %u\n", s.kcalDay,
         s.dayKey);

  // The standalone roll-over used by the Home screen behaves the same way.
  CharState r = toiCharInit();
  r.kcalDay = 700;
  r.dayKey = 0;
  CHECK(!toiApplyDayRoll(r, 0));       // unknown date: nothing happens
  CHECK(r.kcalDay == 700 && r.dayKey == 0);
  CHECK(!toiApplyDayRoll(r, 20260804));  // sentinel: adopt, keep the tally
  CHECK(r.kcalDay == 700 && r.dayKey == 20260804);
  CHECK(toiApplyDayRoll(r, 20260805));   // genuine change: reset
  CHECK(r.kcalDay == 0 && r.dayKey == 20260805);
  printf("   toiApplyDayRoll sentinel/roll -> ok\n");
}

static void testStateValidation() {
  printf("-- persisted state validation\n");

  CharState s = toiCharInit();
  CHECK(toiCharValid(s));

  s.form = TOI_FORM_LEAF;
  CHECK(!toiCharValid(s));  // babies can only use the baby form

  s = toiCharInit();
  s.stage = TOI_STAGE_ADULT;
  s.form = TOI_FORM_CHILD_A;
  CHECK(!toiCharValid(s));  // adults cannot use a child form

  s = toiCharInit();
  s.version = TOI_CHAR_VERSION + 1;
  CHECK(!toiCharValid(s));

  s = toiCharInit();
  s.form = TOI_FORM_RAINBOW + 1;
  CHECK(!toiCharValid(s));

  printf("   invalid stage/form, version, and form combinations rejected\n");
}

static void testLargeCounters() {
  printf("-- saturated meal counters / large kcal accumulation\n");

  CharState s = toiCharInit();
  s.cnt[TOI_CAT_VEGETABLE] = 0xFFFF;
  toiApplyFeed(s, TOI_CAT_VEGETABLE, 1000000000U, 20260804);
  CHECK(s.cnt[TOI_CAT_VEGETABLE] == 0xFFFF);
  CHECK(s.kcalDay == 1000000000U);
  CHECK(toiCharValid(s));

  toiApplyFeed(s, TOI_CAT_MEAT, 2000000000U, 20260804);
  CHECK(s.kcalDay == 3000000000U);
  CHECK(toiCharValid(s));

  printf("   counter stays at 0xFFFF; kcalDay accumulates to %u\n", s.kcalDay);
}

static void testMisc() {
  printf("-- category names and out-of-range guards\n");
  CHECK(toiCategoryFromName("vegetable") == TOI_CAT_VEGETABLE);
  CHECK(toiCategoryFromName("meat") == TOI_CAT_MEAT);
  CHECK(toiCategoryFromName("seafood") == TOI_CAT_SEAFOOD);
  CHECK(toiCategoryFromName("sweet") == TOI_CAT_SWEET);
  CHECK(toiCategoryFromName("grain") == TOI_CAT_GRAIN);
  CHECK(toiCategoryFromName("other") == TOI_CAT_OTHER);
  CHECK(toiCategoryFromName("nonsense") == TOI_CAT_OTHER);
  CHECK(toiCategoryFromName(nullptr) == TOI_CAT_OTHER);

  CharState s = toiCharInit();
  toiApplyFeed(s, 99, 10, 0);  // a bad category must land in "other"
  CHECK(s.cnt[TOI_CAT_OTHER] == 1);
  CHECK(toiCharValid(s));
  printf("   unknown category -> other, state stays valid\n");
}

int main() {
  printf("ToiCamera character_logic host tests (sizeof(CharState)=%u)\n\n",
         (unsigned)sizeof(CharState));
  testChildBranch();
  testAdultBranches();
  testAdultTiesGoToSmallerId();
  testGrainOtherExcludedFromDenominator();
  testNoDevolution();
  testDayKeySentinel();
  testStateValidation();
  testLargeCounters();
  testMisc();
  printf("\nAll %d checks passed.\n", gChecks);
  return 0;
}
