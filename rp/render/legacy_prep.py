"""Legacy display preparation, copied unchanged from the legacy site.

Source: mehmetmars7/Erdosproblems-llm-hunter @ b1f633121074e16579fa7fd05314e5f504d29bae
(Apache-2.0): ``build_site.py`` (replace_tex_command, tex_notation_macros, expand_tex_notation, normalize_article_notation, parse_numbered_problem_tex, parse_collection_metadata, current_collection_provenance) and ``scripts/economics_catalog.py``
(extract_statement, plus the inline attempt preparation of ``load_economics_attempts``).
These functions decide which TeX the legacy site handed to ``formatTeX`` for
each collection. They are pure string transformations: they never execute TeX.
Do not edit them here; the call sites below reproduce the legacy pipeline, and
``tests/renderer`` guards the behaviour. See docs/adr/0011.
"""
# ruff: noqa
import json
import re

STATEMENT_START = '% BEGIN ECONOMICS STATEMENT\n'
STATEMENT_END = '% END ECONOMICS STATEMENT'


def replace_tex_command(text, command, count, replacement):
    """Replace a known TeX command without truncating nested or escaped braces."""
    pattern = re.compile(r'\\' + re.escape(command) + r'\b')
    parts, cursor = [], 0
    for match in pattern.finditer(text):
        if match.start() < cursor:
            continue
        end = match.end()
        arguments = []
        for _ in range(count):
            while end < len(text) and text[end].isspace():
                end += 1
            if end == len(text) or text[end] != '{':
                raise ValueError(f'Missing argument for TeX command {command}')
            start, depth = end + 1, 1
            end += 1
            while end < len(text) and depth:
                if text[end] == '\\':
                    end += 2
                    continue
                if text[end] == '{':
                    depth += 1
                elif text[end] == '}':
                    depth -= 1
                end += 1
            if depth:
                raise ValueError(f'Unclosed argument for TeX command {command}')
            arguments.append(text[start:end - 1])
        parts.extend((text[cursor:match.start()], replacement(*arguments)))
        cursor = end
    return ''.join(parts) + text[cursor:]


def tex_notation_macros(preamble, defaults):
    """Read document-local, argument-free notation without executing TeX.

    Parameterized commands and layout helpers stay with their existing display
    handlers. This is deliberately not an interpreter for packages or TeX code.
    """
    # Escaped percent signs survive; actual comments cannot declare a macro.
    preamble = re.sub(r'\\.|%[^\n]*',
                      lambda match: match[0] if match[0].startswith('\\') else '',
                      preamble)
    declarations = re.compile(
        r'\\(newcommand|renewcommand|providecommand|DeclareMathOperator)(\*)?\s*'
        r'(?:\{\s*\\([A-Za-z]+)\s*\}|\\([A-Za-z]+))\s*'
        r'(?:\[(\d+)\]\s*)?')
    aliases = dict(defaults)
    declared = set()
    cursor = 0
    for match in declarations.finditer(preamble):
        if match.start() < cursor:
            continue
        start = match.end()
        if start >= len(preamble) or preamble[start] != '{':
            continue
        end, depth = start + 1, 1
        while end < len(preamble) and depth:
            if preamble[end] == '\\':
                end += 2
                continue
            if preamble[end] == '{':
                depth += 1
            elif preamble[end] == '}':
                depth -= 1
            end += 1
        cursor = end
        if depth or int(match[5] or 0):
            continue
        name = match[3] or match[4]
        body = preamble[start + 1:end - 1].strip()
        if name in {'arraystretch', 'tightlist'}:
            continue
        if match[1] == 'providecommand' and name in declared:
            continue
        declared.add(name)
        if match[1] == 'DeclareMathOperator':
            body = r'\operatorname' + (match[2] or '') + '{' + body + '}'
        # Keep the existing normalized spelling for standard number sets.
        body = re.sub(r'\\mathbb\s+([A-Za-z])', r'\\mathbb{\1}', body)
        aliases[name] = body if defaults.get(name) == body else '{' + body + '}'

    command = re.compile(r'\\([A-Za-z]+|[^A-Za-z])')
    resolved = {}

    def resolve(name, trail=()):
        if name in resolved:
            return resolved[name]
        if name in trail or len(trail) >= 32:
            raise ValueError(f'Recursive or excessively nested TeX notation macro: {name}')
        value = command.sub(lambda m: resolve(m[1], (*trail, name))
                            if m[1] in aliases else m[0], aliases[name])
        if len(value) > 65536:
            raise ValueError(f'TeX notation macro expansion too large: {name}')
        resolved[name] = value
        return value

    return {name: resolve(name) for name in aliases}


def expand_tex_notation(text, macros):
    """Expand notation while retaining literal code/verbatim examples."""
    tokens = re.compile(
        r'\\begin\{(verbatim\*?|Verbatim|Code|lstlisting|minted)\}'
        r'[\s\S]*?\\end\{\1\}'
        r'|\\verb\*?([^\w\s])[^\n]*?\2'
        r'|\\([A-Za-z]+|[^A-Za-z])')
    return tokens.sub(lambda m: macros.get(m[3], m[0]) if m[3] else m[0], text)


