# Added race passives

Each added race has three permanent ASR traits. The original nine races are unchanged.
All borrowed active abilities are removed from added races. Values and descriptions
are emitted from the same definitions in `launcher/race_racials.py`.

These are ASR adaptations, not retail spell effects. In particular, a named
damage-school resistance here reduces all damage; damage, experience and movement
bonuses are unconditional; regeneration runs continuously. No gathering, pet,
critical-damage, reactive-heal or teleport mechanic is claimed.

| Race | Passive effects |
|---|---|
| Worgen | Viciousness: +3% critical strike chance; Running Wild: +8% movement speed; Aberration: +4% damage reduction |
| Kul Tiran | Brush It Off: +0.8 health per second; Rime of the Ancient Mariner: +5% damage reduction; Jack of All Trades: +10% luck |
| Draenei | Heroic Presence: +6% damage; Gift of the Naaru: +1 health per second; Shadow Resistance: +4% damage reduction |
| Earthen | Titan-Wrought Frame: +6% damage reduction; Ingest Minerals: +8% max health; Wide-Eyed Wonder: +12% experience |
| Dark Iron Dwarf | Forged in Flames: +5% damage reduction; Dungeon Delver: +6% movement speed; Mass Production: -5% cooldowns |
| Lightforged Draenei | Demonbane: +7% damage; Holy Providence: +1 health per second; Forge of Light: +8% max health |
| Void Elf | Entropic Embrace: +8% damage; Preternatural Calm: -6% cooldowns; Chill of Night: +4% damage reduction |
| Mechagnome | Combat Analysis: +6% damage; Re-Arm: +1.2 health per second; Skeleton Pinkie: +15% gold |
| Dracthyr | Awakened: +3% critical strike chance; Discerning Eye: +25% pickup range; Glide: +8% movement speed |
| Haranir | Subterranean Predator: +10% experience; Lash Out: +3% critical strike chance; One with Nature: +25% pickup range |
| Nightborne | Magical Affinity: +8% damage; Ancient History: +8% experience; Arcane Resistance: +4% damage reduction |
| Highmountain Tauren | Rugged Tenacity: +6% damage reduction; Mountaineer: +10% max health; Waste Not, Want Not: +15% gold |
| Mag'har Orc | Ancestral Call: +6% damage; Savage Blood: +5% damage reduction; Sympathetic Vigor: +10% max health |
| Zandalari Troll | Embrace of Pa'ku: +3% critical strike chance; City of Gold: +20% gold; Regeneratin': +1 health per second |
| Vulpera | Nose for Trouble: +5% damage reduction; Alpaca Saddlebags: +35% pickup range; Bag of Tricks: +15% luck |
| Pandaren | Epicurean: +12% max health; Inner Peace: +10% experience; Bouncy: +5% damage reduction |
| Goblin | Time is Money: -7% cooldowns; Best Deals Anywhere: +20% gold; Better Living Through Chemistry: +0.8 health per second |

## Verification

The tests map the native executable and execute the original passive dispatcher
(RVA `0x5be93fd`) and all twelve effect cases. Each race is tested against its
actual embedded passive array, including numerical results. The tests also
verify that added races have no inherited active ability, every locale describes
the same applied effects, and the original nine race effects are unchanged.

The legacy UI requires an ability definition even to draw a racial icon. An
empty active ID now resolves to a compatibility slot with no spell, power,
radius, duration or secondary effect and a disabled practical cooldown. This
covers both ordinary and inlined ability lookups without borrowing a racial
attack. Nonempty ability lookups retain their original behavior. A native
regression test covers both paths, including verification of the original
War Stomp spell ID.

The build refuses to silently reuse an expanded executable with stale racial
mechanics: rebuild from the frozen baseline. Existing saves retain their race IDs;
the current race definition supplies the new passive kit at runtime.

A native Haranir/Goblin localhost co-op run joined and entered gameplay with the
new definitions. Test artifacts are under `downloads/race-expansion/racials/coop/`.
This is a startup smoke test, not a full-match balance or Internet soak test.

## Racial-theme references

- [Blizzard: Worgen and Goblin](https://worldofwarcraft.blizzard.com/en-us/news/24080626)
- [Blizzard: Kul Tiran and Zandalari](https://worldofwarcraft.blizzard.com/en-us/news/22882888)
- [Blizzard: Mag’har and Dark Iron](https://worldofwarcraft.blizzard.com/en-us/news/21701413/preview-maghar-orcs-and-dark-iron-dwarves)
- [Blizzard: Mechagnome and Vulpera](https://worldofwarcraft.blizzard.com/en-us/news/23177594)
- [Blizzard: Allied races](https://worldofwarcraft.blizzard.com/en-us/news/21498532)
- [Blizzard: Earthen](https://news.blizzard.com/en-gb/article/24104276/meet-the-earthen-a-new-playable-allied-race)
- [Blizzard: Haranir](https://worldofwarcraft.blizzard.com/en-us/news/24264009)

Names are racial-theme references. ASR numerical values and substitutions are
local gameplay design decisions, not claims about retail balance.
