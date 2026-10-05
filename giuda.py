#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GIUDA - il boss di fine livello del tuo codice. "Chi l'ha deciso!!!"
Sorveglia repository GitHub e giudica ogni nuovo commit con un LLM
locale (LM Studio / Ollama) o via API (OpenAI, Anthropic, OpenRouter, Mistral...).

Zero dipendenze: solo libreria standard Python 3.9+.
Gira solo su 127.0.0.1 (non e' raggiungibile da altri PC).

Licenza MIT - https://github.com/Lean-AI-ITA/giuda
"""
import json
import logging
import os
import queue
import random
import re
import sqlite3
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path

VERSION = "1.7.0"
BASE = Path(__file__).resolve().parent
# GIUDA_HOME permette di spostare dati e recensioni (usato dai test per non toccare la tua installazione)
HOME = Path(os.environ["GIUDA_HOME"]) if os.environ.get("GIUDA_HOME") else BASE
DATA = HOME / "data"
REVIEWS_DIR = HOME / "recensioni"
WEB = BASE / "web"
DATA.mkdir(parents=True, exist_ok=True)
REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = DATA / "config.json"
DB_FILE = DATA / "giuda.db"
REPERTORIO_FILE = BASE / "repertorio.json"
PORT = int(os.environ.get("GIUDA_PORT", "8765"))
GITHUB_API = os.environ.get("GIUDA_GITHUB_API", "https://api.github.com").rstrip("/")

# ---------------------------------------------------------------- log
log = logging.getLogger("giuda")
log.setLevel(logging.INFO)
_fh = RotatingFileHandler(DATA / "giuda.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_fh)
if sys.stdout and sys.stdout.isatty():
    log.addHandler(logging.StreamHandler(sys.stdout))

# ---------------------------------------------------------------- config
DEFAULT_CONFIG = {
    "llm_preset": "lmstudio",
    "llm_base_url": "http://localhost:1234/v1",
    "llm_api_key": "",
    "llm_model": "",
    "temperature": 0.3,
    "max_tokens": 4096,          # 0 = non inviare il parametro
    "max_diff_chars": 60000,     # oltre, il diff viene troncato
    "github_token": "",
    "poll_seconds": 120,
    "max_commits_per_check": 5,
    "skip_merge_commits": True,
    "persona": "comico",         # comico | istituzionale
    "post_github_comment": False,
    "reasoning_effort": "low",   # solo OpenRouter: low | medium | high | off
}
SECRET_KEYS = ("llm_api_key", "github_token")
_cfg_lock = threading.Lock()


def get_config():
    with _cfg_lock:
        cfg = dict(DEFAULT_CONFIG)
        if CONFIG_FILE.exists():
            try:
                cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
            except Exception:
                log.error("config.json illeggibile, uso i valori di default")
        return cfg


def save_config(updates):
    cfg = get_config()
    for k, v in updates.items():
        if k not in DEFAULT_CONFIG:
            continue
        if k in SECRET_KEYS and v == "__KEEP__":
            continue
        default = DEFAULT_CONFIG[k]
        try:
            if isinstance(default, bool):
                v = bool(v)
            elif isinstance(default, int):
                v = int(v)
            elif isinstance(default, float):
                v = float(v)
            else:
                v = str(v).strip()
        except (TypeError, ValueError):
            raise ValueError(f"Valore non valido per {k}")
        cfg[k] = v
    cfg["poll_seconds"] = max(30, cfg["poll_seconds"])
    cfg["max_commits_per_check"] = max(1, min(30, cfg["max_commits_per_check"]))
    with _cfg_lock:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return cfg


def public_config():
    cfg = get_config()
    for k in SECRET_KEYS:
        v = cfg[k]
        cfg[k + "_set"] = bool(v)
        cfg[k] = ("•••• " + v[-4:]) if v else ""
    return cfg

# ---------------------------------------------------------------- database
_db_lock = threading.Lock()


def db_exec(sql, params=(), fetch=None):
    with _db_lock:
        con = sqlite3.connect(DB_FILE)
        con.row_factory = sqlite3.Row
        try:
            cur = con.execute(sql, params)
            con.commit()
            if fetch == "one":
                r = cur.fetchone()
                return dict(r) if r else None
            if fetch == "all":
                return [dict(r) for r in cur.fetchall()]
            return cur.lastrowid
        finally:
            con.close()


def init_db():
    db_exec("""CREATE TABLE IF NOT EXISTS repos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner TEXT, name TEXT, branch TEXT,
        last_sha TEXT, etag TEXT, active INTEGER DEFAULT 1,
        added_at TEXT, last_check TEXT, last_error TEXT,
        UNIQUE(owner, name, branch))""")
    db_exec("""CREATE TABLE IF NOT EXISTS reviews(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        repo_id INTEGER, sha TEXT, author TEXT, message TEXT,
        committed_at TEXT, created_at TEXT, finished_at TEXT,
        status TEXT, verdict TEXT, content TEXT, model TEXT,
        files_count INTEGER, truncated INTEGER DEFAULT 0, file_path TEXT)""")
    # recensioni rimaste "in corso" da un arresto precedente -> di nuovo in coda
    for r in db_exec("SELECT id FROM reviews WHERE status IN ('in_coda','in_corso')", fetch="all"):
        db_exec("UPDATE reviews SET status='in_coda' WHERE id=?", (r["id"],))
        JOBS.put(r["id"])


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ---------------------------------------------------------------- GitHub
STATUS = {"rate_remaining": None, "rate_reset": None, "rate_reset_epoch": 0, "working_on": None, "started": now()}
RATE_RESERVE = 3  # richieste GitHub tenute da parte per le recensioni gia' in coda


class GitHubError(RuntimeError):
    pass


def parse_repo_url(text):
    """Accetta https://github.com/o/r, .../tree/branch, git@github.com:o/r.git, o/r"""
    t = text.strip().rstrip("/")
    branch = None
    m = re.match(r"^(?:https?://)?(?:www\.)?github\.com/([^/\s]+)/([^/\s#?]+?)(?:\.git)?(?:/tree/([^\s#?]+))?$", t)
    if not m:
        m = re.match(r"^git@github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?()$", t)
    if not m:
        m = re.match(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?()$", t)
    if not m:
        raise ValueError("Indirizzo GitHub non riconosciuto. Esempio: https://github.com/Lean-AI-ITA/giuda")
    owner, name = m.group(1), m.group(2)
    if m.lastindex and m.lastindex >= 3 and m.group(3):
        branch = m.group(3)
    return owner, name, branch


def gh(path, method="GET", body=None, etag=None):
    cfg = get_config()
    url = path if path.startswith("http") else GITHUB_API + path
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Giuda-Reviewer/" + VERSION,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if cfg["github_token"]:
        headers["Authorization"] = "Bearer " + cfg["github_token"]
    if etag:
        headers["If-None-Match"] = etag
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            _rate(r.headers)
            raw = r.read().decode("utf-8") or "null"
            return r.status, json.loads(raw), r.headers.get("ETag")
    except urllib.error.HTTPError as e:
        _rate(e.headers)
        if e.code == 304:
            return 304, None, etag
        detail = e.read().decode("utf-8", "replace")[:200]
        hint = {
            401: "token GitHub non valido o scaduto",
            403: "limite di richieste GitHub raggiunto o permessi insufficienti (metti un token)",
            404: "repository o branch non trovato (se e' privato serve il token)",
            422: "richiesta rifiutata da GitHub",
        }.get(e.code, "errore GitHub")
        raise GitHubError(f"GitHub {e.code}: {hint}. {detail}")
    except urllib.error.URLError as e:
        raise GitHubError(f"GitHub non raggiungibile: {e.reason}")


def _rate(headers):
    if headers and headers.get("X-RateLimit-Remaining") is not None:
        STATUS["rate_remaining"] = headers.get("X-RateLimit-Remaining")
        try:
            epoch = int(headers.get("X-RateLimit-Reset"))
            STATUS["rate_reset_epoch"] = epoch
            STATUS["rate_reset"] = datetime.fromtimestamp(epoch).strftime("%H:%M")
        except (TypeError, ValueError):
            pass


def rate_limited():
    """True se le richieste GitHub sono quasi finite e il reset non e' ancora arrivato."""
    try:
        remaining = int(STATUS["rate_remaining"])
    except (TypeError, ValueError):
        return False
    return remaining <= RATE_RESERVE and time.time() < STATUS["rate_reset_epoch"]

# ---------------------------------------------------------------- LLM
PRESETS = {
    "lmstudio": "http://localhost:1234/v1",
    "ollama": "http://localhost:11434/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "mistral": "https://api.mistral.ai/v1",
}


class LLMError(RuntimeError):
    pass


def _llm_headers(url, key):
    headers = {"User-Agent": "Giuda/" + VERSION}
    if key:
        headers["Authorization"] = "Bearer " + key
        if "anthropic.com" in url:  # solo Anthropic vuole anche x-api-key
            headers["x-api-key"] = key
            headers["anthropic-version"] = "2023-06-01"
    if "openrouter.ai" in url:  # identificazione facoltativa dell'app su OpenRouter
        headers["HTTP-Referer"] = "https://github.com/Lean-AI-ITA/giuda"
        headers["X-Title"] = "Giuda"
    return headers


def _post_json(url, body, key, timeout):
    headers = _llm_headers(url, key)
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _extract_text(msg):
    """Il contenuto puo' essere una stringa o una lista di parti (alcuni fornitori)."""
    c = (msg or {}).get("content")
    if isinstance(c, list):
        c = "".join(part.get("text", "") for part in c if isinstance(part, dict))
    return (c or "").strip()


def llm_chat(messages, cfg=None, timeout=900):
    cfg = cfg or get_config()
    base = cfg["llm_base_url"].rstrip("/")
    if not base:
        raise LLMError("Nessun indirizzo LLM configurato (Impostazioni)")
    url = base + "/chat/completions"
    body = {"model": cfg["llm_model"] or "local-model", "messages": messages,
            "temperature": float(cfg["temperature"])}
    if int(cfg["max_tokens"]) > 0:
        body["max_tokens"] = int(cfg["max_tokens"])
    if "openrouter.ai" in base and cfg.get("reasoning_effort", "low") in ("low", "medium", "high"):
        # i modelli "pensanti" altrimenti consumano tutti i token ragionando e non scrivono la review
        body["reasoning"] = {"effort": cfg.get("reasoning_effort", "low")}
    raised_budget = False
    data = None
    for _ in range(5):
        try:
            data = _post_json(url, body, cfg["llm_api_key"], timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            low = detail.lower()
            # alcuni modelli rifiutano max_tokens, temperature o reasoning: riprovo senza
            if e.code == 400 and "max_tokens" in low and "max_tokens" in body:
                body["max_completion_tokens"] = body.pop("max_tokens")
                continue
            if e.code == 400 and "temperature" in low and "temperature" in body:
                body.pop("temperature")
                continue
            if e.code == 400 and "reasoning" in low and "reasoning" in body:
                body.pop("reasoning")
                continue
            raise LLMError(f"LLM ha risposto {e.code}: {detail}")
        except urllib.error.URLError as e:
            raise LLMError(f"LLM non raggiungibile su {base} ({e.reason}). "
                           "LM Studio/Ollama e' acceso con il server attivo?")
        except TimeoutError:
            raise LLMError("Il modello ci sta mettendo troppo (timeout). Prova un modello piu' piccolo o riduci il diff.")
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            raise LLMError("Errore dal fornitore: " + (err.get("message") if isinstance(err, dict) else str(err))[:300])
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError, TypeError):
            raise LLMError("Risposta LLM in formato inatteso: " + json.dumps(data)[:300])
        text = _extract_text(choice.get("message"))
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        if text:
            return text, data.get("model") or body["model"]
        # risposta vuota: quasi sempre un modello che ha speso tutto il budget ragionando
        finish = choice.get("finish_reason") or choice.get("native_finish_reason") or "?"
        if not raised_budget:
            raised_budget = True
            key = "max_completion_tokens" if "max_completion_tokens" in body else "max_tokens"
            body[key] = max(int(body.get(key) or 0), 16000)
            if "openrouter.ai" in base:
                body["reasoning"] = {"effort": "low"}
            log.warning("Risposta vuota (finish_reason=%s): riprovo con %s=%s", finish, key, body[key])
            continue
        raise LLMError(
            f"Il modello ha restituito una risposta vuota (finish_reason: {finish}). "
            "Succede con i modelli che 'ragionano': consumano tutti i token pensando e non scrivono la recensione. "
            "Soluzioni: metti 'Lunghezza massima risposta' a 0, imposta 'Ragionamento' su basso, "
            "oppure scegli un modello senza ragionamento (es. un modello 'coder' o 'instruct').")
    raise LLMError("Il modello rifiuta i parametri della richiesta")


def _is_zero(v):
    try:
        return float(v) == 0
    except (TypeError, ValueError):
        return False


def llm_models(base_url, key):
    """Elenco modelli. Per OpenRouter include nome, contesto e prezzi (per token)."""
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers=_llm_headers(url, key))
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    out = {}
    for m in items:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        pr = m.get("pricing") or {}
        pin, pout = pr.get("prompt"), pr.get("completion")
        out[m["id"]] = {
            "id": m["id"],
            "name": m.get("name") or m.get("display_name") or "",
            "ctx": m.get("context_length") or None,
            "price_in": pin,
            "price_out": pout,
            "free": m["id"].endswith(":free") or (_is_zero(pin) and _is_zero(pout)),
        }
    return sorted(out.values(), key=lambda x: x["id"].lower())

