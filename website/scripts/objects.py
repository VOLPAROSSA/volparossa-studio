"""The same sample project presented on paper, in the editor, on a phone and in a browser."""
from html import escape


def picture(name, inventory, sizes, *, alt='', eager=False, mobile=False):
    def sources(key):
        return ', '.join(f'assets/studio/{key}-{w}.webp {w}w' for w, _ in inventory[key]['frames'])
    info = inventory[name]
    w, h = info['fallback']
    load = 'loading="eager"' if eager else 'loading="lazy" decoding="async"'
    markup = ['<picture>']
    if mobile:
        markup += [f'<source media="(max-width:900px)" type="image/webp" srcset="{sources("wall-mobile")}" sizes="100vw">',
                   '<source media="(max-width:900px)" srcset="assets/studio/wall-mobile.jpg">']
    markup += [f'<source type="image/webp" srcset="{sources(name)}" sizes="{sizes}">',
               f'<img src="assets/studio/{name}.{info["ext"]}" width="{w}" height="{h}" alt="{escape(alt, quote=True)}" {load}></picture>']
    return ''.join(markup)


def poster(art):
    return f'''<div class="studio-poster">
      <div class="poster-print">
        <div class="poster-graphic">
          <span class="poster-sun" aria-hidden="true"></span>
          <strong class="poster-title"><span>Open</span> <span>Studio</span> <span>Saturday</span></strong>
        </div>
        <p class="poster-subtitle">A craft studio open to all.</p>
        {art}
        <div class="poster-programme">
          <p><span>10:00 to 12:00</span> · <span>Studio tour</span></p>
          <p><span>14:00 to 16:00</span> · <span>Make &amp; share</span></p>
        </div>
      </div>
    </div>'''


def editor(page, *, detail=False):
    variant = 'editor-detail' if detail else 'editor-overview'
    layers = ''.join(f'<li class="layer-{key}"><i aria-hidden="true">{icon}</i>{label}</li>' for key, icon, label in [
        ('page', '◇', 'Page'), ('header', '▱', 'Header'), ('heading', 'T', 'Heading'), ('photo', '▧', 'Photo'),
        ('programme', '☷', 'Programme'), ('background', '▦', 'Background')])
    return f'''<div class="silex-editor {variant}" aria-label="Illustration of the Silex editor" role="group">
        <div class="editor-chrome"><div class="editor-brand"><img src="assets/studio/silex-picto.png" width="20" height="20" alt=""> Silex</div>
        <span class="editor-document">Open Studio Saturday</span>
        <svg class="editor-tools" viewBox="0 0 100 16" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.4"><path d="M1 4l5 4-5 4zM22 5h8v6h-8zM23 3h6M43 8c3-5 7-5 10 0-3 5-7 5-10 0z"/><circle cx="48" cy="8" r="1.5"/><path d="m67 4 4 8 4-8m13 6 3 3 7-9"/></g></svg></div>
        <div class="editor-body">
          <div class="editor-layers"><strong>Layers</strong><ul>{layers}</ul></div>
          <div class="editor-stage">{page}</div>
          <div class="editor-inspector"><strong>Typography</strong>
            <div class="inspector-field"><span>Font</span><b>Cormorant</b></div>
            <div class="inspector-field editor-text-size"><span>Size</span><b>37 px</b></div>
            <div class="inspector-field"><span>Weight</span><b>Semibold</b></div>
            <div class="inspector-field"><span>Line height</span><b>1.0</b></div>
          </div>
        </div>
    </div>'''


def phone(page):
    return f'<div class="phone-mockup" role="group" aria-label="The poster on a phone"><div class="phone-glass"><i class="phone-camera" aria-hidden="true"></i>{page}</div></div>'


def browser(page):
    return f'<div class="browser-preview" role="group" aria-label="Browser preview of the poster"><div class="browser-chrome" aria-hidden="true"><i></i><i></i><i></i><span>Open Studio Saturday</span></div>{page}</div>'
