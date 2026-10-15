"""Offline behavioral checks; no Graphify installation, service keys or network."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import graphify_runner as runner


class GuardedDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="graphify test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repository with spaces"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write("go.mod", "module example.invalid/fixture\n\ngo 1.25\n")
        self.write("main.go", "package main\nfunc main() { helper() }\nfunc helper() {}\n")
        self.write("other.go", "package main\nfunc other() {}\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.cache = self.root / "cache"
        self.log = self.root / "runtime-calls.jsonl"
        self.runtime = self.fake_runtime()

    def write(self, name, data):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
        return path

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.DEVNULL).decode().strip()

    def args(self, command="build", **overrides):
        values = dict(repo=self.repo, runtime=self.runtime, cache_root=self.cache, timeout=10, budget=2000, question="main helper", command=command)
        values.update(overrides)
        return argparse.Namespace(**values)

    def fake_runtime(self, *, version=runner.VERSION, mode="ok", query_exit=0, long_query=False):
        path = self.root / "graphify"
        script = f'''#!{sys.executable}
import sys,os,json,time,subprocess
from pathlib import Path
args=sys.argv[1:]
log=Path({str(self.log)!r})
with log.open('a') as f: f.write(json.dumps({{'args':args,'env':dict(os.environ)}})+'\\n')
if args==['--version']:
 print('graphify {version}');raise SystemExit(0)
if args[0]=='extract':
 assert args[2:]==['--code-only','--no-dedup'],args
 if {mode!r}=='fail': raise SystemExit(9)
 if {mode!r}=='timeout':
  subprocess.Popen([sys.executable,'-c',"import time;from pathlib import Path;time.sleep(0.7);Path("+repr({str(self.root / 'late-child')!r})+").write_text('late')"])
  time.sleep(5)
 snapshot=Path(args[1]);out=Path(os.environ['GRAPHIFY_OUT']);out.mkdir(parents=True)
 files=sorted(snapshot.rglob('*.go'))
 if {mode!r}=='omit': files=files[:1]
 nodes=[{{'id':str(i),'label':p.stem,'source_file':str(p),'source_location':'1'}} for i,p in enumerate(files)]
 edges=[{{'source':'0','target':'1','relation':'calls','confidence':'INFERRED','source_file':str(files[0]),'source_location':'2'}}] if len(files)>1 else []
 if {mode!r}=='foreign': nodes[0]['source_file']='/outside/secret.go'
 if {mode!r}=='location': nodes[0]['source_location']='L9999'
 (out/'graph.json').write_text(json.dumps({{'nodes':nodes,'links':edges,'directed':False}}))
 if {mode!r}=='change': Path({str(self.repo / 'main.go')!r}).write_text('package main\\nfunc changed(){{}}\\n')
 raise SystemExit(0)
if args[0]=='query':
 graph=json.loads(Path(args[args.index('--graph')+1]).read_text())
 if {long_query!r}: print('x'*50000)
 else:
  for n in graph['nodes']: print('NODE '+n['label']+' [src='+n['source_file']+' loc=1]')
  print('EDGE main --calls [INFERRED]--> other')
 raise SystemExit({query_exit})
raise SystemExit(8)
'''
        path.write_text(script)
        path.chmod(0o700)
        return path

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_fresh_build_query_maps_paths_and_preserves_inferred_labels(self):
        result = runner.build(self.args())
        self.assertFalse(result["reused"])
        graph = json.loads(Path(result["graph"]).read_bytes())
        self.assertTrue(all(n["source_file"].startswith(str(self.repo.resolve())) for n in graph["nodes"]))
        self.assertEqual(graph["links"][0]["confidence"], "INFERRED")
        query = runner.query(self.args("query"))
        self.assertEqual(query["status"], "ok")
        self.assertIn("INFERRED", query["context"])
        self.assertIn("interfaces", query["qualification"])
        self.assertFalse((self.repo / "graphify-out").exists())
        self.assertTrue(runner.build(self.args())["reused"])
        self.assertEqual(sum(c["args"][0] == "extract" for c in self.calls()), 1)

    def test_exclusions_and_untracked_files_never_enter_snapshot(self):
        for name in ("third_party/library/a.go", "vendor/b.go", "internal/testdata/c.go", "fixtures/d.go"):
            self.write(name, "package excluded\n")
        self.git("add", ".")
        self.write("untracked.go", "package secret\n")
        result = runner.build(self.args())
        ready = json.loads((Path(result["graph"]).parents[1] / "ready.json").read_bytes())
        self.assertEqual([f["path"] for f in ready["source"]["files"]], ["go.mod", "main.go", "other.go"])

    def test_minimal_environment_blocks_credentials_and_inherited_modes(self):
        secret_names = ("OPENAI_API_KEY", "TYPESAFE_API_KEY", "SUBQ_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "PYTHONPATH", "GRAPHIFY_QUERY_LOG", "GRAPHIFY_QUERY_LOG_ENABLE", "GRAPHIFY_OUT")
        with patch.dict(os.environ, {k: "do-not-forward" for k in secret_names}):
            runner.build(self.args())
            runner.query(self.args("query"))
        for call in self.calls():
            env = call["env"]
            for name in secret_names:
                if name != "GRAPHIFY_OUT":
                    self.assertNotIn(name, env)
            self.assertEqual(env["GRAPHIFY_NO_AUTO_REFRESH"], "1")
            self.assertEqual(env["GRAPHIFY_QUERY_LOG_DISABLE"], "1")
            self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertEqual(env["PYTHONHASHSEED"], "0")
            self.assertNotEqual(env["HOME"], str(Path.home()))
            self.assertTrue(env["XDG_CONFIG_HOME"].startswith(env["HOME"]))
            self.assertFalse(Path(env["HOME"]).exists())

    def test_unsupported_process_platform_is_rejected_before_spawning(self):
        with patch.object(runner.os, "name", "nt"), self.assertRaises(runner.DiscoveryError) as failure:
            runner.process([], cwd=".", env={}, timeout=1)
        self.assertEqual(failure.exception.code, "platform")

    def test_missing_and_wrong_runtime_fail_before_extraction(self):
        with self.assertRaisesRegex(runner.DiscoveryError, "Install graphifyy"):
            runner.build(self.args(runtime=self.root / "missing"))
        self.fake_runtime(version="0.0.1")
        with self.assertRaisesRegex(runner.DiscoveryError, "requires graphifyy"):
            runner.build(self.args())
        self.assertFalse(any(c["args"][0] == "extract" for c in self.calls()))

    def test_missing_dirty_branch_and_corrupt_graphs_are_refused(self):
        with self.assertRaises(runner.DiscoveryError) as missing:
            runner.query(self.args("query"))
        self.assertEqual(missing.exception.code, "stale_graph")
        result = runner.build(self.args())
        self.write("main.go", "package main\nfunc changed() {}\n")
        with self.assertRaises(runner.DiscoveryError):
            runner.query(self.args("query"))
        self.git("checkout", "--", "main.go")
        self.git("checkout", "-qb", "another-branch")
        with self.assertRaises(runner.DiscoveryError):
            runner.query(self.args("query"))
        self.git("checkout", "-")
        Path(result["graph"]).write_text('{"nodes":[]}')
        with self.assertRaises(runner.DiscoveryError):
            runner.query(self.args("query"))

    def test_tracked_deletion_and_new_tracked_source_change_fingerprint(self):
        before, _ = runner.source(self.repo)
        (self.repo / "other.go").unlink()
        deleted, _ = runner.source(self.repo)
        self.assertNotEqual(before["source_sha256"], deleted["source_sha256"])
        self.write("new.go", "package main\n")
        self.git("add", "new.go")
        added, _ = runner.source(self.repo)
        self.assertNotEqual(deleted["source_sha256"], added["source_sha256"])

    def test_escaping_and_internal_source_symlinks_are_refused(self):
        outside = self.root / "outside.go"
        outside.write_text("package outside\n")
        for target in (outside, self.repo / "main.go"):
            link = self.repo / "linked.go"
            link.symlink_to(target)
            self.git("add", "linked.go")
            with self.assertRaises(runner.DiscoveryError) as failure:
                runner.source(self.repo)
            self.assertEqual(failure.exception.code, "source_symlink")
            self.git("rm", "-f", "linked.go")

    def test_cache_inside_repository_or_skill_snapshot_is_refused(self):
        with self.assertRaises(runner.DiscoveryError):
            runner.build(self.args(cache_root=self.repo / ".cache"))
        released = self.root / "managed-release"
        released.mkdir()
        (released / "skills-manifest.json").write_text("{}")
        with self.assertRaises(runner.DiscoveryError):
            runner.build(self.args(cache_root=released / "cache"))

    def test_cache_child_redirects_cannot_write_into_repository_or_release(self):
        state, _ = runner.source(self.repo)
        parent, entry = runner.cache_paths(state, self.cache)
        self.cache.mkdir()
        parent.symlink_to(self.repo, target_is_directory=True)
        before = self.repo.stat().st_mode
        with self.assertRaises(runner.DiscoveryError):
            runner.build(self.args())
        self.assertEqual(self.repo.stat().st_mode, before)
        parent.unlink()
        parent.mkdir()
        entry.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaises(runner.DiscoveryError):
            runner.build(self.args())
        entry.unlink()
        result = runner.build(self.args())
        ready = Path(result["graph"]).parents[1] / "ready.json"
        saved = self.root / "saved-ready.json"
        ready.rename(saved)
        ready.symlink_to(saved)
        with self.assertRaises(runner.DiscoveryError):
            runner.query(self.args("query"))

    def test_failed_partial_foreign_and_bad_line_builds_never_publish_ready(self):
        for mode in ("fail", "omit", "foreign", "location", "change"):
            with self.subTest(mode=mode):
                self.fake_runtime(mode=mode)
                with self.assertRaises(runner.DiscoveryError):
                    runner.build(self.args())
                self.assertFalse(list(self.cache.rglob("ready.json")))
                self.assertFalse(list(self.cache.rglob(".build-*")))

    def test_timeout_kills_owned_delayed_child_and_leaves_no_active_graph(self):
        self.fake_runtime(mode="timeout")
        with self.assertRaises(runner.DiscoveryError) as failure:
            runner.build(self.args(timeout=0.15))
        self.assertEqual(failure.exception.code, "timeout")
        time.sleep(0.9)
        self.assertFalse((self.root / "late-child").exists())
        self.assertFalse(list(self.cache.rglob("ready.json")))

    def test_ambiguous_no_match_and_output_budget_remain_explicit(self):
        runner.build(self.args())
        for rc, status in ((3, "ambiguous"), (4, "no_match")):
            self.fake_runtime(query_exit=rc)
            self.assertEqual(runner.query(self.args("query"))["status"], status)
        self.fake_runtime(long_query=True)
        result = runner.query(self.args("query", budget=100))
        self.assertTrue(result["truncated"])
        self.assertLessEqual(result["context_chars"], 300)
        self.assertIn("unknown", result["truncation_notice"])

    def test_invalid_budgets_and_timeouts_are_rejected(self):
        for extra in (("--budget", "0"), ("--timeout", "nan"), ("--timeout", "inf"), ("--timeout", "-1")):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.main(["query", "--repo", str(self.repo), "helper", *extra])


if __name__ == "__main__":
    unittest.main()