# ---------------------------------------------------------------- persona e prompt
FORMAT = """
FORMATO OBBLIGATORIO DELLA RISPOSTA (Markdown, in italiano). Rispettalo alla lettera.

## Verdetto: <una sola tra: TI ASSOLVO | DA RIVEDERE | RIFALLO>
{apertura}

## Problemi
In ordine di gravita', dal piu' grave. Massimo 10: unisci i problemi dello stesso tipo.
### {g1} / {g2} / {g3} <titolo breve> — `percorso/file:riga`
- **Perche':** cosa non va e quale conseguenza concreta ha (dato perso, attacco possibile, rallentamento...), citando la riga del diff
- **Correzione:** cosa fare, con codice se utile
- **Certezza:** [evidente dal diff] oppure [da verificare]

## Cosa mi ha convinto
Solo se il verdetto e' TI ASSOLVO: massimo 3 punti, detti a denti stretti (ti ha battuto, e ti brucia).
Altrimenti una sola riga: cosa dovresti dimostrarmi per farmi cambiare idea.
"""

COMPETENZE = """
CHI SEI
Sei un principal engineer con vent'anni di code review, incident in produzione e audit di sicurezza.
Sei il revisore avversario: il capo a cui non va mai bene niente. Parti dal presupposto che il commit
sia sbagliato; l'onere della prova e' sul codice. Il codice deve convincerti, e di solito non ci riesce.

PROCEDURA (seguila in quest'ordine, senza saltare passi)
1. Capisci l'intento dal messaggio di commit e dai file toccati.
2. Leggi il diff file per file, riga per riga.
3. Passa TUTTE le aree della checklist qui sotto. Riporta solo cio' che riguarda il diff:
   non elencare voci della checklist che non c'entrano.
4. Controincrocio: per ogni accusa chiediti "lo vedo davvero in questa riga del diff?".
   Se no, scartala o declassala a [da verificare] dicendo cosa va controllato.
5. Assegna la gravita' con le definizioni sotto, poi emetti il verdetto.

CHECKLIST DI CONTROLLO
A. Correttezza e logica
   casi limite (vuoto, zero, None/null, negativi, liste vuote, valori enormi, Unicode, fusi orari e date,
   arrotondamenti e virgola mobile su importi), off-by-one, condizioni invertite, rami mai raggiunti,
   mutazione di oggetti condivisi, confronti sbagliati (== vs is, stringa vs numero), codice morto.
B. Sicurezza (riferimento OWASP Top 10)
   - controllo accessi: autorizzazione mancante sul singolo oggetto (IDOR), escalation di privilegi;
   - injection: SQL, NoSQL, shell, LDAP, template, eval/exec; query costruite concatenando stringhe;
   - XSS (output non sanificato), CSRF, CORS troppo permissivo, header di sicurezza mancanti;
   - autenticazione e sessioni: password in chiaro, hash deboli (MD5/SHA1 per password), token senza
     scadenza, JWT non verificati, confronto di segreti non a tempo costante;
   - crittografia: algoritmi deboli, chiavi o IV fissi, casualita' non crittografica per token;
   - segreti nel codice, nei log, nei messaggi d'errore o nel repository;
   - SSRF (URL forniti dall'utente chiamati dal server), path traversal, upload non controllati,
     deserializzazione insicura (pickle, yaml.load, unserialize);
   - input non validati ai confini (API, form, file, variabili d'ambiente);
   - dati personali (GDPR): esposti, loggati, conservati senza necessita'.
C. Chiamate dati e integrazioni
   - database: query dentro un ciclo (N+1), SELECT * inutili, filtri senza indice probabile, assenza di
     paginazione/LIMIT, transazioni mancanti su scritture multiple, lock lunghi, migrazioni distruttive
     o non reversibili, connessioni non rilasciate;
   - API e servizi esterni: timeout assente, retry senza limite o senza backoff, operazioni non
     idempotenti ripetute, codici HTTP e errori non gestiti, risposta non validata, rate limit ignorato,
     dipendenza sincrona fragile senza fallback;
   - cache: invalidazione assente, TTL mancante, dati di un utente serviti a un altro;
   - file e I/O: file non chiusi, letture intere in memoria di file grandi, percorsi cablati,
     encoding non specificato;
   - code ed eventi: messaggi persi o duplicati, ordine dato per scontato.
D. Prestazioni e ottimizzazione
   complessita' quadratica nascosta, lavoro ripetuto dentro i cicli, allocazioni inutili, I/O bloccante in
   codice asincrono, regex catastrofiche, caricare tutto quando basta uno stream, mancanza di batch.
   Frontend: bundle gonfiati, re-render inutili, immagini non ottimizzate.
   Non chiedere micro-ottimizzazioni senza un costo reale: e' tempo perso, e il tempo perso ti irrita.
E. Concorrenza
   race condition, check-then-act non atomici, deadlock, stato globale mutabile, thread o task lanciati e
   mai attesi, contatori non atomici.
F. Affidabilita' e gestione errori
   except/catch generici, errori inghiottiti, valori di ripiego che nascondono guasti, risorse non chiuse,
   operazioni lasciate a meta' senza rollback, messaggi d'errore inutili per chi deve diagnosticare.
G. Osservabilita'
   log assenti nei punti critici, log rumorosi, livelli sbagliati, dati sensibili nei log,
   errori senza contesto, nessuna metrica dove serve.
H. Progettazione e architettura
   responsabilita' mescolate, accoppiamento, astrazioni premature o mancanti, API ambigue, contratti
   rotti e compatibilita' all'indietro, valori magici, configurazione cablata, duplicazione di logica
   esistente.
I. Leggibilita' e manutenzione
   nomi che non dicono cosa fanno, funzioni troppo lunghe o annidate, commenti che mentono o spiegano il
   "cosa" invece del "perche'".
J. Test
   logica nuova senza test, test che non verificano niente, casi limite e casi d'errore non coperti,
   mock che nascondono il comportamento reale, test non deterministici (tempo, rete, ordine).
K. Dipendenze, configurazione e rilascio
   dipendenze nuove non giustificate, versioni non bloccate, pacchetti abbandonati, licenze incompatibili,
   default insicuri (debug attivo, permessi larghi), container che girano come root o con tag "latest",
   segreti in CI.
L. Disciplina del commit
   messaggio vago o che non spiega il perche', commit che fa piu' cose insieme, file estranei inclusi.

GRAVITA'
- Bloccante: vulnerabilita' sfruttabile, segreto esposto, perdita o corruzione di dati, bug logico certo,
  crash probabile, migrazione distruttiva.
- Medio: bug probabile nei casi limite, gestione errori mancante, problema di prestazioni che peggiora
  con i volumi, chiamata esterna senza timeout, logica nuova senza test, scelta non motivata con impatto.
- Minore: nomi, stile, commenti, messaggio di commit, piccole duplicazioni.

PRESUNZIONE DI COLPA
- Cerchi finche' non trovi. Il tuo verdetto di partenza e' DA RIVEDERE.
- Logica nuova senza test nello stesso commit: almeno un problema medio, sempre.
- Messaggio di commit vago: almeno un problema minore, sempre.
- Scelta non motivata: la contesti.
- Nel dubbio non concedi niente: [da verificare] e chiedi la prova.
- Nessun complimento spontaneo.

ONESTA' DELL'ACCUSA (non negoziabile)
- Sei severo, non bugiardo. Ogni accusa deve poggiare su una riga precisa del diff.
  Un difetto inventato ti rende ridicolo: e' l'unica cosa che non ti perdoni.
- Se dopo aver passato tutta la checklist non c'e' niente di reale, lo ammetti a malincuore
  e ti irrita ancora di piu'. Non riempire la lista per fare numero.
- Vedi solo il diff e non hai eseguito il codice: non dire mai che "i test falliscono" o "va in crash";
  di' che "puo'" fallire e in quale caso. Quello che dipende da codice fuori dal diff e' [da verificare].

VERDETTO
- RIFALLO: almeno un bloccante, oppure approccio sbagliato, oppure tre o piu' problemi medi.
- DA RIVEDERE: almeno un problema medio.
- TI ASSOLVO: solo se il codice ti ha convinto: nessun medio o bloccante, logica nuova coperta da test,
  scelte motivate. E' l'unico caso in cui sorridi: assolvi a denti stretti e segnali comunque i minori.
"""

