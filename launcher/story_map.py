"""Story map: the Story panel's Story and Dungeons buttons and their overlays.

The panel's heading is replaced by two buttons. Story opens the panel as one
wide branching map over the picker; Dungeons opens the dungeons this hero has
unlocked. Clicking the open one again, or picking another zone, closes it. The map lays every zone card on the road from the sketch:
the Horde (top) and Alliance (middle) roads merge into Stranglethorn Vale, and
the shared zones continue from there as one chain (right, down the right edge,
then back left along the bottom), joined by gold connectors.

The picker is Bevy UI (taffy flexbox), built once and rebuilt when the hero
changes. Node fields used here (0x180-byte Node, Val = u32 tag + f32; tags
0 Auto, 1 Px, 2 Percent, 3 Vw, 4 Vh): +0x60 flex basis, +0x68 left, +0x70
right, +0x78 top, +0x80 bottom, +0x88 width, +0x90 height, +0x98..+0xb0
min/max sizes, +0x173 position type (1 = absolute).

Opening: the buttons come from the picker's own button helper (0x23dc40, as
for Armory and Talents) with the zone-pick Action (tag 1) and the IDs
"story-map" / "dungeon-map". The zone lookup resolves those IDs to the last
picked zone, so nothing sees an unknown zone; the picker's rebuild hook
(story_chapters) sees the ID, sets the overlay and puts the real zone back.
"""
import struct
import json
from pathlib import Path
from durotar_patch import Code

TOGGLE_ID = b'story-map'
DUNGEON_ID = b'dungeon-map'
STORY, DUNGEONS = 1, 2                             # overlay state values
VW, VH, PX, PCT = 3, 4, 1, 2
COLS = (0.0, 12.3, 24.6, 36.9, 49.2, 61.5, 73.8)   # vw from the card list's left edge
ROWS = (0.5, 14.5, 28.5, 42.5)                     # vh from its top
CARD_W, CARD_H = 11.3, 12.0
DUNGEON_W, DUNGEON_H = 26.0, 26.0                  # the Dungeons overlay's cards
DUNGEON_X, DUNGEON_Y = (14.0, 46.0), 6.0
OFFSCREEN = -1000.0
LINE = 3.0                                         # px
GOLD = (0.69, 0.541, 0.227, 0.9)
BACKDROP = (0.045, 0.035, 0.025, 1.0)
# The shared zones after Stranglethorn: (column, row) in chain order.
CHAIN = ((5, 1), (6, 1), (6, 2), (6, 3), (5, 3), (4, 3), (3, 3), (2, 3), (1, 3), (0, 3))

# Native sites (race-expansion base).
COLUMN = 0x28c817           # Story column: before its Node is spawned (Node at rsp+0x40)
CARD = 0x20b327             # zone loop: card frame Node at r14, record at rdi
SELECTED = 0x20b3f9         # r13b = selected (expanded content)
LIST_NODE = 0x20af40        # card list Node at rbp+0x3b8, before it is spawned
LIST_HEIGHT = 57.0          # vh: the overlays' card list; the buttons keep their size
LIST_START = 0x20af90       # card list spawner ready (rbp+8), before the first card
LIST_END = 0x20bf76         # after the last card
HEADING = 0x20aa48          # heading row spawn (rbp+0x60 = column spawner, r15 = fonts)
HEADING_END = 0x20aa6f
BUTTON = 0x23dc40           # (fonts, spawner, &Action, title, len, &subtitle, lit)
RULE = 0x1e3950             # heading rule: its Node at rsp+0x50
CATALOG_SLICE = 0x85f26c8   # -> (records, count)
RULE_BUNDLE, SPAWN = 0x110f10, 0x187c90
BUTTONS = (('Story', 'The road so far', TOGGLE_ID, STORY), ('Dungeons', 'Unlocked dungeons', DUNGEON_ID, DUNGEONS))
HEADER_HEIGHT = 6.5
TAB_WIDTH = 20.0
# These two sibling panels are rebuilt on every selection. Do not spawn their
# interactive descendants while the map occupies their screen area.
COVERED_PANELS = ((0x20cdc9, 0x289570), (0x20cde3, 0x28d780))
TAB_NODE = 0x23df36        # button Node at rbp+0x280; r14 still points to its Action


