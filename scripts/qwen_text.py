#!/usr/bin/env python3
"""Текст для голоса, который не понимает знаки ударения (Qwen3-TTS), — из tts_text и словаря (Claude, 2026-10-29).

    python3 scripts/qwen_text.py <сценарий.json>      # печатает текст для голоса каждой реплики

Знаки ударения убираются. Слова, для которых Роман выбрал написание на слух (поле `qwen` в proiznoshenie.json),
заменяются этим написанием во всех формах (тулче́нджера → тулчéнджера); «е» и «э» при поиске не различаются.
Первая буква предложения — заглавная. Программа озвучки проекта берёт текст отсюда, а не из своего списка замен:
так выбор Романа сразу доходит до любого ролика и любого агента.
"""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
ACUTE = '́'
VOWELS = 'аеёиоуыэюяaeiou'


def load_lexicon(path=None):
    return json.loads(Path(path or ROOT/'references/proiznoshenie.json').read_text(encoding='utf-8'))['entries']


def rules(lexicon):
    """(шаблон, написание) — длинные раньше: «бамбу лаб а-один мини» до «а-один»."""
    found = []
    for e in lexicon:
        spelling, source = e.get('qwen'), e['say'].replace(ACUTE, '')
        if not spelling:
            continue    # совпадающее написание тоже правило: «пэтджи» и «петджи» приводятся к выбранному
        # ищется в размеченном тексте: знак ударения после любой буквы не мешает совпадению
        body = ''.join(('[еэЕЭ]' if ch in 'еэЕЭ' else re.escape(ch)) + ACUTE + '?' for ch in source)
        # слово на согласную совпадает и в падежных формах (окончание остаётся), на гласную — только целиком
        tail = '' if source[-1].lower() not in VOWELS else r'(?![\w' + ACUTE + '])'
        flags = 0 if len(source.replace(' ', '')) <= 2 else re.IGNORECASE   # «И И» — только как написано
        found.append((len(source), re.compile(r'(?<![\w' + ACUTE + '])' + body + tail, flags), spelling))
    return [(rx, spelling) for _, rx, spelling in sorted(found, key=lambda r: -r[0])]


# Омографы, у которых голос ставил ударение то так, то так (ролик о 3D-печати, 2026-10-30); плюс группа словаря «Омографы…»
HOMOGRAPHS = {'сопла', 'волокна', 'сорта'}
LATIN = {'а': 'á', 'е': 'é', 'э': 'é', 'о': 'ó', 'и': 'í', 'А': 'Á', 'Е': 'É', 'Э': 'É', 'О': 'Ó', 'И': 'Í', 'у': 'у' + ACUTE, 'У': 'У' + ACUTE}


def watched(lexicon):
    """Слова, где знак ударения превращается в латинскую букву: омографы и правки Романа, которые он ещё не проверил
    на слух (нет qwen и qwen_heard_ok). Пустое qwen значит «написание не помогает», qwen_heard_ok — «и так звучит
    правильно»: такие слова не трогать."""
    words = set(HOMOGRAPHS)
    for e in lexicon:
        if e['group'].startswith('Омографы') or (e['group'] in ('Правки Романа', 'Выведено из правок Романа')
                                                 and 'qwen' not in e and not e.get('qwen_heard_ok')):
            words |= {w.replace(ACUTE, '').lower() for w in re.split(r'[ -]', e['say']) if ACUTE in w}
    return words


def latinize(word):
    return re.sub('([' + ''.join(LATIN) + '])' + ACUTE, lambda m: LATIN[m.group(1)], word)


def to_qwen(tts_text, lexicon=None, latin_stress='all'):
    """latin_stress='all' — по умолчанию (Роман, 2026-10-30: «во всех словах когда отдаешь текст на озвучку выставлять
    ударения сразу»; образец трёх фраз — «сейчас все отлично»): ударная гласная каждого слова — латинская буква
    (á é ó í; у — знаком ударения; ы, я, ю — без подсказки), кроме слов с выбранным Романом написанием.
    latin_stress=True (Роман: «выставляй ударения как я понял это самый рабочий вариант»): только в омографах и правках
    Романа без выбранного написания ударная гласная — латинская буква с ударением (соплá, сортá). Для ролика,
    уже одобренного без этого правила, — latin_stress=False, иначе изменится текст одобренных кусков."""
    lexicon = lexicon if lexicon is not None else load_lexicon()
    text, kept = tts_text, []

    def keep(spelling):
        kept.append(spelling); return f'{len(kept)-1}'

    # 1) выбранные Романом написания — целым названием/фразой, закрыты от дальнейших замен (аудит 2026-10-30, риск 2:
    #    раньше из ударений выпадали все слова названий, например «один» из «а-один мини», и в обычном тексте)
    for rx, spelling in rules(lexicon):
        text = rx.sub(lambda m: keep(spelling[0].upper() + spelling[1:] if m.group(0)[0].isupper() else spelling), text)
    # 2) латинские ударения в остальных словах
    if latin_stress == 'all':
        # кроме слов с пустым qwen: «написание не помогает» (нейлон — Роман отверг латиницу)
        plain = {w.replace(ACUTE, '').lower() for e in lexicon if e.get('qwen') == '' for w in re.split(r'[ -]', e['say'])}
        text = re.sub(r'[\w' + ACUTE + ']+', lambda m: m.group(0) if m.group(0).replace(ACUTE, '').lower() in plain else latinize(m.group(0)), text)
    elif latin_stress:
        watch = watched(lexicon)
        text = re.sub(r'[\w' + ACUTE + ']+', lambda m: latinize(m.group(0)) if m.group(0).replace(ACUTE, '').lower() in watch else m.group(0), text)
    text = text.replace(ACUTE, '')
    text = re.sub('(\\d+)', lambda m: kept[int(m.group(1))], text)
    # предложение начинается с заглавной: модель читает это как начало фразы
    return re.sub(r'(^|[.!?]\s+)([а-яёa-záéíóú])', lambda m: m.group(1) + m.group(2).upper(), text)


def main(argv):
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    lexicon = load_lexicon()

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get('tts_text'), str):
                print(to_qwen(node['tts_text'], lexicon))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(json.loads(Path(argv[0]).read_text(encoding='utf-8')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
