"""Cut a retail character's customization textures into 1.12 CharSections pieces.

Retail layout 121 (2048x1024) keeps the classic body sections in its left half and the face,
ears, teeth and eyes in a square on the right; retail_m2 maps that square onto the classic face
strips at (0,160)-(128,256) of the 256x256 layout. Here each retail texture is cut the same way:
the left half becomes the base skin, the face square is squeezed into the strips, its top third
becoming the "upper" texture and the rest the "lower" one.

Only ordinary player choices are carried: no Death Knight or Demon Hunter options and none that
need an unlock.
"""
import blp

SKIN, FACE, FACIAL_HAIR, HAIR, UNDERWEAR = range(5)
DK, DH = 32, 2048
TABLES = dict(option=3384247, choice=3450554, element=3512765, material=3459652, texture=982459,
              requirement=3450453, geoset=3456171)


class Customization:
    def __init__(self, tables, chr_model):
        """tables: {name: db2.Table} for TABLES."""
        self.t = tables
        self.options = {tables['option'].string(k, 0): k for k, v in tables['option'].rows.items()
                        if v[4] == chr_model}
        self.files = {}
        for fid, v in tables['texture'].rows.items():
            if v[1] == 0:
                self.files.setdefault(v[2], fid)

    def choices(self, option_name):
        """The option's ordinary player choices in display order."""
        option = self.options.get(option_name)
        if option is None:
            return []
        out = []
        for k, v in sorted(self.t['choice'].rows.items(), key=lambda kv: (kv[1][5], kv[0])):
            if v[2] != option:
                continue
            req = self.t['requirement'].rows.get(v[3])
            if req and (req[1] != 3 or req[4] or req[2] & 0xFFFFFFFF in (DK, DH)):
                continue
            out.append(k)
        return out

    def elements(self, choice):
        return [v for v in self.t['element'].rows.values() if v[0] == choice]

    def texture(self, choice, target, related=None):
        """The FileDataID a choice paints into a texture target, optionally for a related choice."""
        fallback = None
        for e in self.elements(choice):
            if not e[4] or e[4] not in self.t['material'].rows:
                continue
            mat_target, resource = self.t['material'].rows[e[4]][:2]
            if mat_target != target or resource not in self.files:
                continue
            if e[1] == related:
                return self.files[resource]
            if not e[1]:
                fallback = self.files[resource]
        return fallback

    def geoset(self, choice, group):
        for e in self.elements(choice):
            g = self.t['geoset'].rows.get(e[2])
            if g and g[0] == group:
                return group * 100 + g[1]
        return None


def level_for(data, height):
    """The first mip level at least `height` pixels tall."""
    full = int.from_bytes(data[16:20], 'little')
    level = 0
    while full >> (level + 1) >= height and level + 1 < blp.mip_count(data):
        level += 1
    return level


def strips(image):
    """A face-square texture as the classic (upper 128x32, lower 128x64) pair."""
    squeezed = blp.resize(image, 128, 96)
    return blp.crop(squeezed, 0, 0, 128, 32), blp.crop(squeezed, 0, 32, 128, 64)


