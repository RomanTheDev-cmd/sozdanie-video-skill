#!/usr/bin/env python3
"""Entrypoint of the skill «Создание видео» (formerly VideoFreeLearn) for the existing shared local engine; no runtime copies."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode=True
os.environ['PYTHONDONTWRITEBYTECODE']='1'


def resolve_engine(home=None):
    home=Path.home() if home is None else Path(home)
    aliases=[home/'.codex/skills/freelearn-video',home/'.claude/skills/freelearn-video']
    if any(not p.is_symlink() or not p.is_dir() for p in aliases):
        raise RuntimeError('Нужны обе действующие ссылки Codex/Claude на общий freelearn-video')
    roots=[p.resolve() for p in aliases]
    if roots[0]!=roots[1]:raise RuntimeError('Ссылки Codex и Claude ведут к разным движкам')
    root=roots[0]
    for name in ['ENGINE.md','VERSION','scripts/build_video.py','scripts/check_logic.py','scripts/check_audio_logic.py']:
        if not (root/name).is_file():raise RuntimeError('В движке отсутствует '+name)
    return root


def runtime_root(home=None,environ=None):
    env=os.environ if environ is None else environ
    home=Path.home() if home is None else Path(home)
    value=env.get('FREELEARN_VIDEO_RUNTIME')
    if value is not None and not value.strip():raise RuntimeError('FREELEARN_VIDEO_RUNTIME задан пустым')
    return Path(value).expanduser() if value else home/'.local/share/freelearn-video'


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['status','check-entrypoint','check','check-audio','build'],nargs='?',default='status')
    parser.add_argument('--allow-render',action='store_true',help='Only for a current explicit user request for media')
    args,rest=parser.parse_known_args(argv)
    if args.mode=='build' and not args.allow_render:parser.error('Рендер не разрешён: нужен явный запрос пользователя и --allow-render')
    if args.mode!='build' and (args.allow_render or rest):parser.error('Этот режим не принимает параметры рендера')
    if args.mode=='build' and not rest:parser.error('Укажите JSON-сценарий и параметры заказанного экспорта')
    if args.mode in ('check-entrypoint','check'):
        print('Создание видео: проверки навыка',flush=True)
        tests=Path(__file__).resolve().with_name('check_entrypoint.py')
        result=subprocess.run([sys.executable,str(tests)],check=False,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}).returncode
        if result or args.mode=='check-entrypoint':return result
    engine=resolve_engine();runtime=runtime_root()
    if args.mode=='status':
        result={'interface':'Создание видео','interface_version':(Path(__file__).resolve().parents[1]/'VERSION').read_text().strip(),'engine_root':str(engine),'engine_version':(engine/'VERSION').read_text().strip(),'runtime':str(runtime),'python_available':{env:(runtime/env/'bin/python').is_file() for env in ['.venv','.venv-audio','.venv-qwen']},'render_started':False,'voice_synthesis_started':False,'limits':['Path/version inventory is not rendering or listening assessment.']}
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    environment='.venv-audio' if args.mode=='check-audio' else '.venv'
    python=runtime/environment/'bin/python'
    if not python.is_file():raise RuntimeError('Нет локального окружения '+str(python))
    script={'check':'check_logic.py','check-audio':'check_audio_logic.py','build':'build_video.py'}[args.mode]
    if args.mode in ('check','check-audio'):print('freelearn-video: '+script,flush=True)
    command=[str(python),str(engine/'scripts'/script)]+(rest if args.mode=='build' else [])
    return subprocess.run(command,check=False,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}).returncode


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,RuntimeError,ValueError) as error:
        print(json.dumps({'errors':[str(error)],'render_started':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
