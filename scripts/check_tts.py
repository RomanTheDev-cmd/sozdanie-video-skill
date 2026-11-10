#!/usr/bin/env python3
"""Проверка narration/tts_text по общему словарю до синтеза Tera.
Запуск: python3 scripts/check_tts.py scenario.json [more.json ...]
Коды: 0 — проверенные текстовые правила соблюдены, 1 — нарушения, 2 — неверный вход.
Текстовая проверка не подтверждает фактическое произношение записи.
"""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
ACUTE = '́'
STRICT = {'Правки Романа', 'Выведено из правок Романа'}
SUGGESTED = {'3D-печать: названия, модели, форматы'}
LETTER = r'[\w' + ACUTE + ']'
# Знаков нет в словаре символов Tera (unicode_indexer.json): модель молча их выбрасывает, пауза пропадает
# («двухсот — трёхсот» сливается). Claude, 2026-11-09, ролик «Меры безопасности в FDM-печати».
TERA_SKIPS = {'—': 'длинное тире', '–': 'короткое тире', '…': 'многоточие'}
VOWELS = set('аеёиоуыэюя')


def load_lexicon(path=None):
    return json.loads(Path(path or ROOT/'references/proiznoshenie.json').read_text(encoding='utf-8'))['entries']


def plain(text):
    return text.replace(ACUTE, '').replace('ё', 'е').replace('Ё', 'Е').lower()


def norm(text, keep_stress, e_is_e=False):
    """Compare what is heard: punctuation and hyphens are pauses at most; optionally stress marks and е/э are ignored."""
    text = re.sub(r'[.,;:!?…"«»()\[\]—–-]+', ' ', text.lower().replace('ё', 'е'))
    if not keep_stress:
        text = text.replace(ACUTE, '')
    if e_is_e:
        text = text.replace('э', 'е')
    return ' ' + re.sub(r'\s+', ' ', text).strip() + ' '


def says(form, voice):
    """Roman's form must be heard; where he gave no stress, any stress and е/э spelling will do (петджи = пэтджи́)."""
    keep = ACUTE in form
    return norm(form, keep, not keep).strip() in norm(voice, keep, not keep)


def key_of(written):
    return re.sub(r'\s*\(.*?\)', '', written).strip()


def pattern(key):
    """Abbreviations and Latin names match case-sensitively as whole words; Russian words also match their endings."""
    if key.upper() == key or re.search(r'[A-Za-z0-9]', key):
        return re.compile(r'(?<!' + LETTER + ')' + re.escape(key) + r'(?!' + LETTER + ')')
    # A word ending in a consonant (дрыгостол, хотэнд) also matches its case forms; a word ending in a vowel
    # (постепенно) or a phrase matches only as written, so «постепенная» is not taken for «постепенно».
    tail = r'\w*' if ' ' not in key and key[-1].lower() not in 'аяоеёыиуюэ' else ''
    return re.compile(r'(?<!' + LETTER + ')' + re.escape(key) + tail + r'(?!' + LETTER + ')', re.IGNORECASE)


def forbidden(form, spoken):
    """A rejected form with a stress mark must match exactly; without one it matches any stress."""
    keep = ACUTE in form
    target, text = norm(form, keep).strip(), norm(spoken, keep)
    return re.search(r'(?<!' + LETTER + ')' + re.escape(target) + r'(?!' + LETTER + ')', text) is not None


def rows(node, where='сценарий'):
    if isinstance(node, dict):
        if isinstance(node.get('narration'), str):
            yield where + (' «' + str(node.get('title')) + '»' if node.get('title') else ''), node['narration'], node.get('tts_text')
        for k, v in node.items():
            yield from rows(v, where + '/' + str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from rows(v, where + '[' + str(i + 1) + ']')


def check_text(where, shown, spoken, lexicon):
    errors, warnings = [], []
    voice = spoken if isinstance(spoken, str) else shown
    taken = []  # spans of replaced words, so «дрыгостолы» is not also judged as «дрыгостол»
    for e in lexicon:
        if e['kind'] != 'замена слова':
            continue
        for form in e['forms']:
            for m in re.finditer(r'(?<!' + LETTER + ')' + re.escape(form) + r'(?!' + LETTER + ')', shown, re.IGNORECASE):
                taken.append(m.span())
                errors.append(f'{where}: «{key_of(e["written"])}» нужно заменить — {e["note"]}')
    for e in lexicon:
        if e['kind'] == 'замена слова' or e['group'] not in STRICT | SUGGESTED:
            continue
        key = key_of(e['written'])
        found = [m for m in pattern(key).finditer(shown) if not any(a <= m.start() < b for a, b in taken)]
        if found and not says(e['say'], voice):
            if not isinstance(spoken, str):
                warnings.append(f'{where}: нет tts_text — «{key}» голос прочитает без словаря; нужно «{e["say"]}»')
            elif e['group'] in STRICT:
                errors.append(f'{where}: «{key}» в тексте для голоса должно быть «{e["say"]}» — {e["note"]}')
            else:
                warnings.append(f'{where}: «{key}» — предложено «{e["say"]}» ({e["source"]})')
    for e in lexicon:
        for form in e.get('avoid', []):
            if forbidden(form, voice):
                errors.append(f'{where}: в тексте для голоса отменённая форма «{form}» — нужно «{e["say"]}» ({key_of(e["written"])})')
    if isinstance(spoken, str):
        latin = sorted(set(re.findall(r'[A-Za-z][A-Za-z0-9-]*', spoken)))
        if latin:
            warnings.append(f'{where}: латиница в тексте для голоса: {", ".join(latin)} — записать по-русски')
        if re.search(r'\d', spoken):
            warnings.append(f'{where}: цифры в тексте для голоса — записать словами')
        for mark, name in TERA_SKIPS.items():
            if mark in spoken:
                errors.append(f'{where}: в тексте для голоса знак «{mark}» ({name}) — Tera его молча пропускает, '
                              f'пауза пропадает; заменить запятой, двоеточием или точкой (в субтитрах можно оставить)')
        single = sorted({w for w in re.findall('[А-Яа-яЁё' + ACUTE + ']+', spoken)
                         if ACUTE in w and sum(c in VOWELS for c in w.lower()) == 1})
        if single:
            warnings.append(f'{where}: знак ударения на односложном слове: {", ".join(single)} — снять '
                            f'(RUAccent ставит его и на предлоги, частицы)')
    return errors, warnings


def check_file(path, lexicon):
    errors, warnings = [], []
    lines = list(rows(json.loads(Path(path).read_text(encoding='utf-8'))))
    if not lines:
        raise ValueError('не найдено ни одной реплики с полем narration — проверять нечего')
    for where, shown, spoken in lines:
        e, w = check_text(where, shown, spoken, lexicon)
        errors += e
        warnings += w
    return errors, warnings






def main(argv):
    if not argv or any(a.startswith('--') for a in argv):
        print('Нужен сценарий JSON; специальные режимы прежнего синтезатора удалены.', file=sys.stderr)
        return 2
    lexicon = load_lexicon()
    total = 0
    for path in argv:
        try:
            errors, warnings = check_file(path, lexicon)
        except (OSError, ValueError) as error:
            print(f'{path}: не удалось прочитать сценарий — {error}', file=sys.stderr)
            return 2
        total += len(errors)
        print(f'{path}: ошибок {len(errors)}, предупреждений {len(warnings)}')
        for line in errors:
            print('  ОШИБКА ' + line)
        for line in warnings:
            print('  предупреждение ' + line)
    if total:
        print('Синтез речи не запускать, пока ошибки не исправлены.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