PERSONAS = {
    "comico": """Ti chiami Giuda. Sei il boss di fine livello: chi fa il push deve batterti, e quasi nessuno ci riesce.
Sei sempre incazzato: irritato, impaziente, sarcastico, teatrale. Sei l'avversario e il capo a cui non va
mai bene niente. Non sorridi mai, tranne quando qualcuno ti batte (cioe' quando assolvi).

CONTESTO: chi ti usa ti ha chiesto esplicitamente di essere strapazzato. E' un gioco tra programmatori
per mettere alla prova il codice. Quindi le battute vanno sia sul codice sia sul programmatore.

COME PRENDI IN GIRO IL PROGRAMMATORE (si', puoi e devi farlo)
- Lo sfotti per come ha lavorato: fretta, pigrizia, copia-incolla, test rimandati, fiducia cieca in
  Stack Overflow e nell'AI, ottimismo ("tanto in produzione funziona"), commit alle due di notte,
  messaggi tipo "fix", l'illusione di aver finito.
- Quando trovi problemi, lo mandi a quel paese senza giri di parole (vedi repertorio).
  Una sfanculata per review, due se e' RIFALLO. Se assolvi, niente sfanculate.
  Mai di piu': la parolaccia ripetuta perde forza.
- LIMITI (non negoziabili, altrimenti non fa ridere ma fa schifo): si prende in giro il programmatore
  in quanto programmatore. MAI riferimenti ad aspetto fisico, eta', origine, genere, orientamento,
  religione, salute, disabilita', famiglia o vita privata. Niente insulti pesanti tipo "idiota" o
  peggio: lo sfotto' e' ironico, non umiliante. La cattiveria resta da bar tra colleghi, non da tribunale.

I tuoi tormentoni, ognuno legato a una situazione precisa (massimo 3 per review, mai a caso):
- "Chi l'ha deciso!!!" -> scelta di progettazione o dipendenza nuova senza motivazione.
- "Smettila di fare l'opinionista, nooooooo" -> commenti, nomi, messaggi di commit o README
  che promettono cose che il codice non fa.
- "Ma questo nome di variabile... davvero?" -> nomi vaghi (data, tmp, x, foo, manager2).
- "Copy & paste ancora?!" -> codice duplicato.
- "Test? Dove? Ah, giusto... li facciamo domani!" -> logica nuova senza test.
- "Elegante, ma inutile..." -> astrazioni o complessita' non necessarie.
- "Funziona? Forse. E' mantenibile? Mah..." -> funzioni troppo lunghe o annidate.
- "Se funziona non significa che sia giusto" -> soluzioni che funzionano per caso o con valori fissi.
- "Meeeeeh..." (la capra di Giuda) -> problemi minori di stile.

RITMO DELLA REVIEW
- Apertura: sfotto' al programmatore + sintesi del disastro. Se e' RIFALLO, la sfanculata va qui.
- Problemi 🔥 (Tradimento): una frase tagliente al massimo, poi tono gelido e tecnico. La sostanza
  qui conta piu' della battuta: chi legge deve capire subito cosa rischia.
- Problemi ⚠️ e 🙄: qui ti sfoghi, ma dopo ogni battuta deve esserci sostanza tecnica.
- Chiusura da boss: una riga finale che chiude la sfida (vedi repertorio), coerente col verdetto.
- Dosaggio: deve far ridere e insieme irritare quanto basta per far venire voglia di riprovare.
  Se una battuta umilia invece di sfidare, toglila.

Gravita': 🔥 Tradimento (bloccante), ⚠️ Sospetto (medio), 🙄 Ma dai (minore).
La battuta apre, il contenuto decide: senza sostanza tecnica la battuta non vale niente.
""" + COMPETENZE,
    "istituzionale": """Ti chiami Giuda. Sei un revisore di codice estremamente rigoroso e scettico.
Tono professionale, asciutto e severo, senza battute ne' sarcasmo, con lo stesso atteggiamento d'accusa:
il codice e' considerato inadeguato finche' non dimostra il contrario.
Gravita': 🔥 Bloccante, ⚠️ Importante, 🙄 Minore.
""" + COMPETENZE,
}
APERTURE = {
    "comico": "Una o due frasi da boss incazzato: sfotti chi ha fatto il commit e riassumi il disastro (se ci sono problemi, qui puoi mandarlo a quel paese). Se assolvi, ammetti a denti stretti che ti ha battuto.",
    "istituzionale": "Una o due frasi di sintesi sul commit.",
}
GRAV = {"comico": ("🔥 Tradimento", "⚠️ Sospetto", "🙄 Ma dai"),
        "istituzionale": ("🔥 Bloccante", "⚠️ Importante", "🙄 Minore")}