class Builder:
    def __init__(self, casc, custom, race, sex, folder, prefix, hair_styles, facial_styles,
                 shared_hair=True, preserve_body_palette=False):
        """folder like Character\\BloodElf, prefix like BloodElfMale; hair_styles lists the hair
        style choice positions the converted model kept, facial_styles how many facial hair
        choices it kept."""
        self.casc, self.c = casc, custom
        self.race, self.sex, self.folder, self.prefix = race, sex, folder, prefix
        self.hair_styles, self.facial_styles = hair_styles, facial_styles
        self.shared_hair = shared_hair
        self.preserve_body_palette = preserve_body_palette
        self.files, self.rows, self.hair_geosets = {}, [], []
        self.cache = {}

    def image(self, fid, height):
        key = (fid, height)
        if key not in self.cache:
            data = self.casc.read(fid)
            self.cache[key] = blp.decode(data, level_for(data, height))
        return self.cache[key]

    def put(self, name, image):
        path = f'{self.folder}\\{name}.blp'
        self.files[path] = blp.encode(image)
        return path

    def row(self, section, variation, color, *textures):
        self.rows.append((self.race, self.sex, section, variation, color,
                          *(list(textures) + [''] * 3)[:3]))

    def build(self):
        sex_dir = self.prefix[len(self.folder.split('\\')[-1]):]
        body = f'{sex_dir}\\{self.prefix}'
        skins = self.c.choices('Skin Color')
        for color, skin in enumerate(skins):
            fid = self.c.texture(skin, 1)
            retail = self.image(fid, 256)
            w, h, _ = retail
            base = blp.resize(blp.crop(retail, 0, 0, w // 2, h), 256, 256)
            face = blp.crop(retail, w // 2, 0, w // 2, h)
            upper, lower = strips(face)
            blp.paste(base, upper, 0, 160, blend=False)
            blp.paste(base, lower, 0, 192, blend=False)
            extra = self.c.texture(skin, 2)
            extra_image = self.image(extra, 256) if extra else None
            if extra_image and self.preserve_body_palette:
                size = extra_image[1]
                extended = (size*2, size, bytearray(size*size*8))
                blp.paste(extended, blp.resize(extra_image, size, size), 0, 0, blend=False)
                blp.paste(extended, blp.resize(blp.crop(retail, 0, 0, w//2, h), size, size),
                          size, 0, blend=False)
                extra_image = extended
            self.row(SKIN, 0, color, self.put(f'{body}Skin00_{color:02d}', base),
                     self.put(f'{body}SkinExtra00_{color:02d}', extra_image) if extra else '')
            under = []
            for target, name in ((13, 'NakedPelvisSkin'), (14, 'NakedTorsoSkin')):
                fid = self.c.texture(skin, target)
                if fid:
                    under.append(self.put(f'{body}{name}00_{color:02d}', blp.resize(self.image(fid, 64), 128, 64)))
            self.row(UNDERWEAR, 0, color, *under)
            for variation, face_choice in enumerate(self.c.choices('Face')):
                fid = self.c.texture(face_choice, 5, skin)
                if not fid:
                    continue
                upper, lower = strips(self.image(fid, 96))
                self.row(FACE, variation, color,
                         self.put(f'{body}FaceLower{variation:02d}_{color:02d}', lower),
                         self.put(f'{body}FaceUpper{variation:02d}_{color:02d}', upper))

        styles = self.c.choices('Hair Style')
        colors = self.c.choices('Hair Color')
        hair = {}
        for color, choice in enumerate(colors):
            fid = self.c.texture(choice, 10)
            if fid:
                hair_name = f'Hair00_{color:02d}' if self.shared_hair else f'{body}Hair00_{color:02d}'
                hair[color] = self.put(hair_name, blp.resize(self.image(fid, 256), 256, 256))
        for variation, position in enumerate(self.hair_styles):
            style = styles[position]
            self.hair_geosets.append((variation, self.c.geoset(style, 0) or 0))
            for color, choice in enumerate(colors):
                fid = self.c.texture(style, 12, choice)
                scalp = []
                if fid:
                    upper, lower = strips(self.image(fid, 96))
                    scalp = [self.put(f'{sex_dir}\\ScalpLowerHair{variation:02d}_{color:02d}', lower),
                             self.put(f'{sex_dir}\\ScalpUpperHair{variation:02d}_{color:02d}', upper)]
                self.row(HAIR, variation, color, hair.get(color, ''), *scalp)

        facial = self.c.choices('Facial Hair')[:self.facial_styles]
        self.facial_geosets = [(v, self.c.geoset(choice, 1) or 0) for v, choice in enumerate(facial)]
        for variation in range(max(len(facial), 1)):
            for color in range(len(colors)):
                choice = facial[variation] if facial else None
                fid = (self.c.texture(choice, 8, colors[color]) or self.c.texture(choice, 8)) if choice else None
                textures = []
                if fid:
                    upper, lower = strips(self.image(fid, 96))
                    textures = [self.put(f'{body}FacialLowerHair{variation:02d}_{color:02d}', lower),
                                self.put(f'{body}FacialUpperHair{variation:02d}_{color:02d}', upper)]
                self.row(FACIAL_HAIR, variation, color, *textures)

        eye = self.c.choices('Eye Color')
        self.eye_texture = None
        if eye:
            for target in (25,):
                fid = self.c.texture(eye[0], target)
                if fid:
                    self.eye_texture = self.put(f'{self.prefix}Eyes', self.image(fid, 64))
        return self
