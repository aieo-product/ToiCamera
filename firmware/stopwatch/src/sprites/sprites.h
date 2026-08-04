// Sprite aggregator — symbol contract is FIXED (form ids 0..7, 4 frames each).
// Frame data files are regenerated from art; this table layout must not change.
#ifndef TOI_SPRITES_H
#define TOI_SPRITES_H
#include <pgmspace.h>

#include "baby.h"
#include "child_a.h"
#include "child_b.h"
#include "adult_leaf.h"
#include "adult_muscle.h"
#include "adult_marine.h"
#include "adult_candy.h"
#include "adult_rainbow.h"

static const int TOI_SPR_SIZE = 32;
static const uint8_t TOI_SPR_TRANSPARENT = 0xE3;

struct ToiSpriteSet {
  const uint8_t *idle_a;
  const uint8_t *idle_b;
  const uint8_t *eat;
  const uint8_t *happy;
};

// index = form id: 0=baby 1=child_a 2=child_b 3=leaf 4=muscle 5=marine 6=candy 7=rainbow
static const ToiSpriteSet TOI_SPRITES[8] = {
  { SPR_BABY_IDLE_A, SPR_BABY_IDLE_B, SPR_BABY_EAT, SPR_BABY_HAPPY },
  { SPR_CHILD_A_IDLE_A, SPR_CHILD_A_IDLE_B, SPR_CHILD_A_EAT, SPR_CHILD_A_HAPPY },
  { SPR_CHILD_B_IDLE_A, SPR_CHILD_B_IDLE_B, SPR_CHILD_B_EAT, SPR_CHILD_B_HAPPY },
  { SPR_ADULT_LEAF_IDLE_A, SPR_ADULT_LEAF_IDLE_B, SPR_ADULT_LEAF_EAT, SPR_ADULT_LEAF_HAPPY },
  { SPR_ADULT_MUSCLE_IDLE_A, SPR_ADULT_MUSCLE_IDLE_B, SPR_ADULT_MUSCLE_EAT, SPR_ADULT_MUSCLE_HAPPY },
  { SPR_ADULT_MARINE_IDLE_A, SPR_ADULT_MARINE_IDLE_B, SPR_ADULT_MARINE_EAT, SPR_ADULT_MARINE_HAPPY },
  { SPR_ADULT_CANDY_IDLE_A, SPR_ADULT_CANDY_IDLE_B, SPR_ADULT_CANDY_EAT, SPR_ADULT_CANDY_HAPPY },
  { SPR_ADULT_RAINBOW_IDLE_A, SPR_ADULT_RAINBOW_IDLE_B, SPR_ADULT_RAINBOW_EAT, SPR_ADULT_RAINBOW_HAPPY },
};

#endif // TOI_SPRITES_H