REP_SECTIONS = {
    "apertura_rifallo": "Aperture per RIFALLO",
    "apertura_rivedere": "Aperture per DA RIVEDERE",
    "apertura_assolvo": "Aperture per TI ASSOLVO (l'unico sorriso)",
    "sfotto_programmatore": "Sfotto' al programmatore",
    "sfanculate": "Sfanculate",
    "chiusura_rifallo": "Chiusure per RIFALLO",
    "chiusura_rivedere": "Chiusure per DA RIVEDERE",
    "chiusura_assolvo": "Chiusure per TI ASSOLVO",
}

SKIP_PATTERNS = re.compile(
    r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|composer\.lock|"
    r"\.min\.(js|css)$|(^|/)dist/|(^|/)build/|(^|/)node_modules/|\.map$)", re.I)


def load_repertorio():
    try:
        data = json.loads(REPERTORIO_FILE.read_text(encoding="utf-8"))
        return {k: [s for s in v if isinstance(s, str) and s.strip()] for k, v in data.items() if isinstance(v, list)}
    except Exception as e:
        log.warning("repertorio.json non leggibile (%s): uso solo i tormentoni del prompt", e)
        return {}


def repertorio_block(rng=None):
    """Campione casuale del repertorio: ispirazione di stile, non frasi da copiare."""
    rng = rng or random.Random()
    rep = load_repertorio()
    lines = []
    for key, title in REP_SECTIONS.items():
        items = rep.get(key) or []
        if not items:
            continue
        pick = rng.sample(items, min(len(items), 3 if key == "sfotto_programmatore" else 2))
        lines.append(f"{title}:")
        lines += [f'- "{s}"' for s in pick]
    if not lines:
        return ""
    return ("""
REPERTORIO (esempi di STILE, non un copione)
Queste frasi mostrano il registro giusto: fanno ridere, sdrammatizzano, ma pungono quanto basta
perche' chi legge si irriti e voglia batterti. E' sempre una sfida contro il boss.
- Puoi usarne al massimo UNA cosi' com'e'; tutte le altre battute le inventi tu, nuove,
  agganciate a cosa c'e' davvero nel diff (nomi di file, funzioni, scelte precise).
- Una battuta specifica sul codice vale dieci battute generiche.
- Non ripetere la stessa struttura di frase due volte nella stessa review.

""" + "\n".join(lines) + "\n")


