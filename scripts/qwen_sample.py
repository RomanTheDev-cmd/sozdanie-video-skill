#!/usr/bin/env python3
"""Образец для выбора написания на слух (Claude, 2026-10-29).

Qwen3-TTS не понимает знак ударения, а Whisper ударение не слышит. Поэтому написание термина для голоса
выбирает Роман на слух: одна фраза в нескольких написаниях, перед каждым голос называет номер.
Все сомнительные слова ролика собирать в ОДИН образец до озвучки ролика, а не по слову после сборки.

Запуск в окружении Qwen (~/.local/share/freelearn-video/.venv-qwen):
    python qwen_sample.py --reference <образец голоса.wav> --out <папка> \\
        --phrase 'Объясним разницу между {} и тулчéнджером.' --variants 'аэмéс,аэмээс,аэмес' \\
        [--phrase '...{}...' --variants '...'] [--seed 12]
Рядом с образцом голоса должен лежать .json с полем text (текст образца) или указать --ref-text.
Пишет <папка>/Образец для Романа.wav и .json (номер → фраза и написание) и печатает время каждого номера.
"""
import argparse, json, os, sys
from pathlib import Path

ONES = ['один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять']
NUMBERS = ONES + ['десять', 'одиннадцать', 'двенадцать', 'тринадцать', 'четырнадцать', 'пятнадцать', 'шестнадцать',
                  'семнадцать', 'восемнадцать', 'девятнадцать', 'двадцать'] + ['двадцать ' + x for x in ONES] + ['тридцать'] \
          + ['тридцать ' + x for x in ONES] + ['сорок']
BASE = Path.home()/'.cache/freelearn-video/qwen3-base-bf16'
SETTINGS = dict(temperature=0.8, top_p=0.9, repetition_penalty=1.1, max_tokens=1500)


def plan(phrases, variants, first=1):
    """Номера по порядку через все фразы (с first — продолжение прежнего образца); проверяет ввод до загрузки модели."""
    if len(phrases) != len(variants):
        raise SystemExit('на каждую --phrase нужна своя --variants')
    items = []
    for phrase, vs in zip(phrases, variants):
        if phrase.count('{}') != 1:
            raise SystemExit(f'во фразе должно быть ровно одно место {{}} для слова: {phrase!r}')
        for v in [x.strip() for x in vs.split(',') if x.strip()]:
            items.append(dict(number=first+len(items), phrase=phrase, spelling=v, text=phrase.format(v)))
    if not items or items[-1]['number'] > len(NUMBERS):
        raise SystemExit(f'вариантов должно быть от 1 до {len(NUMBERS)}, сейчас {len(items)}')
    return items


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--reference', type=Path, required=True); ap.add_argument('--ref-text')
    ap.add_argument('--out', type=Path, required=True); ap.add_argument('--seed', type=int, default=12)
    ap.add_argument('--phrase', action='append', default=[]); ap.add_argument('--variants', action='append', default=[])
    ap.add_argument('--first', type=int, default=1, help='первый номер (продолжить нумерацию прежнего образца)')
    args = ap.parse_args(argv)
    items = plan(args.phrase, args.variants, args.first)
    ref_text = args.ref_text or json.loads(args.reference.with_suffix('.json').read_text(encoding='utf-8'))['text']
    os.environ['HF_HUB_OFFLINE'] = '1'
    import numpy as np, soundfile as sf, mlx.core as mx
    from mlx_audio.tts.utils import load_model
    model = load_model(str(BASE))

    def say(text, seed):
        mx.random.seed(seed)
        res = list(model.generate(text=text, lang_code='Russian', ref_audio=str(args.reference), ref_text=ref_text, verbose=False, **SETTINGS))
        a = np.concatenate([np.asarray(r.audio, dtype=np.float32).reshape(-1) for r in res]); rate = res[0].sample_rate
        level = np.abs(a); idx = np.nonzero(level > max(level.max()*0.02, 1e-4))[0]
        a = a[max(0, idx[0]-int(0.06*rate)):idx[-1]+int(0.06*rate)]
        mx.clear_cache()
        return a*0.1/max(float(np.sqrt(np.mean(a**2))), 1e-6), rate

    # Голос каждый раз ставит ударение по-своему, поэтому звук каждого варианта сохраняется: выбранный Романом дубль
    # вставляется в ролик как есть (pin_take.py проекта), а не озвучивается заново. Одинаковые написания — разные дубли.
    pieces = []; t = 0.0; takes = args.out/'Дубли'; takes.mkdir(parents=True, exist_ok=True)
    for it in items:
        label, rate = say(f'Вариант {NUMBERS[it["number"]-1]}.', args.seed)
        take, rate = say(it['text'], args.seed + it['number'])
        it['take'] = str(takes/f'{it["number"]:02d}.wav'); sf.write(it['take'], np.clip(take, -0.98, 0.98), rate, subtype='PCM_24')
        it['start'] = round(t, 1)
        for p in (label, np.zeros(int(0.5*rate), np.float32), take, np.zeros(int(1.2*rate), np.float32)):
            pieces.append(p); t += len(p)/rate
        print(f'{it["number"]:2}  {int(it["start"]//60)}:{it["start"]%60:04.1f}  {it["spelling"]}', flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    wav = args.out/'Образец для Романа.wav'
    sf.write(wav, np.clip(np.concatenate(pieces), -0.98, 0.98), rate, subtype='PCM_24')
    (args.out/'Образец для Романа.json').write_text(json.dumps(dict(reference=str(args.reference), seed=args.seed, settings=SETTINGS,
                                                                   items=items), ensure_ascii=False, indent=2), encoding='utf-8')
    print('ОБРАЗЕЦ', wav, round(t, 1), 'с')


if __name__ == '__main__':
    main()