def normalize_article_notation(content):
    """Expand declared notation in ordinary articles, preserving the source wrapper."""
    document = re.search(r'^[ \t]*\\begin\{document\}[ \t]*\r?$', content, re.MULTILINE)
    if not document:
        return content
    macros = tex_notation_macros(content[:document.start()], {})
    return content[:document.end()] + expand_tex_notation(content[document.end():], macros)


def parse_numbered_problem_tex(content, *, require_source_urls=True):
    """Extract display content while leaving the downloadable source untouched."""
    # Standalone submissions can retain archival comments after the document.
    content = re.sub(r'^[ \t]*%[^\n]*(?:\n|$)', '', content, flags=re.MULTILINE)
    document = re.search(r'\\begin\{document\}(.*?)\\end\{document\}\s*$',
                         content, re.DOTALL)
    if not document:
        raise ValueError('Expected one complete TeX document')
    body = re.sub(r'^[ \t]*%[^\n]*(?:\n|$)', '', document[1], flags=re.MULTILINE)
    headings = list(re.finditer(r'^[ \t]*\\subsection\{([^}\n]+)\}', body, re.MULTILINE))
    sections = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        if heading[1] in sections:
            raise ValueError(f'Duplicate TeX subsection: {heading[1]}')
        sections[heading[1]] = body[heading.end():end].strip()
    required = ['Definitions and mathematical statement', 'Short English statement', 'Sources']
    if any(not sections.get(name) for name in required):
        raise ValueError('Missing definition, summary, or sources')

    # Both the original standalone files and verbatim notebook sections use
    # local S/E source labels; the latter wrap them in textnormal/hypertarget.
    sources_tex = re.sub(r'\\item\[\\textnormal\{\[([A-Z]\d+)\]\}\]',
                         r'\\item[\1]', sections['Sources'])
    sources_tex = replace_tex_command(sources_tex, 'hypertarget', 2, lambda key, text: text)
    sources, urls = [], {}
    for item in re.finditer(r'\\item\[([A-Z]\d+)\]\s*(.*?)(?=\\item\[|\\end\{itemize\}|\Z)',
                            sources_tex, re.DOTALL):
        url = re.search(r'\\url\{([^}]+)\}', item[2])
        if not url and require_source_urls:
            raise ValueError(f'Missing URL for source {item[1]}')
        urls[item[1]] = url[1] if url else None
        sources.append({'citation': item[2][:url.start()].strip() if url else item[2].strip(),
                        'url': url[1] if url else None})

    macros = {'N': r'{\mathbb{N}}', 'Z': r'{\mathbb{Z}}', 'Q': r'{\mathbb{Q}}',
              'R': r'{\mathbb{R}}', 'C': r'{\mathbb{C}}', 'F': r'{\mathbb{F}}',
              'A': r'{\mathbb{A}}', 'PP': r'{\mathbb{P}}', 'E': r'{\mathbb{E}}',
              'eps': r'\varepsilon', 'dd': r'\,\mathrm d'}
    macros = tex_notation_macros(content[:document.start()], macros)

    def display(text):
        # The website uses the mathematical exposition, not the repeated
        # catalogue quotation. Keep that quotation in the original .tex file.
        text = replace_tex_command(text, 'cataloguescope', 1, lambda quote: '')
        def source_link(label):
            if label not in urls:
                raise ValueError(f'Missing local source {label}')
            if urls[label] is None:
                return '[' + label + ']'
            return r'\href{' + urls[label] + '}{[' + label + ']}'

        for command, prefix in [('sref', 'S'), ('eref', 'E')]:
            text = replace_tex_command(text, command, 2,
                                       lambda scope, number, prefix=prefix: source_link(prefix + number))
        for command in ('src', 'srcref'):
            text = replace_tex_command(text, command, 1, source_link)
        text = replace_tex_command(text, 'needspace', 1, lambda space: '')
        text = re.sub(r'\\raggedright\b', '', text)
        return expand_tex_notation(text, macros).strip()

    sections['Sources'] = sources_tex
    definition = '\n\n'.join(r'\subsection{' + name + '}\n' + display(sections[name])
                             for name in required)
    research = '\n\n'.join(r'\subsection{' + name + '}\n' + display(text)
                           for name, text in sections.items()
                           if re.fullmatch(r'Research attempt(?:: .+)?', name) and text)
    research = (research + '\n\n' + r'\subsection{Sources}' + '\n' + display(sources_tex)
                if research else None)
    title = re.search(r'^[ \t]*\\section\*?\{[^\n]+', body, re.MULTILINE)
    document = ((title[0].strip() + '\n\n') if title else '') + '\n\n'.join(
        r'\subsection{' + name + '}\n' + display(text) for name, text in sections.items())
    return {'definitionTeX': definition, 'exactTarget': display(sections['Short English statement']),
            'sources': sources, 'researchTeX': research, 'documentTeX': document}


