"""Check the generated Studio product site without running the editor or using the network."""

import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent.parent
HOME = 'https://volparossa.org/'
CANONICAL = f'{HOME}volparossa-studio/'
PROJECT = 'https://github.com/VOLPAROSSA/volparossa-studio'
EVIDENCE = f'{PROJECT}/blob/main/docs/IMPLEMENTATION_STATUS.md'
TITLE = 'VOLPAROSSA Studio · Your canvas. Your website.'
DESCRIPTION = ('Explore visual website editing with Silex, portable ZIP export and '
               'VOLPAROSSA’s plans for shared AI and cooperative hosting.')
SECTIONS = {
    'studio-hero': 'Your canvas. Your website.',
    'studio-workflow': 'Begin on the canvas.',
    'studio-export': 'Preview it. Take it with you.',
    'studio-ai': 'A second pair of eyes on your design.',
    'studio-selection': 'Choose what goes public.',
    'studio-publish': 'Publish a version.',
    'studio-development': 'What works today. What comes next.',
    'studio-closing': 'Help shape the next version of Studio.',
}
POSTER_COPY = ('Open Studio Saturday', 'A craft studio open to all.', '10:00 to 12:00',
               'Studio tour', '14:00 to 16:00', 'Make & share')
PEERS = {'A': 'North Studio', 'B': 'Print Room', 'C': 'Courtyard', 'D': 'East Studio'}
EDGES = {'A-B', 'B-C', 'C-D', 'A-D', 'A-C'}
VOID_TAGS = set('area base br col embed hr img input link meta param source track wbr'.split())
CSS_URL = re.compile(r'''url\(\s*(['"]?)([^'"\s)]+)\1\s*\)''', re.IGNORECASE)