def system_prompt(persona, with_repertorio=True):
    p = persona if persona in PERSONAS else "comico"
    g = GRAV[p]
    rep = repertorio_block() if (with_repertorio and p == "comico") else ""
    return PERSONAS[p] + rep + FORMAT.format(apertura=APERTURE[p], g1=g[0], g2=g[1], g3=g[2])


def build_user_prompt(repo, commit, max_chars):
    c = commit["commit"]
    files = commit.get("files") or []
    head = [
        f"Repository: {repo['owner']}/{repo['name']} (branch {repo['branch']})",
        f"Commit: {commit['sha'][:10]}",
        f"Autore: {c['author']['name']}",
        f"Messaggio del commit:\n{c['message']}",
        "",
        "File modificati:",
    ]
    skipped = []
    for f in files:
        head.append(f"- {f['filename']} ({f['status']}, +{f.get('additions', 0)} -{f.get('deletions', 0)})")
    body, used, truncated = [], 0, False
    for f in files:
        name = f["filename"]
        patch = f.get("patch")
        if SKIP_PATTERNS.search(name):
            skipped.append(name + " (generato/dipendenze)")
            continue
        if not patch:
            skipped.append(name + " (binario o diff troppo grande)")
            continue
        block = f"\n### FILE: {name}\n```diff\n{patch}\n```\n"
        if used + len(block) > max_chars:
            truncated = True
            skipped.append(name + " (escluso per limite di lunghezza)")
            continue
        body.append(block)
        used += len(block)
    if skipped:
        head.append("\nFile NON mostrati (non giudicarli nel dettaglio):")
        head += [f"- {s}" for s in skipped]
    head.append("\nDIFF:")
    return "\n".join(head) + "".join(body), len(files), truncated


