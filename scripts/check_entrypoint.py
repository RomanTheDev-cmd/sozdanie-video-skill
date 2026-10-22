#!/usr/bin/env python3
"""Portable stdlib checks. Every subprocess is mocked; no media or models."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('video_entry', ROOT/'scripts/engine.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


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
        self.assertFalse(data['python_available']['.venv-qwen'])

    def test_default_is_status(self):
        code, process, output = self.invoke([])
        self.assertEqual(json.loads(output)['interface'], 'VideoFreeLearn')
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
