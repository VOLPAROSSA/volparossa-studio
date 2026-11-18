"""Build the static Studio product site under its GitHub Pages project path."""
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path

from objects import browser, editor, phone, picture, poster

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
THEME = ROOT / 'vendor/volparossa-theme'


def render(template, values):
    return re.sub(r'{{(\w+)}}', lambda match: values[match[1]], template)


def read_json(path):
    return json.loads(path.read_text())


def link_arrow(direction):
    paths = {'external': 'M4 13 13 4M5 4h8v8', 'next': 'M2 8h12m-5-5 5 5-5 5', 'back':'M14 8H2m5-5L2 8l5 5'}
    return (f'<svg class="link-direction" aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" '
            f'fill="none" stroke="currentColor" stroke-width="1.45"><path d="{paths[direction]}"/></svg>')


def theme_values(config):
    inventory = read_json(THEME / 'theme-version.json')
    if inventory['source_commit'] != config['theme_commit']:
        raise ValueError('Unexpected shared theme revision')
    for name, digest in inventory['files'].items():
        if hashlib.sha256((THEME / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Shared theme checksum mismatch: {name}')
    spec = importlib.util.spec_from_file_location('navigation', THEME / 'shared/navigation.py')
    navigation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(navigation)
    nav = read_json(THEME / 'data/navigation.json')
    links = navigation.site_links(nav, read_json(THEME / 'data/projects.json'), 'https://volparossa.org/')
    github = (THEME / 'assets/icons/github.svg').read_text().replace('<svg ', '<svg class="github-icon" aria-hidden="true" ', 1)
    for group, key in [('main', 'nav_links'), ('footer', 'footer_links')]:
        links[key] = navigation.navigation_links(nav[group], links, 'applications', github, footer=group == 'footer')
        links[key] = links[key].replace(' ↗</a>', ' ' + link_arrow('external') + '</a>')
    return {**links, 'github_icon': github, 'external_arrow':link_arrow('external'),
            'next_arrow':link_arrow('next'), 'back_arrow':link_arrow('back')}


def components():
    inventory = read_json(SRC / 'art.json')
    def workshop(eager=False):
        return picture('workshop', inventory, '(max-width:600px) 230px, 300px', alt='Daylight on an empty ceramics workbench.', eager=eager)
    hero_page, example = poster(workshop(True)), poster(workshop())
    return dict(wall_picture=picture('wall', inventory, '100vw', mobile=True, eager=True),
                closing_picture=picture('wall', inventory, '100vw', mobile=True),
                fox_picture=picture('fox', inventory, '115px', eager=True),
                maker_picture=picture('maker', inventory, '230px'),
                reviewer_picture=picture('reviewer', inventory, '230px'),
                workshop_picture=workshop(), poster=hero_page, closing_poster=example,
                hero_editor=editor(hero_page), workflow_editor=editor(example, detail=True),
                phone=phone(example), browser_preview=browser(example))


def build(output, production):
    config = read_json(SRC / 'content.json')
    canonical = config['canonical']
    shared = theme_values(config)
    output = output.resolve()
    marker = output / '.studio-site-build'
    if output.exists() and any(output.iterdir()):
        if not marker.is_file():
            raise ValueError('Choose an empty directory or an existing Studio site build.')
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    marker.touch()
    (output / '.nojekyll').touch()
    shutil.copytree(ROOT / 'assets', output / 'assets')
    for name in ['site.css', 'tokens.css', 'site.js', 'logo.png', 'favicon.png']:
        shutil.copy2(THEME / 'assets' / name, output / 'assets' / name)
    for name in ['fonts', 'icons']:
        shutil.copytree(THEME / 'assets' / name, output / 'assets' / name)
    for name in ['studio.css', 'studio-objects.css']:
        shutil.copy2(SRC / name, output / 'assets' / name)
    for name in ['LICENSE', 'favicon.ico']:
        shutil.copy2(THEME / name, output / name)
    all_values = {**shared, **config, **components(), 'body_class':'studio-page',
                  'social_image':canonical + 'assets/studio/social.jpg'}
    for slug, name in [('', 'index'), ('credits/', 'credits')]:
        root = '../' if slug else ''
        values = {**all_values, 'root':root, 'canonical':canonical + slug}
        if slug:
            values['title'] = 'Sources and credits · VOLPAROSSA Studio'
        robots = 'index,follow' if production else 'noindex,nofollow'
        values['head_extra'] = (f'<meta name="robots" content="{robots}"><meta property="og:locale" content="en_GB">'
                                f'<link rel="stylesheet" href="{root}assets/studio.css">'
                                f'<link rel="stylesheet" href="{root}assets/studio-objects.css">')
        for part in ['header', 'footer']:
            values[part] = render((THEME / f'templates/{part}.html').read_text(), values)
        values['content'] = render((SRC / f'{name}.html').read_text(), values)
        folder = output / slug
        folder.mkdir(exist_ok=True)
        (folder / 'index.html').write_text(render((THEME / 'templates/layout.html').read_text(), values))
    if production:
        items = ''.join(f'<url><loc>{canonical}{path}</loc></url>' for path in ['', 'credits/'])
        (output / 'sitemap.xml').write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>\n')
    print('Built', 'production site' if production else 'noindex preview', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'preview/volparossa-studio')
    parser.add_argument('--production', action='store_true')
    options = parser.parse_args()
    build(options.output, options.production)