def parse_collection_metadata(content):
    """Read an attributed collection record without treating its header as prose.

    Invalid metadata stops the build: silently discarding attribution could
    misrepresent an imported writeup as a new mathematical attempt.
    """
    first_line, separator, remainder = content.partition('\n')
    marker = re.match(r'^\s*%\s*COLLECTION_METADATA:\s*(.*)$', first_line)
    if not marker:
        return None, content
    try:
        metadata = json.loads(marker.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError('Invalid COLLECTION_METADATA JSON') from exc
    if not isinstance(metadata, dict) or metadata.get('schema_version') != 1:
        raise ValueError('Unsupported COLLECTION_METADATA schema_version')
    kind = metadata.get('kind')
    if kind not in {'reused_writeup', 'statement_only'}:
        raise ValueError('Invalid COLLECTION_METADATA kind')
    if metadata.get('independently_reviewed') is not False:
        raise ValueError('Collection imports must explicitly be independently_reviewed: false')
    if kind == 'reused_writeup':
        for key in ('source_model', 'primary_source'):
            if not isinstance(metadata.get(key), str) or not metadata[key].strip():
                raise ValueError(f'COLLECTION_METADATA requires {key}')
        paths = metadata.get('source_paths')
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
            raise ValueError('COLLECTION_METADATA requires source_paths')
        if metadata.get('source_claim') not in {'solved', 'unresolved'}:
            raise ValueError('Invalid COLLECTION_METADATA source_claim')
        completion = metadata.get('source_completion')
        if completion is not None and (
            type(completion) not in (int, float) or not 0 <= completion <= 100
        ):
            raise ValueError('Invalid COLLECTION_METADATA source_completion')
    else:
        urls = metadata.get('source_urls')
        if not isinstance(urls, list) or not all(isinstance(url, str) for url in urls):
            raise ValueError('COLLECTION_METADATA requires source_urls')
    return metadata, remainder if separator else ''


def current_collection_provenance(metadata):
    """Resolve migrated source links in site data while retaining source records."""
    if metadata['kind'] != 'reused_writeup':
        return metadata

    def current_path(path):
        for collection in ('erdos', 'mo'):
            old_prefix = f'attacks/{collection}/'
            if path.startswith(old_prefix):
                return f'attacks/open_problems/{collection}/' + path[len(old_prefix):]
        return path

    return {
        **metadata,
        'primary_source': current_path(metadata['primary_source']),
        'source_paths': [current_path(path) for path in metadata['source_paths']],
    }


def extract_statement(content):
    if content.count(STATEMENT_START) != 1 or content.count(STATEMENT_END) != 1:
        raise ValueError('Statement file must contain one Economics statement boundary pair')
    body = content.split(STATEMENT_START, 1)[1].split(STATEMENT_END, 1)[0].strip()
    if not body or not re.search(r'\\subsection\*?\s*\{', body):
        raise ValueError('Economics statement has no substantive subsection')
    if re.search(r'\\label\{difficulty-rank:', body) or '\\ProblemClassification' in body:
        raise ValueError('Economics statement contains obsolete classification/rank metadata')
    return body


def economics_attempt_body(content, path):
    """Inline preparation from load_economics_attempts (unchanged)."""
    preamble, body = content.split(r'\begin{document}', 1)
    body, trailing = body.split(r'\end{document}', 1)
    if trailing.strip() or not body.strip():
        raise ValueError(f'Invalid Economics attempt document: {path.name}')
    titles = []
    replace_tex_command(preamble, 'title', 1, lambda title: titles.append(title) or '')
    if titles:
        # PDF title spacing and font sizes must not become display math
        # or raw commands inside the website's section heading.
        titles[0] = re.sub(r'\\\\(?:\[[^\]]*\])?', ' ', titles[0])
        titles[0] = re.sub(r'\\(?:large|Large|LARGE|huge|Huge|small|normalsize)\b', '', titles[0])
        titles[0] = ' '.join(titles[0].split())
    body = body.replace(r'\maketitle', r'\section*{' + titles[0] + '}' if titles else '')
    body = re.sub(r'\\(?:tableofcontents|appendix|clearpage)\b', '', body)
    body = body.replace(r'\begin{abstract}', r'\subsection*{Abstract}').replace(r'\end{abstract}', '')
    body = re.sub(r'\\(?:begingroup|endgroup)\b', '', body)
    body = replace_tex_command(body, 'vspace', 1, lambda *args: '')
    body = replace_tex_command(body, 'setlength', 2, lambda *args: '')
    body = replace_tex_command(body, 'addcontentsline', 3, lambda *args: '')
    body = expand_tex_notation(body, tex_notation_macros(preamble, {}))
    return body
