# Changelog

## [1.7.0] - 2026-10-05
### Aggiunto
- Pausa automatica del polling quando le richieste GitHub stanno per finire; riparte da sola al reset del limite.
- Avviso nell'interfaccia quando manca il token GitHub; contatore richieste evidenziato quando scende sotto 20.
### Modificato
- Organizzazione GitHub aggiornata a `Lean-AI-ITA`.

## [1.6.2] - 2026-10-05
### Corretto
- Verdetto "?" con i modelli che ragionano (es. su OpenRouter): Giuda chiede ragionamento basso, riprova da solo con più token se la risposta è vuota e, se non basta, segnala l'errore con la spiegazione.
- Recensioni senza riga del verdetto: mostrate comunque, con avviso ed etichetta "SENZA VERDETTO".
### Aggiunto
- Impostazione "Ragionamento" (solo OpenRouter): basso, medio, alto, non inviare.

## [1.6.1] - 2026-10-05
### Corretto
- Selettore modelli: l'elenco ora è sempre visibile, con ricerca, filtri per fornitore, "Solo gratis", contesto e prezzi (OpenRouter).
- La chiave OpenRouter viene inviata solo come `Authorization: Bearer`.
- La creatività accetta anche la virgola.

## [1.6.0] - 2026-10-04
### Aggiunto
- `repertorio.json`: aperture, chiusure, sfottò e sfanculate usati come esempio di stile.
- Test automatici e GitHub Actions.

## [1.5.0]
- Modalità comica da "boss di fine livello", con limiti fissi (mai sulla persona). Modalità istituzionale pulita.

## [1.4.0]
- Prompt con procedura in 5 passi e checklist in 12 aree. Avatar sempre arrabbiato, sorride solo quando assolve.

## [1.3.0]
- Presunzione di colpa: verdetto di partenza DA RIVEDERE, ma nessun difetto inventato.

## [1.2.0]
- Avatar animato in SVG e interfaccia rinnovata.

## [1.1.0]
- Tormentoni legati a situazioni precise.

## [1.0.0]
- Prima versione: sorveglianza di GitHub, recensioni con LLM locale o API, installazione automatica.
