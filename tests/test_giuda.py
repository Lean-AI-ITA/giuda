"""Test di Giuda. Solo libreria standard: python -m unittest discover -s tests -v

Il test end-to-end usa un finto GitHub e un finto LLM in locale: nessuna chiamata esterna.
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAKE_PORT = 18998
APP_PORT = 18765
os.environ["GIUDA_GITHUB_API"] = f"http://127.0.0.1:{FAKE_PORT}"
os.environ["GIUDA_PORT"] = str(APP_PORT)
# dati e recensioni dei test in una cartella temporanea: mai nella tua installazione
_TMP_HOME = tempfile.mkdtemp(prefix="giuda-test-")
os.environ["GIUDA_HOME"] = _TMP_HOME

import giuda  # noqa: E402

SHA = "a" * 40
REVIEW = """## Verdetto: RIFALLO
Questo non e' un commit, e' una confessione.

## Problemi
### 🔥 Tradimento Chiave nel codice — `src/app.py:1`
- **Perche':** segreto nel repository
- **Correzione:** variabile d'ambiente
- **Certezza:** [evidente dal diff]
"""
# Formato reale della risposta /models di OpenRouter (prezzi per token, stringhe)
OPENROUTER_MODELS = {"data": [
    {"id": "anthropic/claude-sonnet-4", "name": "Anthropic: Claude Sonnet 4", "context_length": 200000,
     "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
    {"id": "qwen/qwen-2.5-coder-32b-instruct:free", "name": "Qwen2.5 Coder 32B (free)", "context_length": 32768,
     "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "openai/gpt-4o-mini", "name": "OpenAI: GPT-4o-mini", "context_length": 128000,
     "pricing": {"prompt": "0.00000015", "completion": "0.0000006"}},
]}
CALLS = []
HEADERS = []


class FakeHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-RateLimit-Remaining", "4999")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        HEADERS.append(dict(self.headers))
        commit = {"sha": SHA, "parents": [{}],
                  "commit": {"message": "fix", "author": {"name": "Dev", "date": "2026-10-04T02:00:00Z"}}}
        if self.path == "/repos/Lean-AI-ITA/demo":
            return self._json({"default_branch": "main"})
        if self.path.startswith("/repos/Lean-AI-ITA/demo/commits?"):
            return self._json([commit])
        if self.path.startswith("/repos/Lean-AI-ITA/demo/commits/"):
            return self._json(dict(commit, files=[
                {"filename": "src/app.py", "status": "modified", "additions": 1, "deletions": 0,
                 "patch": "+API_KEY = 'sk-123'"},
                {"filename": "package-lock.json", "status": "modified", "patch": "+x"},
            ]))
        if self.path == "/v1/models":
            return self._json(OPENROUTER_MODELS)
        if self.path == "/plain/models":  # formato minimo (LM Studio / Ollama)
            return self._json({"data": [{"id": "qwen2.5-coder-14b-instruct"}, {"id": "llama3"}]})
        return self._json({"message": "Not Found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        CALLS.append(body)
        if self.path.startswith("/empty/"):  # modello che ragiona e non scrive mai
            return self._json({"model": body["model"], "choices": [
                {"message": {"content": "", "reasoning": "penso..."}, "finish_reason": "length"}]})
        if self.path.startswith("/think/"):  # vuoto al primo colpo, ok col budget alzato
            if (body.get("max_tokens") or 0) < 16000:
                return self._json({"model": body["model"], "choices": [
                    {"message": {"content": None}, "finish_reason": "length"}]})
        return self._json({"model": body["model"], "choices": [{"message": {"content": "<think>x</think>" + REVIEW}}]})


class TestParsing(unittest.TestCase):
    def test_parse_repo_url(self):
        cases = {
            "https://github.com/Lean-AI-ITA/giuda": ("Lean-AI-ITA", "giuda", None),
            "https://github.com/Lean-AI-ITA/giuda.git": ("Lean-AI-ITA", "giuda", None),
            "https://github.com/Lean-AI-ITA/giuda/": ("Lean-AI-ITA", "giuda", None),
            "https://github.com/Lean-AI-ITA/giuda/tree/dev": ("Lean-AI-ITA", "giuda", "dev"),
            "git@github.com:Lean-AI-ITA/giuda.git": ("Lean-AI-ITA", "giuda", None),
            "Lean-AI-ITA/trascrittore": ("Lean-AI-ITA", "trascrittore", None),
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(giuda.parse_repo_url(url), expected)

    def test_parse_repo_url_rifiuta_input_sbagliati(self):
        for bad in ["", "ciao mondo", "https://gitlab.com/a/b", "solo-una-parola"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    giuda.parse_repo_url(bad)

    def test_parse_verdict(self):
        self.assertEqual(giuda.parse_verdict("## Verdetto: TI ASSOLVO\nok"), "TI ASSOLVO")
        self.assertEqual(giuda.parse_verdict("## Verdetto: **DA RIVEDERE**"), "DA RIVEDERE")
        self.assertEqual(giuda.parse_verdict("## Verdetto: RIFALLO"), "RIFALLO")
        self.assertEqual(giuda.parse_verdict("nessun verdetto"), "?")

    def test_rate_limit_pausa(self):
        vecchio = dict(giuda.STATUS)
        try:
            giuda.STATUS.update(rate_remaining="2", rate_reset_epoch=time.time() + 600)
            self.assertTrue(giuda.rate_limited())
            giuda.STATUS.update(rate_reset_epoch=time.time() - 1)
            self.assertFalse(giuda.rate_limited(), "dopo il reset deve ripartire")
            giuda.STATUS.update(rate_remaining="4999", rate_reset_epoch=time.time() + 600)
            self.assertFalse(giuda.rate_limited())
        finally:
            giuda.STATUS.clear(); giuda.STATUS.update(vecchio)

    def test_header_llm(self):
        h = giuda._llm_headers("https://openrouter.ai/api/v1/models", "sk-or-1")
        self.assertEqual(h["Authorization"], "Bearer sk-or-1")
        self.assertNotIn("x-api-key", h, "la chiave OpenRouter non va mandata come x-api-key")
        a = giuda._llm_headers("https://api.anthropic.com/v1/models", "sk-ant-1")
        self.assertEqual(a["x-api-key"], "sk-ant-1")
        self.assertIn("anthropic-version", a)


class TestPrompt(unittest.TestCase):
    def test_istituzionale_senza_battute(self):
        p = giuda.system_prompt("istituzionale").lower()
        self.assertNotIn("repertorio", p)
        for parola in ("vaffa", "cagare", "sfott"):
            self.assertNotIn(parola, p)

    def test_comico_contiene_repertorio_e_formato_in_coda(self):
        p = giuda.system_prompt("comico")
        self.assertIn("REPERTORIO", p)
        self.assertIn("FORMATO OBBLIGATORIO", p[-2500:])

    def test_checklist_completa(self):
        p = giuda.system_prompt("comico").lower()
        for voce in ("owasp", "idor", "injection", "xss", "csrf", "ssrf", "path traversal", "n+1",
                     "timeout", "backoff", "race condition", "deadlock", "gdpr", "migrazioni"):
            with self.subTest(voce=voce):
                self.assertIn(voce, p)

    def test_repertorio_rotto_non_blocca(self):
        originale = giuda.REPERTORIO_FILE
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{rotto")
        try:
            giuda.REPERTORIO_FILE = Path(f.name)
            self.assertNotIn("REPERTORIO", giuda.system_prompt("comico"))
        finally:
            giuda.REPERTORIO_FILE = originale
            os.unlink(f.name)

    def test_lock_file_esclusi_dal_diff(self):
        repo = {"owner": "o", "name": "r", "branch": "main"}
        commit = {"sha": SHA, "commit": {"message": "m", "author": {"name": "a"}},
                  "files": [{"filename": "package-lock.json", "status": "modified", "patch": "+x"},
                            {"filename": "a.py", "status": "modified", "patch": "+y"}]}
        prompt, n, truncated = giuda.build_user_prompt(repo, commit, 60000)
        self.assertIn("### FILE: a.py", prompt)
        self.assertNotIn("### FILE: package-lock.json", prompt)
        self.assertEqual(n, 2)
        self.assertFalse(truncated)


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(("127.0.0.1", FAKE_PORT), FakeHandler)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        sys.argv = ["giuda", "--no-browser"]
        threading.Thread(target=giuda.main, daemon=True).start()
        time.sleep(1.5)

    @classmethod
    def tearDownClass(cls):
        giuda.STOP.set()
        cls.fake.shutdown()

    def call(self, path, body=None, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(f"http://127.0.0.1:{APP_PORT}{path}",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers=headers, method="GET" if body is None else "POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_flusso_completo(self):
        code, _ = self.call("/api/config", {"llm_base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                                            "llm_model": "anthropic/claude-sonnet-4", "llm_api_key": "sk-segreta1234"})
        self.assertEqual(code, 200)
        _, state = self.call("/api/state")
        self.assertEqual(state["config"]["llm_api_key"], "•••• 1234", "la chiave non deve uscire in chiaro")

        code, r = self.call("/api/repos", {"url": "https://github.com/Lean-AI-ITA/demo", "review_now": True})
        self.assertEqual(code, 200, r)
        code, r = self.call("/api/repos", {"url": "Lean-AI-ITA/demo"})
        self.assertEqual(code, 400, "duplicato non rifiutato")

        for _ in range(50):
            _, reviews = self.call("/api/reviews")
            if reviews and reviews[0]["status"] == "ok":
                break
            time.sleep(0.2)
        self.assertEqual(reviews[0]["verdict"], "RIFALLO")
        _, detail = self.call(f"/api/reviews/{reviews[0]['id']}")
        self.assertNotIn("<think>", detail["content"], "il ragionamento interno va rimosso")
        self.assertTrue(Path(detail["file_path"]).exists(), "recensione Markdown non salvata")
        self.assertEqual(CALLS[-1]["model"], "anthropic/claude-sonnet-4", "il nome OpenRouter va passato intero")
        self.assertNotIn("package-lock", CALLS[-1]["messages"][-1]["content"].split("DIFF:")[1])

    def test_modelli_openrouter_con_prezzi(self):
        base = urllib.parse.quote(f"http://127.0.0.1:{FAKE_PORT}/v1")
        _, r = self.call(f"/api/models?base_url={base}")
        ids = [m["id"] for m in r["models"]]
        self.assertEqual(len(ids), 3)
        self.assertIn("anthropic/claude-sonnet-4", ids, "il prefisso fornitore/ deve restare")
        claude = next(m for m in r["models"] if m["id"] == "anthropic/claude-sonnet-4")
        self.assertEqual(claude["ctx"], 200000)
        self.assertEqual(claude["price_in"], "0.000003")
        self.assertFalse(claude["free"])
        free = next(m for m in r["models"] if m["id"].endswith(":free"))
        self.assertTrue(free["free"])

    def test_modelli_formato_minimo(self):
        base = urllib.parse.quote(f"http://127.0.0.1:{FAKE_PORT}/plain")
        _, r = self.call(f"/api/models?base_url={base}")
        self.assertEqual([m["id"] for m in r["models"]], ["llama3", "qwen2.5-coder-14b-instruct"])

    def _cfg(self, path):
        cfg = dict(giuda.DEFAULT_CONFIG)
        cfg.update(llm_base_url=f"http://127.0.0.1:{FAKE_PORT}/{path}", llm_model="qwen/qwen3.8-max-prime",
                   max_tokens=4096)
        return cfg

    def test_risposta_vuota_riprova_con_piu_token(self):
        text, _ = giuda.llm_chat([{"role": "user", "content": "x"}], self._cfg("think/v1"))
        self.assertIn("Verdetto", text)
        self.assertEqual(CALLS[-1]["max_tokens"], 16000)

    def test_risposta_sempre_vuota_e_errore_chiaro(self):
        with self.assertRaises(giuda.LLMError) as ctx:
            giuda.llm_chat([{"role": "user", "content": "x"}], self._cfg("empty/v1"))
        self.assertIn("vuota", str(ctx.exception))
        self.assertIn("length", str(ctx.exception))

    def test_contenuto_a_parti(self):
        self.assertEqual(giuda._extract_text({"content": [{"type": "text", "text": "ab"}, {"type": "text", "text": "c"}]}), "abc")
        self.assertEqual(giuda._extract_text({"content": None}), "")

    def test_dati_dei_test_isolati(self):
        self.assertTrue(str(giuda.DATA).startswith(_TMP_HOME))
        self.assertFalse((ROOT / "data" / "config.json").exists(), "i test non devono scrivere nella cartella del programma")

    def test_origine_esterna_bloccata(self):
        code, _ = self.call("/api/shutdown", {}, origin="http://sito-malevolo.example")
        self.assertEqual(code, 403)


import urllib.parse  # noqa: E402

def tearDownModule():
    import shutil
    shutil.rmtree(_TMP_HOME, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