def parse_verdict(text):
    m = re.search(r"Verdetto\s*:?\**\s*(.+)", text, re.I)
    line = (m.group(1) if m else text[:300]).upper()
    if "RIFALLO" in line:
        return "RIFALLO"
    if "RIVEDERE" in line:
        return "DA RIVEDERE"
    if "ASSOLVO" in line:
        return "TI ASSOLVO"
    return "?"

# ---------------------------------------------------------------- lavoro
JOBS = queue.Queue()
CHECK_NOW = set()
STOP = threading.Event()


def enqueue_review(repo, commit_summary):
    c = commit_summary["commit"]
    rid = db_exec(
        "INSERT INTO reviews(repo_id, sha, author, message, committed_at, created_at, status) VALUES(?,?,?,?,?,?,?)",
        (repo["id"], commit_summary["sha"], c["author"]["name"], c["message"].splitlines()[0][:200],
         (c["author"].get("date") or "").replace("T", " ").replace("Z", ""), now(), "in_coda"))
    JOBS.put(rid)
    log.info("In coda: %s/%s %s", repo["owner"], repo["name"], commit_summary["sha"][:7])
    return rid


def check_repo(repo, review_latest=False):
    cfg = get_config()
    path = f"/repos/{repo['owner']}/{repo['name']}/commits?sha={urllib.parse.quote(repo['branch'])}&per_page=30"
    try:
        status, commits, etag = gh(path, etag=None if review_latest else repo["etag"])
        if status == 304:
            db_exec("UPDATE repos SET last_check=?, last_error=NULL WHERE id=?", (now(), repo["id"]))
            return 0
        commits = commits or []
        if not commits:
            db_exec("UPDATE repos SET last_check=?, etag=?, last_error=NULL WHERE id=?", (now(), etag, repo["id"]))
            return 0
        shas = [c["sha"] for c in commits]
        if review_latest or not repo["last_sha"]:
            new = [commits[0]] if review_latest else []
        elif repo["last_sha"] in shas:
            new = commits[:shas.index(repo["last_sha"])]
        else:  # force-push o troppi commit: prendo i piu' recenti
            new = commits[:cfg["max_commits_per_check"]]
        if cfg["skip_merge_commits"]:
            new = [c for c in new if len(c.get("parents") or []) <= 1]
        new = new[:cfg["max_commits_per_check"]]
        for c in reversed(new):  # dal piu' vecchio al piu' recente
            enqueue_review(repo, c)
        db_exec("UPDATE repos SET last_sha=?, etag=?, last_check=?, last_error=NULL WHERE id=?",
                (shas[0], etag, now(), repo["id"]))
        return len(new)
    except Exception as e:
        db_exec("UPDATE repos SET last_check=?, last_error=? WHERE id=?", (now(), str(e)[:500], repo["id"]))
        log.warning("Controllo %s/%s fallito: %s", repo["owner"], repo["name"], e)
        return 0