def rule_template(image):
    """The native rule Node, independent of whether another heading was drawn."""
    profile = json.loads(Path(__file__).with_name('native-story-map.json').read_text())
    for source in profile['sources']:
        expected = bytes.fromhex(source['bytes'])
        if image.read(source['rva'], len(expected)) != expected:
            raise ValueError('Unsupported native map rule constructor')
    return bytes.fromhex(profile['node'])


def layout(horde, alliance, stv, shared):
    """Zone index -> (left vw, top vh)."""
    spots = {z: (COLS[k], ROWS[0]) for k, z in enumerate(horde)}
    spots.update({z: (COLS[k], ROWS[2]) for k, z in enumerate(alliance)})
    spots[stv] = (COLS[4], ROWS[1])
    for z, (c, r) in zip(shared, CHAIN):
        spots[z] = (COLS[c], ROWS[r])
    return spots


def connectors(spots, horde, alliance, stv, shared):
    """Absolute rects (left, top, width, height as (tag, value)) joining consecutive cards."""
    W, H = CARD_W, CARD_H
    segs = []

    def hline(x1, x2, y):
        segs.append(((VW, min(x1, x2)), (VH, y), (VW, abs(x2-x1)), (PX, LINE)))

    def vline(x, y1, y2):
        segs.append(((VW, x), (VH, min(y1, y2)), (PX, LINE), (VH, abs(y2-y1))))

    def link(a, b):
        (xa, ya), (xb, yb) = spots[a], spots[b]
        if ya == yb:
            hline(xa+W, xb, ya+H/2) if xb > xa else hline(xb+W, xa, ya+H/2)
        elif xa == xb:
            vline(xa+W/2, ya+H, yb) if yb > ya else vline(xa+W/2, yb+H, ya)
        else:  # elbow: out of a's side, then into b's top or bottom
            hline(xa+W, xb+W/2, ya+H/2)
            vline(xb+W/2, ya+H/2, yb if yb > ya else yb+H)
    for road in (horde, alliance):
        for a, b in zip(road, road[1:]):
            link(a, b)
        link(road[-1], stv)
    chain = (stv, *shared)
    for a, b in zip(chain, chain[1:]):
        link(a, b)
    return segs


def rect_table(rects):
    return b''.join(struct.pack('<IfIfIfIf', *(v for pair in r for v in pair)) for r in rects)


