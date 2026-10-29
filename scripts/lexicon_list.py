#!/usr/bin/env python3
"""Build the readable stress list references/spisok-udareniy.md from references/proiznoshenie.json.

    python3 scripts/lexicon_list.py           write the list
    python3 scripts/lexicon_list.py --check   exit 1 if the list is out of date
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'references/proiznoshenie.json'
TARGET = ROOT/'references/spisok-udareniy.md'
GROUPS = ['Правки Романа', 'Выведено из правок Романа', '3D-печать: названия, модели, форматы',
          '3D-печать: слова', 'Омографы и общие слова']
INTRO = {
    'Правки Романа': 'Обязательны. Важнее всех остальных записей.',
    'Выведено из правок Романа': 'Получено из его правки для близкого слова; отдельно Роман не подтверждал.',
    '3D-печать: названия, модели, форматы': 'Формы из ролика о 3D-печати (Роман их не исправлял) и предложения для частых названий.',
    '3D-печать: слова': 'Ударения по словарной норме; Роман их не подтверждал.',
    'Омографы и общие слова': 'Ударение зависит от смысла — проверять по контексту реплики.',
}


def cell(text):
    return text.replace('|', '/').strip() or '—'


def render(data):
    lines = ['# Список слов и ударений для озвучки', '',
             'Создан из `proiznoshenie.json` командой `python3 scripts/lexicon_list.py`; вручную не править. '
             'Знак ударения стоит после ударной гласной. «Как читать» — текст для голоса, в субтитрах остаётся «Как пишется».',
             '', 'Обновлён: ' + data['updated'] + '.', '']
    for group in GROUPS:
        items = [e for e in data['entries'] if e['group'] == group]
        if not items:
            continue
        lines += ['## ' + group, '', INTRO[group], '', '| Как пишется | Как читать | Примечание |', '|---|---|---|']
        for e in sorted(items, key=lambda e: e['written'].lower()) if group != 'Правки Романа' else items:
            note = '. '.join(x for x in [e['note'], 'Замена слова: меняет и субтитры' if e['kind'] == 'замена слова' else '',
                                         'Запрещено: ' + ', '.join(e['avoid']) if e.get('avoid') else ''] if x)
            lines.append('| ' + cell(e['written']) + ' | ' + cell(e['say']) + ' | ' + cell(note) + ' |')
        lines.append('')
    return '\n'.join(lines)


def main(argv):
    text = render(json.loads(SOURCE.read_text(encoding='utf-8')))
    if '--check' in argv:
        current = TARGET.read_text(encoding='utf-8') if TARGET.exists() else ''
        if current != text:
            print('Список ударений устарел: запустите python3 scripts/lexicon_list.py', file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text, encoding='utf-8')
    print(TARGET)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
