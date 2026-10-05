# Guida a Giuda

Guida completa all'installazione e all'uso. Per una panoramica vedi il [README](../README.md).

## Indice
1. [Cosa serve](#1-cosa-serve)
2. [Installazione](#2-installazione)
3. [Collegare il modello](#3-collegare-il-modello)
4. [Collegare GitHub](#4-collegare-github)
5. [Aggiungere un repository](#5-aggiungere-un-repository)
6. [La prima sfida](#6-la-prima-sfida)
7. [Leggere una recensione](#7-leggere-una-recensione)
8. [Impostazioni](#8-impostazioni)
9. [Personalizzare il repertorio](#9-personalizzare-il-repertorio)
10. [Se qualcosa non va](#10-se-qualcosa-non-va)
11. [Aggiornare Giuda](#11-aggiornare-giuda)
12. [Disinstallazione](#12-disinstallazione)

## 1. Cosa serve

- Windows 10/11, macOS o Linux.
- Python 3.9 o superiore. Su Windows, se manca, lo installa l'installatore.
- Un modello AI: **LM Studio**, **Ollama** oppure una chiave API (OpenAI, Anthropic, OpenRouter, Mistral).
- Un account GitHub e un **token** (vedi il punto 4): senza token hai solo 60 richieste l'ora.

## 2. Installazione

### Windows

1. Scarica il repository (*Code → Download ZIP*) ed **estrailo** in una cartella fissa, per esempio `C:\Giuda`. Non avviarlo dall'interno dello zip.
2. Doppio clic su **`INSTALLA_GIUDA.bat`**.
3. Se compare «Windows ha protetto il PC», clicca **Ulteriori informazioni → Esegui comunque**: il file non ha una firma digitale.
4. Se Python manca, lo installa con winget. Se non ci riesce, scaricalo da [python.org](https://www.python.org/downloads/), spunta **Add python.exe to PATH** e rilancia il file.
5. Rispondi **S** se vuoi che Giuda parta all'accensione del PC, **N** se preferisci avviarlo dall'icona *Giuda* sul desktop.
6. Il browser si apre su `http://127.0.0.1:8765`, nella scheda **Impostazioni**.

### macOS / Linux

```bash
git clone https://github.com/Lean-AI-ITA/giuda.git
cd giuda
./installa.sh
```

Lo script chiede se attivare l'avvio automatico (launchd su macOS, systemd utente su Linux). In alternativa basta `python3 giuda.py`.

## 3. Collegare il modello

### A. LM Studio (locale)
1. Scarica un modello per il codice, preferibilmente **da almeno 14B parametri** (per esempio Qwen2.5-Coder 14B Instruct, se RAM o scheda video lo reggono).
2. Scheda **Developer**: carica il modello e attiva **Start Server** (indirizzo `localhost:1234`).
3. In Giuda: Fornitore **LM Studio** → **Carica modelli** → clicca il modello nell'elenco.

### B. Ollama (locale)
1. Da terminale: `ollama pull qwen2.5-coder:14b` (o il modello che preferisci).
2. In Giuda: Fornitore **Ollama** → **Carica modelli** → clicca il modello.

### C. API (a pagamento)
1. Scegli **OpenAI**, **Anthropic**, **OpenRouter** o **Mistral**. L'indirizzo si compila da solo (OpenRouter: `https://openrouter.ai/api/v1`).
2. Incolla la chiave API e premi **Carica modelli**.

![Il selettore dei modelli](img/selettore.png)

L'elenco ha una casella di ricerca, filtri per fornitore e **Solo gratis**. Per OpenRouter mostra anche contesto e prezzo per milione di token. Clicca un modello e finisce nel campo **Modello**.

> **Nomi OpenRouter.** I modelli si chiamano `fornitore/modello` (es. `anthropic/claude-…`, `openai/gpt-…`, `qwen/…`). È il nome giusto: va lasciato **intero, prefisso compreso**. Quelli che finiscono con `:free` sono gratuiti.

Poi premi **Prova Giuda**: se l'avatar risponde con una frase delle sue, il collegamento funziona.

### Modelli che "ragionano"

Molti modelli recenti ragionano prima di rispondere, e i token del ragionamento si contano (e si pagano) come quelli della risposta. Con un limite basso il modello può finirli tutti pensando e restituire una recensione **vuota**. Per questi modelli:

- metti **Lunghezza massima risposta** a `0`;
- metti **Ragionamento** su **Basso** (solo OpenRouter).

Se la risposta arriva comunque vuota, Giuda riprova da solo con più token; se non basta, la recensione va in **ERRORE** con la spiegazione. Per le recensioni di tutti i giorni conviene un modello **senza ragionamento** (cerca "coder" o "instruct"): è più veloce e costa meno.

> **Privacy.** Con un modello locale il codice non lascia il PC. Con un'API il diff viene inviato al fornitore.
>
> **Tono.** I modelli via API possono ammorbidire battute e parolacce di loro iniziativa. Quelli locali di solito seguono il prompt alla lettera.

## 4. Collegare GitHub

Il token è necessario in pratica: senza, GitHub concede **60 richieste l'ora**, che finiscono in fretta. Con il token sono **5.000**. Se manca, l'interfaccia lo segnala; quando le richieste stanno per finire, Giuda **mette in pausa** i controlli e riparte da solo all'orario di reset indicato in alto.

1. Su GitHub: **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. *Resource owner*: scegli l'organizzazione (es. **Lean-AI-ITA**) se i repository sono suoi.
3. *Repository access*: **Only select repositories**, poi seleziona i repository da sorvegliare.
4. *Permissions → Contents*: **Read-only**. Scegli *Read and write* solo se vuoi che Giuda pubblichi i commenti sui commit.
5. Copia il token (inizia con `github_pat_`) e incollalo nel campo **Token GitHub**.
6. Scegli la personalità e premi **Salva impostazioni**.

## 5. Aggiungere un repository

1. Scheda **Repository**: incolla l'indirizzo, per esempio `https://github.com/Lean-AI-ITA/trascrittore`. Funzionano anche `Lean-AI-ITA/trascrittore`, gli indirizzi `.git` e quelli con `/tree/branch`.
2. Lascia vuoto il branch per usare quello principale e lascia spuntato «Valuta subito l'ultimo commit».
3. Premi **Sorveglia**. In **Recensioni** compare il primo verdetto: con un modello locale può richiedere qualche minuto.

Da quel momento Giuda controlla il repository ogni 2 minuti e giudica i commit nuovi. Per non aspettare usa **Controlla ora**.

## 6. La prima sfida

Fai due prove:

- **Un commit con errori voluti**: una password nel codice, una funzione duplicata, nessun test. Giuda deve trovarli tutti.
- **Un commit pulito, con test e un messaggio chiaro**: deve assolverti controvoglia, senza inventare problemi.

Se inventa problemi, usa un modello più grande o abbassa la creatività.

## 7. Leggere una recensione

![Una recensione](img/recensione.png)

Clicca una recensione nella lista a sinistra. A destra trovi, dall'alto in basso:

1. **Intestazione**: l'avatar nell'espressione del verdetto, il verdetto, repository, commit (cliccandolo apri GitHub), autore, file e modello, il messaggio del commit e il fumetto con l'apertura di Giuda.
2. **Copia** e **Rifai**, in alto a destra.
3. **Problemi**: una scheda per problema, colorata per gravità.

   | Livello | Significato |
   |---|---|
   | Tradimento (rosso) | Bloccante: vulnerabilità, segreto esposto, perdita di dati, bug certo |
   | Sospetto (arancio) | Medio: bug probabile, errori non gestiti, chiamate senza timeout, logica senza test |
   | Ma dai (viola) | Minore: nomi, stile, commenti, messaggio di commit |

   Ogni scheda ha file e riga, il perché, la correzione e la certezza: `evidente dal diff` oppure `da verificare`.
4. **Cosa mi ha convinto**: i punti a favore se ti assolve, altrimenti cosa devi dimostrargli.
5. **La chiusura da boss**, in corsivo.

| Verdetto | Quando |
|---|---|
| RIFALLO | Almeno un bloccante, approccio sbagliato o tre o più problemi medi |
| DA RIVEDERE | Almeno un problema medio. È il verdetto di partenza |
| TI ASSOLVO | Nessun medio o bloccante, logica nuova coperta da test, scelte motivate |
| SENZA VERDETTO | Il modello ha risposto ma senza rispettare il formato: il testo è comunque visibile. Premi Rifai o usa un modello più capace |
| ERRORE | La recensione non è riuscita: il motivo è scritto nella pagina |

## 8. Impostazioni

| Impostazione | A cosa serve | Iniziale |
|---|---|---|
| Creatività | Più alta = più colorito, più bassa = più preciso | 0,3 |
| Lunghezza massima risposta | Limite di token della recensione (0 = automatico, consigliato con i modelli che ragionano) | 4.096 |
| Lunghezza massima diff | Oltre questa soglia alcuni file vengono esclusi: riduce tempi e costi | 60.000 caratteri |
| Ragionamento | Solo OpenRouter: quanto può ragionare il modello | Basso |
| Controlla ogni | Ogni quanti secondi interroga GitHub (minimo 30) | 120 |
| Massimo commit per controllo | Quanti commit valuta al massimo per giro | 5 |
| Salta i commit di merge | Evita di valutare due volte le stesse modifiche | Attivo |
| Pubblica su GitHub | Scrive la recensione come commento sul commit | Disattivo |

| Pulsante | Cosa fa |
|---|---|
| Carica modelli | Apre l'elenco dei modelli del fornitore |
| Prova Giuda | Verifica il collegamento al modello |
| Controlla ora | Interroga subito GitHub |
| Rivaluta ultimo | Rifà la recensione dell'ultimo commit |
| Pausa / Riprendi | Sospende la sorveglianza di un repository |
| Elimina | Toglie il repository e le sue recensioni |
| Rifai | Ripete una singola recensione |
| Avatar in alto | Giuda dice una frase a caso |
| Spegni Giuda | Ferma l'applicazione |

## 9. Personalizzare il repertorio

Le frasi sono in `repertorio.json`, divise per sezione: `apertura_rifallo`, `apertura_rivedere`, `apertura_assolvo`, `sfotto_programmatore`, `sfanculate`, `chiusura_rifallo`, `chiusura_rivedere`, `chiusura_assolvo`, `interfaccia`.

Aprilo con un editor di testo e aggiungi, togli o riscrivi le frasi tra virgolette, ognuna seguita da una virgola tranne l'ultima della lista. Le modifiche valgono dalla recensione successiva, senza riavviare. Se il file si rompe, Giuda continua a funzionare con i soli tormentoni.

**Il dosaggio giusto:** la frase deve far ridere e irritare insieme, come un boss che ti provoca. Se umilia invece di sfidare, toglila.

## 10. Se qualcosa non va

| Sintomo | Soluzione |
|---|---|
| LLM non raggiungibile | Il server di LM Studio non è avviato oppure Ollama è spento |
| Carica modelli non mostra niente | Controlla indirizzo e chiave; per i locali, che il server sia acceso |
| Verdetto vuoto / ERRORE "risposta vuota" | Modello che ragiona: *Lunghezza massima risposta* = 0, *Ragionamento* = Basso, oppure un modello senza ragionamento |
| SENZA VERDETTO | Il modello non ha rispettato il formato: Rifai o modello più capace |
| GitHub 404 | Repository privato senza token, token che non include quel repository o branch sbagliato |
| GitHub 403 / "GitHub in pausa" | Richieste finite: aggiungi il token. Giuda riparte da solo all'orario indicato |
| Timeout | Modello troppo lento: usane uno più piccolo o abbassa la lunghezza del diff |
| Il browser non si apre | Apri a mano `http://127.0.0.1:8765` |
| Giuda inventa problemi | Modello troppo piccolo: passa ad almeno 14B o a un'API, abbassa la creatività |
| Giuda è troppo educato | Probabilmente è il modello via API che ammorbidisce: prova un modello locale |
| Frasi sempre uguali | Aggiungi frasi nuove a `repertorio.json` |

Il dettaglio degli errori è in `data/giuda.log`.

| Cosa | Dove |
|---|---|
| Recensioni in Markdown | `recensioni/<owner>__<repo>/` |
| Frasi | `repertorio.json` |
| Impostazioni e chiavi (in chiaro) | `data/config.json` |
| Storico | `data/giuda.db` |
| Log | `data/giuda.log` |

## 11. Aggiornare Giuda

1. **Spegni Giuda**.
2. Sostituisci i file del programma con quelli nuovi. **Non cancellare** la cartella `data/` (impostazioni, chiavi, storico) né `recensioni/`. Se hai personalizzato `repertorio.json`, tieni il tuo.
3. Riavvia Giuda e ricarica la pagina con **Ctrl+F5**.

## 12. Disinstallazione

**Windows:** lancia `DISINSTALLA_GIUDA.bat`. Spegne Giuda e rimuove l'icona e l'avvio automatico. Per eliminare tutto, comprese le recensioni, cancella la cartella.

**macOS:** `launchctl unload ~/Library/LaunchAgents/ai.leanai.giuda.plist`, poi cancella il file e la cartella.

**Linux:** `systemctl --user disable --now giuda.service`, poi cancella `~/.config/systemd/user/giuda.service` e la cartella.

---

*«Game over. Torna quando sai giocare.»*