def install(image, state, horde, alliance, stv, order, dungeons, mask):
    """state['open']: u8, 0 closed, STORY or DUNGEONS. mask: the open-zone mask (u32)."""
    opened = state['open']
    shared = [z for z in order if z not in (*horde, *alliance, stv)]
    spots = layout(horde, alliance, stv, shared)
    count = max(spots)+1
    story_cards, dungeon_cards = bytearray(16*count), bytearray(16*count)
    for z in range(count):
        struct.pack_into('<4f', story_cards, 16*z, *spots[z], CARD_W, CARD_H)
        struct.pack_into('<4f', dungeon_cards, 16*z, OFFSCREEN, 0.0, CARD_W, CARD_H)
    for k, z in enumerate(dungeons):
        struct.pack_into('<4f', dungeon_cards, 16*z, DUNGEON_X[k], DUNGEON_Y, DUNGEON_W, DUNGEON_H)
    story_cards = image.put(bytes(story_cards), 16)
    dungeon_cards = image.put(bytes(dungeon_cards), 16)
    hidden = image.put(struct.pack('<4f', OFFSCREEN, 0.0, CARD_W, CARD_H), 16)
    lines = connectors(spots, horde, alliance, stv, shared)
    line_table = image.put(rect_table(lines), 16)
    backdrop = image.put(rect_table([((PCT, -2.0), (PCT, -2.0), (PCT, 104.0), (PCT, 104.0))]), 16)
    gold = image.put(struct.pack('<I4f', 0, *GOLD), 16)
    dark = image.put(struct.pack('<I4f', 0, *BACKDROP), 16)
    template = image.put(rule_template(image), 16)
    node = image.put(bytes(0x180), 16)
    bundle = image.put(bytes(0x400), 16)
    spawned = image.put(bytes(0x100), 16)

    def gate(code, label):
        return code.rel('803d', opened, '00').jcc('e', label)

    def val(code, base, tag, value):
        code.raw('c78424'+struct.pack('<I', base).hex()+struct.pack('<I', tag).hex())
        code.raw('c78424'+struct.pack('<I', base+4).hex()+struct.pack('<f', value).hex())

    for site, target in COVERED_PANELS:
        before = b'\xe8'+struct.pack('<i', target-site-5)
        code = Code().rel('803d', opened, '00').jcc('ne', 'covered')
        image.hook(site, before, code.rel('e8', target).label('covered').jmp(site+5))

    # The Story column becomes an absolute overlay across the panels.
    before = image.read(COLUMN, 8)
    if before != bytes.fromhex('488d8c24c8010000'):
        raise ValueError('Unsupported native Story column')
    code = gate(Code(), 'native').raw('c68424'+struct.pack('<I', 0x40+0x173).hex()+'01')
    for off in (0x68, 0x70, 0x78, 0x80):
        val(code, 0x40+off, PCT, 1.0)
    image.hook(COLUMN, before, code.label('native').raw(before).jmp(COLUMN+8))

    # Each zone card at its overlay spot (x, y, width, height). The Dungeons
    # overlay shows only unlocked dungeons; every other card goes off-screen.
    before = image.read(CARD, 6)
    if before != bytes.fromhex('41b880010000'):
        raise ValueError('Unsupported native zone card')
    code = gate(Code(), 'native').raw('505152').rel('488b05', CATALOG_SLICE).raw('488b00')
    code.raw('4889f94829c148c1e904')                                  # rcx = (record - catalog) / 16 = 15 * zone
    code.raw('4869c912110000').raw('48c1e910')                        # rcx = zone
    code.raw('4883f9'+bytes([count]).hex()).jcc('ae', 'skip')
    code.raw('4889ca48c1e204')                                        # rdx = 16 * zone
    code.rel('488d05', story_cards).raw('4801d0')
    code.rel('803d', opened, bytes([STORY]).hex()).jcc('e', 'place')
    code.rel('488d05', dungeon_cards).raw('4801d0')
    code.rel('0fa30d', mask).jcc('b', 'place')                        # unlocked: its own spot
    code.rel('488d05', hidden)
    code.label('place').raw('41c6867301000001')
    code.raw('41c74668'+struct.pack('<I', VW).hex()).raw('8b0841894e6c')
    code.raw('41c74678'+struct.pack('<I', VH).hex()).raw('8b480441894e7c')
    code.raw('41c78688000000'+struct.pack('<I', VW).hex()).raw('8b4808' '41898e8c000000')
    code.raw('41c78690000000'+struct.pack('<I', VH).hex()).raw('8b480c' '41898e94000000')
    code.label('skip').raw('5a5958').label('native').raw(before).jmp(CARD+6)
    image.hook(CARD, before, code)

    # The selected card keeps its gold frame but shows the compact content.
    before = image.read(SELECTED, 7)
    if before != bytes.fromhex('4489ad70060000'):
        raise ValueError('Unsupported native selected card')
    image.hook(SELECTED, before, gate(Code(), 'native').raw('4531ed').label('native').raw(before).jmp(SELECTED+7))

    # The heading row becomes the Story and Dungeons buttons; the open one is lit.
    before = image.read(HEADING, 9)
    if before != bytes.fromhex('4c89e94889fa4d89f0'):
        raise ValueError('Unsupported native Story heading')
    # Keep the native heading row as the tabs' parent. Spawning into the whole
    # column made two full-width rows and left the original controls underneath.
    code = Code().raw(before).rel('e8', 0x183b50).raw('4883ec40')
    tab_actions = []
    for title, subtitle, ident, value in BUTTONS:
        action = image.put(struct.pack('<QQQ', 1, 0, len(ident)), 8)       # Action: zone pick, ID
        tab_actions.append(action)
        image.pointer(action+8, image.put(ident, 1))
        sub = image.put(struct.pack('<QQQ', 0, 0, len(subtitle)), 8)       # static String: capacity 0
        image.pointer(sub+8, image.put(subtitle.encode(), 1))
        text = title.encode()
        code.raw('31c0').rel('803d', opened, bytes([value]).hex()).raw('0f94c0').raw('4889442430')
        code.rel('488d05', sub).raw('4889442428').raw('48c7442420'+struct.pack('<I', len(text)).hex())
        code.rel('4c8d0d', image.put(text, 1)).rel('4c8d05', action).raw('488d95500300004c89f9').rel('e8', BUTTON)
    code.raw('4883c440').raw('4c89bdd0050000')                       # as natively: rbp+0x5d0 = r15
    image.hook(HEADING, before, code.jmp(HEADING_END))

    # Apply compact sizing only to our two static Actions; all other native
    # buttons retain their original dimensions, text and interaction behavior.
    before = bytes.fromhex('4c8d75d8488d9580020000')
    code = Code().raw('50')
    for action in tab_actions:
        code.rel('488d05', action).raw('4939c6').jcc('e', 'tab')
    code.jmp('done').label('tab')
    def widths(tag, value):
        for off in (0x60, 0x88, 0x98, 0xa8):
            code.raw('c785'+struct.pack('<I', 0x280+off).hex()+struct.pack('<I', tag).hex())
            code.raw('c785'+struct.pack('<I', 0x284+off).hex()+struct.pack('<f', value).hex())
    widths(VW, TAB_WIDTH)
    for off, tag, value in ((0x90, VH, HEADER_HEIGHT),
                            (0xa0, VH, HEADER_HEIGHT), (0xb0, VH, HEADER_HEIGHT)):
        code.raw('c785'+struct.pack('<I', 0x280+off).hex()+struct.pack('<I', tag).hex())
        code.raw('c785'+struct.pack('<I', 0x284+off).hex()+struct.pack('<f', value).hex())
    code.raw('48c785c803000000000000')  # flex_grow / flex_shrink = 0
    image.hook(TAB_NODE, before, code.label('done').raw('58').raw(before).jmp(TAB_NODE+len(before)))

    def spawn_rects(code, table, count, paint, label):
        """Spawn count absolute rects into the card list (rbp+8 spawner, head [rbp+0x338])."""
        code.rel('4c8d25', table).raw('bb'+struct.pack('<I', count).hex())
        code.label(label).rel('488d3d', node).rel('488d35', template).raw('b980010000f3a4')
        code.rel('c605', node+0x173, '01')
        for off in (0x60, 0x98, 0xa0, 0xa8, 0xb0):
            code.rel('48c705', node+off, '00000000')
        for k, off in enumerate((0x68, 0x78, 0x88, 0x90)):
            code.raw('498b4424'+bytes([8*k]).hex()).rel('488905', node+off)
        code.rel('488d0d', bundle+8).rel('488d15', node).rel('4c8d05', paint).rel('e8', RULE_BUNDLE)
        code.raw('498b442418').rel('488905', bundle+8+0x90)      # the rule forces 1px: real height
        code.rel('488b05', bundle+8+0x188).raw('488b4010')        # its gradient: all stops solid
        code.raw('0f10402c0f11400c0f11404c')
        code.raw('488b8538030000').rel('488905', bundle)
        code.rel('488d0d', spawned).raw('488d5508').rel('4c8d05', bundle).rel('e8', SPAWN)
        code.raw('4983c420ffcb').jcc('ne', label)

    # In an overlay the card list gets a fixed height, so the buttons above it
    # keep their list-view size instead of sharing the overlay's height.
    before = image.read(LIST_NODE, 7)
    if before != bytes.fromhex('4889bdb0030000'):
        raise ValueError('Unsupported native card list node')
    code = gate(Code(), 'native').raw('c785'+struct.pack('<I', 0x3b8+0x90).hex()+struct.pack('<I', VH).hex())
    code.raw('c785'+struct.pack('<I', 0x3b8+0x94).hex()+struct.pack('<f', LIST_HEIGHT).hex())
    image.hook(LIST_NODE, before, code.label('native').raw(before).jmp(LIST_NODE+7))

    # Backdrop under the cards.
    before = image.read(LIST_START, 7)
    if before[:3] != bytes.fromhex('488b05'):
        raise ValueError('Unsupported native card list')
    code = gate(Code(), 'native').raw('53565741544883ec20')
    spawn_rects(code, backdrop, 1, dark, 'backdrop')
    code.raw('4883c420415c5f5e5b').label('native').rel('488b05', CATALOG_SLICE).jmp(LIST_START+7)
    image.hook(LIST_START, before, code)

    # After the cards: the Story overlay's connectors.
    before = image.read(LIST_END, 7)
    if before != bytes.fromhex('488b9590000000'):
        raise ValueError('Unsupported native card list end')
    code = Code().rel('803d', opened, bytes([STORY]).hex()).jcc('ne', 'native').raw('53565741544883ec20')
    spawn_rects(code, line_table, len(lines), gold, 'line')
    code.raw('4883c420415c5f5e5b').label('native').raw(before).jmp(LIST_END+7)
    image.hook(LIST_END, before, code)
    return dict(spots=spots, lines=lines, story_cards=story_cards, dungeon_cards=dungeon_cards)
