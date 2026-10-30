#!/usr/bin/env python3
"""Check the text for speech synthesis against references/proiznoshenie.json before any synthesis.

    python3 scripts/check_tts.py [--qwen] <scenario.json> [more.json ...]

Reads every object with `narration` (what viewers read) and optional `tts_text` (what the voice reads).
Errors (exit 1, do not synthesize): a correction of Roman's is missing from tts_text, a form he rejected
appears in the voice text, or a replaced word («головка», «дрыгостолы», «печать нитью») is still used.
Warnings: suggested forms for names and formats are not used, Latin letters or digits are left in tts_text,
or a row has no tts_text, so the voice reads the subtitle text and stress marks cannot be applied.
--qwen (a voice that ignores stress marks, Qwen3-TTS): also lists Roman's terms of the scenario whose spelling for
that voice he has not approved by ear (no `qwen_heard_ok` in the lexicon) and exits 3 — build ONE numbered sample
of all of them with scripts/qwen_sample.py before synthesizing the video (Roman, 2026-10-29: «чтобы не тратить
больше столько времени на каждое слово»).
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


def unheard_for_qwen(path, lexicon):
    """Roman's terms used in the scenario whose spelling for Qwen he has not approved by ear yet."""
    lines = list(rows(json.loads(Path(path).read_text(encoding='utf-8'))))
    found = {}
    for e in lexicon:
        if e['kind'] == 'замена слова' or e['group'] not in STRICT or e.get('qwen_heard_ok'):
            continue
        key = key_of(e['written'])
        count = sum(len(pattern(key).findall(shown)) for _, shown, _ in lines)
        if count:
            # without a qwen field the voice gets the stress-marked form with the marks removed
            found[key] = dict(say=e['say'], qwen=e.get('qwen') or e['say'].replace(ACUTE, ''), count=count)
    return found


def variable_words(path, lexicon):
    """Words whose stress the voice keeps changing take to take (audit 2026-10-30, risk 1): lexicon entries with
    `qwen_variable` and the homographs of qwen_text.py. qwen_heard_ok approves a spelling, not every take, so after
    voicing Roman gets these places to listen to."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('qwen_text', Path(__file__).with_name('qwen_text.py'))
    qt = importlib.util.module_from_spec(spec); spec.loader.exec_module(qt)
    lines = list(rows(json.loads(Path(path).read_text(encoding='utf-8'))))
    found = {}
    for e in lexicon:
        if e.get('qwen_variable'):
            key = key_of(e['written']); count = sum(len(pattern(key).findall(shown)) for _, shown, _ in lines)
            if count:
                found[key] = count
    for word in sorted(qt.HOMOGRAPHS):
        count = sum(len(re.findall(r'(?<!\w)' + word + r'(?!\w)', plain(shown))) for _, shown, _ in lines)
        if count:
            found[word] = count
    return found


def main(argv):
    qwen = '--qwen' in argv
    argv = [a for a in argv if a != '--qwen']
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    lexicon = load_lexicon()
    total = 0
    unheard, variable = {}, {}
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
        if qwen:
            unheard.update(unheard_for_qwen(path, lexicon))
            variable.update(variable_words(path, lexicon))
    if total:
        print('Синтез речи не запускать, пока ошибки не исправлены.')
        return 1
    if variable:
        print('Ударение в этих словах голос ставит то так, то так — после озвучки дать Роману послушать их места '
              '(open_at.py, время — по .srt итога): ' + ', '.join(f'{k} ×{n}' for k, n in variable.items()))
    if unheard:
        print('Для голоса без знаков ударения (Qwen) Роман ещё не проверил на слух:')
        for key, v in unheard.items():
            print(f'  {key} — нужно «{v["say"]}», голос получает «{v["qwen"]}», в сценарии раз: {v["count"]}')
        print('До озвучки ролика собрать ОДИН образец всех этих слов (scripts/qwen_sample.py: по 3–4 написания, '
              'перед каждым номер), дать Роману выбрать номера и записать выбор в словарь: qwen и qwen_heard_ok.')
        return 3
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
