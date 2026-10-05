# Contribuire a Giuda

Grazie. Sappi che la tua PR verrà giudicata.

## Regole del gioco

1. **Zero dipendenze.** Giuda usa solo la libreria standard di Python 3.9+. Una dipendenza nuova va motivata, altrimenti: *«Chi l'ha deciso!!!»*.
2. **Test.** Logica nuova senza test non passa. Lancia `python -m unittest discover -s tests -v` prima di aprire la PR.
3. **Messaggi di commit chiari.** "fix" non è un messaggio di commit.
4. **Una cosa per PR.**

## Aggiungere frasi al repertorio

È il modo più semplice per contribuire. Apri `repertorio.json` e aggiungi la frase nella sezione giusta.

Una buona frase di Giuda:
- **fa ridere e irrita insieme**, come un boss che ti provoca;
- prende in giro **il lavoro o il modo di lavorare**, non la persona;
- è **breve**: una o due frasi;
- non è un insulto pesante.

Non vengono accettate frasi su aspetto fisico, età, origine, genere, orientamento, religione, salute, disabilità, famiglia o vita privata.

## Modificare il prompt

Il prompt è in `giuda.py` (`COMPETENZE`, `PERSONAS`, `FORMAT`). Se lo cambi:
- lascia le regole di formato in fondo al prompt, perché i modelli le seguono meglio;
- mantieni la regola «nessun difetto inventato»;
- aggiorna i test in `tests/test_giuda.py` se cambi la checklist o le parole chiave.

## Segnalare un problema

Apri una issue con: versione di Giuda, sistema operativo, fornitore e modello usati e le righe pertinenti di `data/giuda.log`. **Togli chiavi e token** prima di incollare qualsiasi cosa.
