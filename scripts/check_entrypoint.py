#!/usr/bin/env python3
"""Portable stdlib checks. Every subprocess is mocked; no media or models."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
ACUTE = '\u0301'
VOWELS = set('аеёиоуыэюя')
spec = importlib.util.spec_from_file_location('video_entry', ROOT/'scripts/engine.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
lister_spec = importlib.util.spec_from_file_location('lexicon_list', ROOT/'scripts/lexicon_list.py')
lister = importlib.util.module_from_spec(lister_spec)
lister_spec.loader.exec_module(lister)
checker_spec = importlib.util.spec_from_file_location('check_tts', ROOT/'scripts/check_tts.py')
checker = importlib.util.module_from_spec(checker_spec)
checker_spec.loader.exec_module(checker)


class EntryChecks(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        self.engine = self.home/'shared-engine'
        self.engine.mkdir()
        for name in ['ENGINE.md', 'VERSION', 'scripts/build_video.py',
                     'scripts/check_logic.py', 'scripts/check_audio_logic.py']:
            target = self.engine/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('9.8.7' if name == 'VERSION' else 'fixture')
        for agent in ['.codex', '.claude']:
            alias = self.home/agent/'skills/freelearn-video'
            alias.parent.mkdir(parents=True)
            alias.symlink_to(self.engine, target_is_directory=True)
        self.runtime = self.home/'runtime'
        for env in ['.venv', '.venv-audio']:
            python = self.runtime/env/'bin/python'
            python.parent.mkdir(parents=True)
            python.write_text('non-executable fixture; never launched')
        guard = patch('subprocess.run', side_effect=AssertionError('External process forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def invoke(self, args, codes=()):
        with patch.object(entry, 'resolve_engine', return_value=self.engine), \
             patch.object(entry, 'runtime_root', return_value=self.runtime), \
             patch('subprocess.run', side_effect=[SimpleNamespace(returncode=c) for c in codes]) as process, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = entry.main(args)
        return code, process, output.getvalue()

    def test_shared_aliases(self):
        self.assertEqual(entry.resolve_engine(self.home), self.engine.resolve())

    def test_engine_needs_no_registered_skill(self):
        self.assertFalse((self.engine/'SKILL.md').exists())
        self.assertTrue((self.engine/'ENGINE.md').is_file())
        self.assertEqual(entry.resolve_engine(self.home),self.engine.resolve())

    def test_missing_alias_stops(self):
        with self.assertRaisesRegex(RuntimeError, 'обе'):
            entry.resolve_engine(self.home/'missing')

    def test_divergent_aliases_stop(self):
        alias = self.home/'.claude/skills/freelearn-video'
        alias.unlink()
        other = self.home/'other'; other.mkdir()
        alias.symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'разным'):
            entry.resolve_engine(self.home)

    def test_incomplete_engine_stops(self):
        (self.engine/'scripts/check_logic.py').unlink()
        with self.assertRaisesRegex(RuntimeError, 'check_logic.py'):
            entry.resolve_engine(self.home)

    def test_status_is_inventory_without_child_process(self):
        code, process, output = self.invoke(['status'])
        data = json.loads(output)
        self.assertEqual(code, 0)
        process.assert_not_called()
        self.assertEqual(data['engine_version'], '9.8.7')
        self.assertFalse(data['render_started'])
        self.assertFalse(data['voice_synthesis_started'])
        self.assertFalse(data['python_available']['.venv-asr'])

    def test_default_is_status(self):
        code, process, output = self.invoke([])
        self.assertEqual(json.loads(output)['interface'], 'Создание видео')
        process.assert_not_called()
        self.assertEqual(code, 0)

    def test_build_guard_precedes_lookup(self):
        with patch.object(entry, 'resolve_engine', side_effect=AssertionError('Premature lookup')), \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            entry.main(['build', 'scenario.json'])
        self.assertEqual(error.exception.code, 2)

    def test_nonbuild_modes_reject_extra_arguments(self):
        for mode in ['status', 'check-entrypoint', 'check', 'check-audio']:
            for extra in ['--allow-render', 'scenario.json', '--preview']:
                with self.subTest(mode=mode, extra=extra), contextlib.redirect_stderr(io.StringIO()), \
                     self.assertRaises(SystemExit) as error:
                    entry.main([mode, extra])
                self.assertEqual(error.exception.code, 2)

    def test_build_requires_arguments(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            entry.main(['build', '--allow-render'])

    def test_runtime_override(self):
        self.assertEqual(entry.runtime_root(self.home, {}), self.home/'.local/share/freelearn-video')
        self.assertEqual(entry.runtime_root(self.home, {'FREELEARN_VIDEO_RUNTIME': str(self.runtime)}), self.runtime)
        for value in ['', '   ']:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                entry.runtime_root(self.home, {'FREELEARN_VIDEO_RUNTIME': value})

    def test_entrypoint_checks_need_no_engine_or_runtime(self):
        with patch.object(entry, 'resolve_engine', side_effect=AssertionError('Engine lookup')), \
             patch.object(entry, 'runtime_root', side_effect=AssertionError('Runtime lookup')), \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=0)) as process, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(entry.main(['check-entrypoint']), 0)
        self.assertEqual(process.call_args.args[0], [sys.executable, str(ROOT/'scripts/check_entrypoint.py')])

    def test_check_runs_interface_before_engine(self):
        code, process, _ = self.invoke(['check'], [0, 7])
        calls = process.call_args_list
        self.assertEqual(code, 7)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[0][1], str(ROOT/'scripts/check_entrypoint.py'))
        self.assertEqual(calls[1].args[0], [str(self.runtime/'.venv/bin/python'), str(self.engine/'scripts/check_logic.py')])

    def test_interface_failure_stops_before_engine_lookup(self):
        with patch.object(entry, 'resolve_engine', side_effect=AssertionError('Engine lookup')), \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=3)) as process, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(entry.main(['check']), 3)
        self.assertEqual(process.call_count, 1)

    def test_audio_routes_only_numeric_suite(self):
        code, process, _ = self.invoke(['check-audio'], [0])
        self.assertEqual(code, 0)
        self.assertEqual(process.call_args.args[0], [str(self.runtime/'.venv-audio/bin/python'), str(self.engine/'scripts/check_audio_logic.py')])

    def test_missing_runtime_does_not_launch_backend(self):
        (self.runtime/'.venv/bin/python').unlink()
        with self.assertRaisesRegex(RuntimeError, 'окружения'):
            self.invoke(['build', '--allow-render', 'scenario.json'])

    def test_build_forwards_arguments_and_exit_code_without_shell(self):
        args = ['/tmp/scenario with spaces.json', '-o', '/tmp/video.mp4', '--voice', 'review']
        code, process, _ = self.invoke(['build', '--allow-render', *args], [7])
        self.assertEqual(code, 7)
        self.assertEqual(process.call_args.args[0], [str(self.runtime/'.venv/bin/python'), str(self.engine/'scripts/build_video.py'), *args])
        self.assertNotIn('shell', process.call_args.kwargs)
        self.assertEqual(process.call_args.kwargs['env']['PYTHONDONTWRITEBYTECODE'], '1')


    def test_skill_card_uses_new_name(self):
        text = (ROOT/'SKILL.md').read_text(encoding='utf-8')
        head = text.split('---')[1]
        self.assertRegex(head, r'(?m)^name: sozdanie-video$')
        description = re.search(r'(?m)^description: (.+)$', head).group(1)
        self.assertIn('Создание видео', description)
        self.assertIn('VideoFreeLearn', description)  # old trigger still finds the skill
        self.assertIn('display_name: "Создание видео"', (ROOT/'agents/openai.yaml').read_text(encoding='utf-8'))
        for name in re.findall(r'`references/([^`]+)`', text):
            with self.subTest(reference=name):
                self.assertTrue((ROOT/'references'/name).is_file())

    def test_lexicon_shape(self):
        data = json.loads((ROOT/'references/proiznoshenie.json').read_text(encoding='utf-8'))
        self.assertEqual(data['format'], 1)
        seen = set()
        for item in data['entries']:
            with self.subTest(written=item.get('written')):
                self.assertTrue({'written', 'say', 'kind', 'date', 'source', 'note', 'group'} <= set(item))
                self.assertIn(item['group'], lister.GROUPS)
                if item['kind'] == 'замена слова':
                    self.assertTrue(item.get('forms'))  # the check needs the exact word forms to replace
                self.assertIn(item['kind'], {'произношение', 'замена слова'})
                self.assertRegex(item['date'], r'^\d{4}-\d{2}-\d{2}$')
                self.assertNotIn(ACUTE, item['written'])
                self.assertNotIn(item['written'].lower(), seen)
                seen.add(item['written'].lower())
                # The voice reads Russian: Cyrillic, spaces, hyphens and the combining acute only.
                self.assertRegex(item['say'], '^[А-Яа-яЁё \\-' + ACUTE + ']+$')
                for form in item.get('avoid', []):
                    self.assertRegex(form, '^[А-Яа-яЁё \\-' + ACUTE + ']+$')
                for word in re.split(r'[ -]', item['say']):
                    self.assertLessEqual(word.count(ACUTE), 1)
                    for i, char in enumerate(word):
                        if char == ACUTE:
                            self.assertIn(word[i-1].lower(), VOWELS)

    def test_lexicon_keeps_latest_corrections(self):
        say = {i['written']: i['say'] for i in json.loads((ROOT/'references/proiznoshenie.json').read_text(encoding='utf-8'))['entries']}
        expected = {'PLA': 'пээла́', 'TPU': 'тэпэу́', 'AMS': 'аэмэ́с', 'ASA': 'А́са', 'Y (ось)': 'и́грик',
                    'дрыгостол': 'дрыгосто́л', 'дрыгостолы': 'дрыги', 'хотэнд': 'хотэ́нд', 'постепенно': 'постепе́нно',
                    'Bambu Lab A1': 'Бамбу Лаб а-оди́н', 'ИИ': 'И И'}
        for written, value in expected.items():
            with self.subTest(written=written):
                self.assertEqual(say.get(written), value)

    def test_readable_list_matches_lexicon(self):
        data = json.loads((ROOT/'references/proiznoshenie.json').read_text(encoding='utf-8'))
        self.assertEqual((ROOT/'references/spisok-udareniy.md').read_text(encoding='utf-8'), lister.render(data))
        roman = [e for e in data['entries'] if e['group'] == 'Правки Романа']
        self.assertTrue(roman and all(e['source'] == 'Роман' for e in roman))

    def test_status_reports_stale_engine_pointer(self):
        _, _, output = self.invoke(['status'])
        self.assertFalse(json.loads(output)['engine_points_to_skill'])
        (self.engine/'ENGINE.md').write_text('Вход — навык «Создание видео» (`~/.codex/skills/sozdanie-video`).', encoding='utf-8')
        _, _, output = self.invoke(['status'])
        self.assertTrue(json.loads(output)['engine_points_to_skill'])

    def scenario(self, rows):
        path = self.home/'scenario.json'
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        return checker.check_file(path, checker.load_lexicon())

    def test_tts_check_catches_repeated_mistakes(self):
        errors, _ = self.scenario([{'narration': 'Для начала хватит PLA. Bambu Lab A1 mini — дрыгостол, такие дрыгостолы постепенно стали популярны. AMS меняет пластик, головка движется по оси Y.',
                                    'tts_text': 'Для начала хватит пэ-эл-а. Бамбу А один мини — дры́гостол, такие дрыгостолы посте́пенно стали популярны. Эйэмэс меняет пластик, головка движется по оси игрек.'}])
        text = '\n'.join(errors)
        for word in ['PLA', 'дрыгостол', 'дрыгостолы', 'постепенно', 'AMS', 'головка', 'Y', 'Bambu Lab A1', 'для начала']:
            with self.subTest(word=word):
                self.assertIn('«' + word, text)

    def test_tts_check_accepts_roman_forms(self):
        errors, _ = self.scenario([{'narration': 'Для начала хватит PLA. Bambu Lab A1 mini — это дрыгостол; такие дрыги постепенно стали популярны. AMS меняет пластик, а хотэнд его плавит. Голова принтера движется по оси Y. С вами был ИИ-ассистент.',
                                    'tts_text': 'Для нача́ла хва́тит пээла́. Бамбу Лаб а-оди́н ми́ни — э́то дрыгосто́л; таки́е дрыги постепе́нно ста́ли популя́рны. Аэмэ́с меня́ет пла́стик, а хотэ́нд ево́ пла́вит. Голова́ при́нтера дви́жется по оси́ и́грик. С ва́ми был И И ассисте́нт.'}])
        self.assertEqual(errors, [])

    def test_tts_ego_uses_phonetic_v(self):
        errors, _ = self.scenario([{'narration': 'После засветки его нужно отделить.',
                                    'tts_text': 'После засветки его́ нужно отделить.'}])
        self.assertTrue(any('«его»' in e and 'ево́' in e for e in errors), errors)
        errors, _ = self.scenario([{'narration': 'После засветки его нужно отделить.',
                                    'tts_text': 'После засветки ево́ нужно отделить.'}])
        self.assertEqual(errors, [])








    def test_retired_backend_flag_stops_before_reading_or_synthesis(self):
        with patch.object(checker, 'load_lexicon', side_effect=AssertionError('No work for retired options')), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(checker.main(['--qwen', 'scenario.json']), 2)

    def test_open_at_reads_timestamps_and_runs_quicktime_without_shell(self):
        # Roman, 2026-10-29: «открывай на нужном тайменге когда вопросы задаешь»
        spec = importlib.util.spec_from_file_location('open_at', ROOT/'scripts/open_at.py')
        opener = importlib.util.module_from_spec(spec); spec.loader.exec_module(opener)
        for text, value in [('13', 13), ('0:13', 13), ('6:53', 413), ('1:02:03', 3723), ('5:48,5', 348)]:
            with self.subTest(text=text):
                self.assertEqual(opener.seconds(text), value)
        for bad in ['', 'a:b', '1:2:3:4', '-5']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                opener.seconds(bad)
        media = self.home/'ролик.mp4'; media.write_bytes(b'x')
        with patch.object(opener.subprocess, 'run') as run:
            opener.main([str(media), '6:53'])
        args = run.call_args.args[0]
        self.assertEqual(args[0], 'osascript'); self.assertEqual(args[-3:], [str(media.resolve()), '413', 'pause'])
        with self.assertRaises(SystemExit):
            opener.main([str(self.home/'нет такого.mp4'), '0:13'])


    def test_tts_check_forbidden_form_without_subtitle_word(self):
        errors, _ = self.scenario({'scenes': [{'narration': 'Система меняет нить.', 'tts_text': 'Эйэмэс меняет нить.'}]})
        self.assertTrue(any('эйэмэс' in e for e in errors))

    def test_tts_check_engine_format_russian_prose_passes(self):
        errors, _ = self.scenario({'scenes': [{'narration': 'Сядьте удобно и постепенно отпустите напряжение.', 'caption': 'Дыхание'}]})
        self.assertEqual(errors, [])

    def test_tts_check_accepts_spelling_and_punctuation_variants(self):
        # Roman gave no stress for PETG/ABS; Codex wrote «пэтджи́», «абээ́с»; «И. И,» is the separate letters he asked for.
        errors, _ = self.scenario([{'narration': 'PETG и ABS. Технологии — печать нитью и смолой. В этом видео говорим об FDM-печати. С вами был ИИ-ассистент 3D Magic.',
                                    'tts_text': 'Пэтджи́ и абээ́с. Техноло́гии — печа́ть ни́тью и смоло́й. В э́том ви́део говори́м об эфдээ́м-печа́ти. С ва́ми был И. И, ассисте́нт три дэ мэ́джик.'}])
        self.assertEqual(errors, [])

    def test_tts_check_rejected_phrase_about_fdm(self):
        errors, _ = self.scenario([{'narration': 'В этом видео говорим о печати нитью.', 'tts_text': 'В э́том ви́део говори́м о печа́ти ни́тью.'}])
        self.assertTrue(any('говорим о печати нитью' in e for e in errors))

    def test_tts_check_adverb_entry_ignores_adjective(self):
        errors, _ = self.scenario([{'narration': 'Постепенная калибровка стола.', 'tts_text': 'Постепе́нная калибро́вка стола́.'}])
        self.assertEqual(errors, [])
        errors, _ = self.scenario([{'narration': 'Увеличивайте постепенно.', 'tts_text': 'Увели́чивайте посте́пенно.'}])
        self.assertTrue(errors)

    def test_tts_check_refuses_file_without_lines(self):
        path = self.home/'other.json'
        path.write_text(json.dumps({'scenes': [{'text': 'PLA', 'speech': 'пэ-эл-а'}]}), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(checker.main([str(path)]), 2)
        self.assertIn('narration', err.getvalue())

if __name__ == '__main__':
    unittest.main(verbosity=2)