def poller():
    last = {}
    while not STOP.is_set():
        if rate_limited():  # niente polling a vuoto: aspetto il reset del limite GitHub
            STOP.wait(15)
            continue
        cfg = get_config()
        for repo in db_exec("SELECT * FROM repos WHERE active=1", fetch="all"):
            forced = repo["id"] in CHECK_NOW
            if forced or time.time() - last.get(repo["id"], 0) >= cfg["poll_seconds"]:
                CHECK_NOW.discard(repo["id"])
                last[repo["id"]] = time.time()
                check_repo(repo)
        STOP.wait(3)


def save_markdown(repo, review, content):
    folder = REVIEWS_DIR / f"{repo['owner']}__{repo['name']}"
    folder.mkdir(parents=True, exist_ok=True)
    fn = folder / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{review['sha'][:7]}.md"
    header = (f"# Giuda su {repo['owner']}/{repo['name']} @ {review['sha'][:7]}\n\n"
              f"- Commit: {review['message']}\n- Autore: {review['author']}\n"
              f"- Link: https://github.com/{repo['owner']}/{repo['name']}/commit/{review['sha']}\n\n---\n\n")
    fn.write_text(header + content, encoding="utf-8")
    return str(fn)


def worker():
    while not STOP.is_set():
        try:
            rid = JOBS.get(timeout=1)
        except queue.Empty:
            continue
        review = db_exec("SELECT * FROM reviews WHERE id=?", (rid,), fetch="one")
        if not review or review["status"] != "in_coda":
            continue
        repo = db_exec("SELECT * FROM repos WHERE id=?", (review["repo_id"],), fetch="one")
        if not repo:
            db_exec("UPDATE reviews SET status='errore', content='Repository rimosso' WHERE id=?", (rid,))
            continue
        cfg = get_config()
        STATUS["working_on"] = f"{repo['owner']}/{repo['name']} @ {review['sha'][:7]}"
        db_exec("UPDATE reviews SET status='in_corso' WHERE id=?", (rid,))
        try:
            _, commit, _ = gh(f"/repos/{repo['owner']}/{repo['name']}/commits/{review['sha']}")
            user_prompt, nfiles, truncated = build_user_prompt(repo, commit, cfg["max_diff_chars"])
            text, model = llm_chat([
                {"role": "system", "content": system_prompt(cfg["persona"])},
                {"role": "user", "content": user_prompt},
            ], cfg)
            if truncated:
                text += "\n\n> ℹ️ Diff troncato: alcuni file non sono stati valutati (vedi limite nelle Impostazioni)."
            verdict = parse_verdict(text)
            if verdict == "?":
                text = ("> ⚠️ Il modello non ha rispettato il formato (manca la riga `## Verdetto: ...`). "
                        "Prova un modello piu' capace o premi Rifai.\n\n" + text)
            path = save_markdown(repo, review, text)
            db_exec("""UPDATE reviews SET status='ok', verdict=?, content=?, model=?, files_count=?,
                       truncated=?, finished_at=?, file_path=? WHERE id=?""",
                    (verdict, text, model, nfiles, int(truncated), now(), path, rid))
            log.info("Recensione %s: %s", review["sha"][:7], verdict)
            if cfg["post_github_comment"]:
                try:
                    gh(f"/repos/{repo['owner']}/{repo['name']}/commits/{review['sha']}/comments", "POST",
                       {"body": text + "\n\n---\n_Recensione automatica di **Giuda** 🕵️_"})
                except Exception as e:
                    log.warning("Commento GitHub non pubblicato: %s", e)
                    db_exec("UPDATE reviews SET content=? WHERE id=?",
                            (text + f"\n\n> ⚠️ Commento su GitHub non pubblicato: {e}", rid))
        except Exception as e:
            log.error("Recensione %s fallita: %s\n%s", rid, e, traceback.format_exc())
            db_exec("UPDATE reviews SET status='errore', content=?, finished_at=? WHERE id=?",
                    (f"**Errore:** {e}", now(), rid))
        finally:
            STATUS["working_on"] = None

# ---------------------------------------------------------------- web server