class Element:
    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.words = []

    @property
    def text(self):
        return ' '.join(' '.join(self.words).split())

    def has_class(self, class_name):
        return class_name in self.attrs.get('class', '').split()

    def find(self, tag=None, *, class_name=None):
        matches = []
        for child in self.children:
            if (tag is None or child.tag == tag) and (class_name is None or child.has_class(class_name)):
                matches.append(child)
            matches.extend(child.find(tag, class_name=class_name))
        return matches


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.document = Element(None, [])
        self.stack = [self.document]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        element = Element(tag, attrs)
        self.stack[-1].children.append(element)
        if tag not in VOID_TAGS:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Element(tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        for element in self.stack:
            element.words.append(data)


def ids(page):
    found = [item.attrs['id'] for item in page.find() if 'id' in item.attrs]
    assert len(found) == len(set(found)), 'Duplicate IDs'
    return set(found)


def asset_path(output, page, reference):
    path = unquote(urlsplit(reference).path)
    assert path and not path.startswith('/'), f'Expected a project-relative path: {reference}'
    target = (page.parent / path).resolve()
    assert target.is_relative_to(output), f'Path escapes generated site: {reference}'
    if target.is_dir():
        target /= 'index.html'
    assert target.is_file(), f'Missing {reference} in {page.relative_to(output)}'
    return target


def check_references(output, pages):
    anchors = {path: ids(page) for path, page in pages.items()}
    for path, page in pages.items():
        for item in page.find():
            attrs = item.attrs
            for attribute in ('aria-labelledby', 'aria-describedby'):
                assert set(attrs.get(attribute, '').split()) <= anchors[path], f'Invalid {attribute} on {item.tag}'
            if item.tag == 'link' and attrs.get('rel') == 'canonical':
                continue
            values = [(key, attrs[key]) for key in ('href', 'src') if key in attrs]
            values += [('srcset', part.split()[0]) for part in attrs.get('srcset', '').split(',') if part.strip()]
            for attribute, value in values:
                url = urlsplit(value)
                if url.scheme or url.netloc:
                    assert item.tag == 'a' and attribute == 'href' and url.scheme == 'https', f'Off-site resource: {value}'
                    continue
                target = asset_path(output, path, value) if url.path else path
                if url.fragment and target in anchors:
                    assert unquote(url.fragment) in anchors[target], f'Missing fragment: {value}'
            if item.tag == 'img':
                assert 'alt' in attrs, 'Image missing alt attribute'
                assert int(attrs.get('width', 0)) > 0 and int(attrs.get('height', 0)) > 0, attrs.get('src')
    for stylesheet in output.rglob('*.css'):
        for _, value in CSS_URL.findall(stylesheet.read_text(encoding='utf-8')):
            url = urlsplit(value)
            assert not url.scheme and not url.netloc, f'Off-site CSS resource: {value}'
            if url.path:
                asset_path(output, stylesheet, value)


def check_head(output, path, page, production):
    head, = page.find('head')
    html, = page.find('html')
    assert html.attrs.get('lang') == 'en'
    meta = {node.attrs.get('name') or node.attrs.get('property'): node.attrs.get('content')
            for node in head.find('meta')}
    canonical = CANONICAL + ('credits/' if path.parent != output else '')
    assert [link.attrs['href'] for link in head.find('link') if link.attrs.get('rel') == 'canonical'] == [canonical]
    assert meta.get('robots') == ('index,follow' if production else 'noindex,nofollow')
    if path.parent == output:
        assert [node.text for node in head.find('title')] == [TITLE]
        for name, expected in {
            'description': DESCRIPTION, 'og:description': DESCRIPTION, 'og:title': TITLE,
            'og:url': CANONICAL, 'og:image:width': '1200', 'og:image:height': '630',
        }.items():
            assert meta.get(name) == expected, name
        image = meta.get('og:image', '')
        assert image.startswith(CANONICAL) and meta.get('twitter:image') == image, image
        asset_path(output, path, image.removeprefix(CANONICAL))
        assert meta.get('og:image:alt'), 'Social image missing an accessible description'


def check_posters(main):
    posters = main.find(class_name='studio-poster')
    assert len(posters) == 6, f'Expected six poster instances, found {len(posters)}'
    images = set()
    for poster in posters:
        image, = poster.find('img')
        images.add(image.attrs['src'])
        offsets = [poster.text.index(line) for line in POSTER_COPY]
        assert offsets == sorted(set(offsets)), f'Poster copy is out of order: {poster.text}'
    assert len(images) == 1, f'Poster images differ: {images}'
    editors = main.find(class_name='silex-editor')
    assert len(editors) == 2 and all(len(editor.find(class_name='studio-poster')) == 1 for editor in editors)
    for name in ('phone-mockup', 'browser-preview'):
        instance, = main.find(class_name=name)
        assert len(instance.find(class_name='studio-poster')) == 1
    for figure in editors + main.find(class_name='phone-mockup') + main.find(class_name='browser-preview'):
        assert not any(node.tag in ('a', 'button', 'input', 'select', 'textarea', 'summary') or
                       node.attrs.get('tabindex', '-1') != '-1' for node in figure.find()), 'Focusable mock control'
    assert '37 px' in main.find(class_name='studio-workflow')[0].text


def check_claims(main):
    links = {(item.text.rstrip(' ↗→'), item.attrs['href']) for item in main.find('a')}
    assert {
        ('Explore the workflow', '#workflow'), ('Documentation', f'{HOME}docs/'),
        ('Read the test record', EVIDENCE), ('View implementation status', EVIDENCE),
        ('Built on Silex', 'https://www.silex.me/'), ('Contribute on GitHub', PROJECT),
    } <= links, 'Missing a required product or evidence link'
    first_use = {
        'studio-ai': ('Planned integration', 'shared AI'),
        'studio-selection': ('Planned publication workflow', 'Review the selected public files'),
        'studio-host-cooperative': ('In development', 'independent peers'),
    }
    for name, (status, description) in first_use.items():
        block, = main.find(class_name=name)
        assert [item.text for item in block.find(class_name='studio-status')] == [status], name
        assert block.text.index(status) < block.text.index(description), name
    assert [item.text for item in main.find(class_name='studio-hero-status')] == ['Integration in development']
    expected_evidence = ('In a hosted test, Silex exported a ZIP after a text edit. '
                         'VOLPAROSSA Core verified all four assets offline.')
    assert expected_evidence in main.find(class_name='studio-export')[0].text
    steps, = main.find(class_name='studio-release-steps')
    assert [step.text for step in steps.find('strong')] == ['Prepare', 'Authorise', 'Retrieve']
    assert 'separate trusted review' in steps.text and 'explicitly authorises signing' in steps.text
    assert 'retrieval is a later step that needs its own evidence' in steps.text
    for name, heading in [('studio-demonstrated', 'Demonstrated in a hosted test'), ('studio-planned', 'In development')]:
        column, = main.find(class_name=name)
        assert [h.text for h in column.find('h3')] == [heading] and len(column.find('li')) == 4


def check_network(main):
    network, = main.find('figure', class_name='studio-network')
    peers = [item for item in network.find() if 'data-peer' in item.attrs]
    edges = [item.attrs['data-edge'] for item in network.find() if 'data-edge' in item.attrs]
    assert len(peers) == len(PEERS) and {peer.attrs['data-peer']: peer.text for peer in peers} == PEERS
    assert len(edges) == len(EDGES) and {'-'.join(sorted(edge.split('-'))) for edge in edges} == EDGES
    assert network.attrs.get('aria-describedby') and network.find('svg')[0].attrs.get('aria-labelledby')
    caption, = network.find('figcaption')
    assert caption.text == 'Proposed cooperative hosting. Peers can reach the same version through different routes.'


def check(output, production):
    output = output.resolve()
    expected_paths = {output / 'index.html', output / 'credits/index.html'}
    assert set(output.rglob('*.html')) == expected_paths, f'Unexpected or missing HTML pages in {output}'
    assert not any(path.is_symlink() for path in output.rglob('*')), 'Generated site contains a symbolic link'
    sitemap = output / 'sitemap.xml'
    assert sitemap.is_file() == production
    if production:
        assert (output / '.nojekyll').is_file()
        routes = {node.text for node in ElementTree.parse(sitemap).iter() if node.tag.split('}')[-1] == 'loc'}
        assert routes == {CANONICAL, f'{CANONICAL}credits/'}, f'Unexpected sitemap routes: {routes}'
    pages = {}
    for path in expected_paths:
        html = path.read_text(encoding='utf-8')
        assert '{{' not in html, f'Unresolved template in {path.relative_to(output)}'
        page = Page(html).document
        assert len(page.find('h1')) == 1 and len(page.find('main')) == 1
        check_head(output, path, page, production)
        pages[path] = page
    check_references(output, pages)

    product = pages[output / 'index.html']
    header, = product.find('header')
    assert {node.attrs['href'] for node in header.find('a')} >= {
        HOME, f'{HOME}#discover', f'{HOME}volparossa/', f'{HOME}applications/',
        f'{HOME}docs/', f'{HOME}contribute/', 'https://github.com/VOLPAROSSA',
    }, 'Shared project navigation destinations'
    assert product.find(class_name='skip-link')[0].attrs['href'] == '#main'
    main, = product.find('main')
    actual_sections = [item for item in main.children if item.tag == 'section']
    assert len(actual_sections) == len(SECTIONS)
    for index, (section, (class_name, heading)) in enumerate(zip(actual_sections, SECTIONS.items())):
        assert section.has_class(class_name), class_name
        assert [item.text for item in section.find('h1' if index == 0 else 'h2')] == [heading], heading
    assert 'Built on Silex. Extended by VOLPAROSSA.' in actual_sections[0].text
    assert 'Illustration of the Silex editor' in actual_sections[0].text
    assert 'open-source website editor' in actual_sections[0].text
    check_posters(main)
    check_claims(main)
    check_network(main)
    assert 'Silex Labs and contributors' in pages[output / 'credits/index.html'].text
    print(f'Checked Studio content, local assets, navigation, evidence and network topology ({"production" if production else "preview"}).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production', action='store_true')
    parser.add_argument('--output', default=ROOT / 'preview/volparossa-studio', type=Path)
    options = parser.parse_args()
    check(options.output, options.production)