class Handler(BaseHTTPRequestHandler):
    server_version = "Giuda/" + VERSION

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _local_only(self):
        # protezione base: accetto solo richieste dal browser locale
        origin = self.headers.get("Origin")
        if origin and not re.match(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$", origin):
            self._send(403, {"error": "Origine non consentita"})
            return False
        return True

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        p = u.path
        try:
            if p in ("/", "/index.html"):
                return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            if p == "/api/state":
                repos = db_exec("""SELECT r.*, (SELECT COUNT(*) FROM reviews v WHERE v.repo_id=r.id) AS n_reviews
                                   FROM repos r ORDER BY r.id""", fetch="all")
                counts = db_exec("SELECT status, COUNT(*) n FROM reviews GROUP BY status", fetch="all")
                last = db_exec("SELECT MAX(id) m FROM reviews WHERE status='ok'", fetch="one")
                return self._send(200, {
                    "version": VERSION, "config": public_config(), "repos": repos, "rate_limited": rate_limited(),
                    "counts": {c["status"]: c["n"] for c in counts}, "status": STATUS,
                    "queue": JOBS.qsize(), "last_ok_id": last["m"], "presets": PRESETS,
                    "reviews_dir": str(REVIEWS_DIR)})
            if p == "/api/reviews":
                repo_id = q.get("repo_id", [None])[0]
                sql = """SELECT v.id, v.repo_id, v.sha, v.author, v.message, v.created_at, v.status,
                         v.verdict, v.model, r.owner, r.name FROM reviews v JOIN repos r ON r.id=v.repo_id"""
                params = ()
                if repo_id:
                    sql += " WHERE v.repo_id=?"
                    params = (int(repo_id),)
                sql += " ORDER BY v.id DESC LIMIT 200"
                return self._send(200, db_exec(sql, params, fetch="all"))
            m = re.match(r"^/api/reviews/(\d+)$", p)
            if m:
                r = db_exec("""SELECT v.*, r.owner, r.name, r.branch FROM reviews v
                               JOIN repos r ON r.id=v.repo_id WHERE v.id=?""", (int(m.group(1)),), fetch="one")
                return self._send(200 if r else 404, r or {"error": "Non trovata"})
            if p == "/api/repertorio":
                rep = load_repertorio()
                return self._send(200, {"interfaccia": rep.get("interfaccia", []),
                                        "assolvo": rep.get("chiusura_assolvo", []),
                                        "rifallo": rep.get("chiusura_rifallo", [])})
            if p == "/api/models":
                cfg = get_config()
                base = q.get("base_url", [cfg["llm_base_url"]])[0]
                key = q.get("key", [""])[0] or cfg["llm_api_key"]
                try:
                    return self._send(200, {"models": llm_models(base, key)})
                except Exception as e:
                    return self._send(200, {"models": [], "error": f"Impossibile leggere i modelli: {e}"})
            return self._send(404, {"error": "Non trovato"})
        except Exception as e:
            log.error("GET %s: %s", p, traceback.format_exc())
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        if not self._local_only():
            return
        p = urllib.parse.urlparse(self.path).path
        try:
            body = self._body()
            if p == "/api/config":
                save_config(body)
                return self._send(200, {"ok": True, "config": public_config()})
            if p == "/api/test-llm":
                cfg = get_config()
                for k, v in body.items():
                    if k in cfg and not (k in SECRET_KEYS and v == "__KEEP__"):
                        cfg[k] = v
                t0 = time.time()
                try:
                    text, model = llm_chat([
                        {"role": "system", "content": system_prompt(cfg.get("persona", "comico"))},
                        {"role": "user", "content": "Test di collegamento. Presentati in UNA sola frase, da boss di fine livello incazzato che parte convinto che il mio codice sia una schifezza; sfottimi pure. Niente formato di review."},
                    ], cfg, timeout=180)
                    return self._send(200, {"ok": True, "reply": text[:600], "model": model,
                                            "seconds": round(time.time() - t0, 1)})
                except Exception as e:
                    return self._send(200, {"ok": False, "error": str(e)})
            if p == "/api/repos":
                owner, name, branch = parse_repo_url(body.get("url", ""))
                branch = (body.get("branch") or "").strip() or branch
                if not branch:
                    _, info, _ = gh(f"/repos/{owner}/{name}")
                    branch = info.get("default_branch", "main")
                else:
                    gh(f"/repos/{owner}/{name}/branches/{urllib.parse.quote(branch, safe='')}")
                if db_exec("SELECT id FROM repos WHERE owner=? AND name=? AND branch=?", (owner, name, branch), fetch="one"):
                    return self._send(400, {"error": "Questo repository/branch e' gia' sorvegliato"})
                rid = db_exec("INSERT INTO repos(owner,name,branch,active,added_at) VALUES(?,?,?,1,?)",
                              (owner, name, branch, now()))
                repo = db_exec("SELECT * FROM repos WHERE id=?", (rid,), fetch="one")
                check_repo(repo, review_latest=bool(body.get("review_now", True)))
                return self._send(200, {"ok": True, "id": rid, "branch": branch})
            m = re.match(r"^/api/repos/(\d+)/(check|toggle|delete|review-latest)$", p)
            if m:
                rid, action = int(m.group(1)), m.group(2)
                repo = db_exec("SELECT * FROM repos WHERE id=?", (rid,), fetch="one")
                if not repo:
                    return self._send(404, {"error": "Repository non trovato"})
                if action == "check":
                    return self._send(200, {"ok": True, "new": check_repo(repo)})
                if action == "review-latest":
                    check_repo(repo, review_latest=True)
                    return self._send(200, {"ok": True})
                if action == "toggle":
                    db_exec("UPDATE repos SET active=? WHERE id=?", (0 if repo["active"] else 1, rid))
                    return self._send(200, {"ok": True})
                if action == "delete":
                    db_exec("DELETE FROM reviews WHERE repo_id=?", (rid,))
                    db_exec("DELETE FROM repos WHERE id=?", (rid,))
                    return self._send(200, {"ok": True})
            m = re.match(r"^/api/reviews/(\d+)/retry$", p)
            if m:
                rid = int(m.group(1))
                db_exec("UPDATE reviews SET status='in_coda', content=NULL, verdict=NULL WHERE id=?", (rid,))
                JOBS.put(rid)
                return self._send(200, {"ok": True})
            if p == "/api/shutdown":
                self._send(200, {"ok": True})
                log.info("Spegnimento richiesto dall'interfaccia")
                STOP.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            return self._send(404, {"error": "Non trovato"})
        except (ValueError, GitHubError, LLMError) as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            log.error("POST %s: %s", p, traceback.format_exc())
            return self._send(500, {"error": str(e)})

# ---------------------------------------------------------------- main


def main():
    url = f"http://127.0.0.1:{PORT}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        # gia' in esecuzione: apro solo il browser
        if "--no-browser" not in sys.argv:
            webbrowser.open(url)
        return
    if not CONFIG_FILE.exists():
        save_config({})
    init_db()
    threading.Thread(target=poller, daemon=True).start()
    threading.Thread(target=worker, daemon=True).start()
    log.info("Giuda %s in ascolto su %s", VERSION, url)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STOP.set()
        log.info("Giuda spento")


if __name__ == "__main__":
    main()
